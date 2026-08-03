"""Adapter per endpoint SPARQL (es. dati.cultura.gov.it/sparql — Cultural-ON/ArCo).

discover registra le query configurate; download le esegue paginando con
LIMIT/OFFSET e materializza GeoJSON: se la riga ha variabili lat/lon → punto,
altrimenti feature senza geometria (tabella). Usato per i luoghi della cultura
geolocalizzati (→ BENI_CULTURALI / PUNTI_INTERESSE).
"""
from __future__ import annotations

import csv
import json
import os
import re
import ssl
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
Progress = Callable[[int, int], None]
CSV_COLUMNS = [
    "uuid", "title", "topic", "url", "local_path_or_status", "bytes",
    "source_service", "layer_key", "metadata_url", "download_mode",
    "download_url", "objectid",
]
_UA = "LayerProcessor/1.0 (+https://basco-t.com)"


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return ctx


def run_query(endpoint: str, query: str, timeout: int = 180) -> list[dict[str, Any]]:
    """Esegue una query SPARQL (GET) e ritorna i bindings JSON."""
    url = f"{endpoint}?{urllib.parse.urlencode({'query': query})}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/sparql-results+json", "User-Agent": _UA,
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return payload.get("results", {}).get("bindings", [])


def _feature(row: dict[str, Any], lat_var: str | None, lon_var: str | None) -> dict[str, Any]:
    geometry = None
    if lat_var and lon_var and lat_var in row and lon_var in row:
        try:
            lat = float(row[lat_var]["value"])
            lon = float(row[lon_var]["value"])
            if 34.0 <= lat <= 48.5 and 5.0 <= lon <= 20.0:
                geometry = {"type": "Point", "coordinates": [lon, lat]}
        except (ValueError, KeyError):
            geometry = None
    props = {
        k: v.get("value")
        for k, v in row.items()
        if k not in {lat_var, lon_var}
    }
    return {"type": "Feature", "geometry": geometry, "properties": props}


def _datasets(source: dict[str, Any]) -> list[dict[str, Any]]:
    datasets = list(source.get("sparql_datasets") or [])
    if not datasets:
        raise ValueError(f"{source.get('key')}: sparql_datasets non configurato")
    return datasets


def _paged_query(query: str, limit: int, offset: int) -> str:
    """Normalizza una query e applica una sola clausola LIMIT/OFFSET."""
    normalized = str(query).strip().rstrip(";").rstrip()
    normalized = re.sub(
        r"\s+(?:LIMIT\s+\d+(?:\s+OFFSET\s+\d+)?|OFFSET\s+\d+)\s*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).rstrip()
    return f"{normalized}\nLIMIT {int(limit)} OFFSET {int(offset)}"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    del status_source
    source_key = str(source["key"])
    endpoint = str(source["sparql_endpoint"])
    datasets = _datasets(source)
    rows: list[dict[str, Any]] = []
    manifest_datasets: list[dict[str, Any]] = []
    total = len(datasets)
    for index, ds in enumerate(datasets, start=1):
        rows.append({
            "uuid": f"{source_key}:{ds['key']}",
            "title": str(ds.get("title") or ds["key"]),
            "topic": str(source.get("topic") or "culturalHeritage"),
            "url": str(source.get("url") or endpoint),
            "local_path_or_status": "discovered",
            "bytes": 0,
            "source_service": "sparql",
            "layer_key": str(ds["key"]),
            "metadata_url": str(source.get("url") or ""),
            "download_mode": "sparql",
            "download_url": endpoint,
            "objectid": index,
        })
        manifest_datasets.append({
            "uuid": f"{source_key}:{ds['key']}",
            "key": str(ds["key"]),
            "title": str(ds.get("title") or ds["key"]),
            "query": str(ds["query"]),
            "lat_var": ds.get("lat_var"),
            "lon_var": ds.get("lon_var"),
            "page_size": int(ds.get("page_size") or 10000),
            "max_rows": int(ds.get("max_rows") or 300000),
            "downloadable": True,
        })
        if progress:
            progress(index, total)

    catalog = work_dir / "catalog" / f"{source_key}.csv"
    manifest = work_dir / "catalog" / f"{source_key}_services.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    with catalog.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    _atomic_write_text(manifest, json.dumps({
        "source": source_key,
        "adapter": "sparql_source",
        "endpoint": endpoint,
        "inventory_count": total,
        "downloadable_count": total,
        "source_url": source.get("url"),
        "license": source.get("license") or "non dichiarata nel registry",
        "attribution": source.get("attribution") or source.get("ente") or source_key,
        "datasets": manifest_datasets,
        "services": [{"id": item["uuid"], "name": item["title"]} for item in manifest_datasets],
    }, ensure_ascii=False, indent=2))
    return {
        "status": "completed",
        "catalog": str(catalog),
        "manifest": str(manifest),
        "services": total,
        "layers": total,
        "downloadable_count": total,
        "missing_services": [],
    }


def download(
    manifest_path: Path,
    raw_dir: Path,
    *,
    dry_run: bool = False,
    refresh: bool = False,
    progress: Progress | None = None,
    call_event: Callable[[dict[str, Any]], None] | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text("utf-8"))
    source_key = str(manifest["source"])
    endpoint = str(manifest["endpoint"])
    output_root = raw_dir / "nazionale" / source_key
    datasets = list(manifest.get("datasets") or [])
    if dry_run:
        return {"status": "dry_run", "layers": len(datasets)}

    results: list[dict[str, Any]] = []
    total = len(datasets)
    for index, ds in enumerate(datasets, start=1):
        ds_key = str(ds["key"])
        dataset_dir = output_root / ds_key
        destination = dataset_dir / f"{ds_key}.geojson"
        status = "skipped"
        error = None
        count = 0
        if refresh or not destination.exists():
            page = int(ds.get("page_size") or 10000)
            max_rows = int(ds.get("max_rows") or 300000)
            lat_var, lon_var = ds.get("lat_var"), ds.get("lon_var")
            offset = 0
            temp_name: str | None = None
            try:
                dataset_dir.mkdir(parents=True, exist_ok=True)
                fd, temp_name = tempfile.mkstemp(
                    prefix=f".{destination.name}.", suffix=".tmp", dir=dataset_dir
                )
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write('{"type":"FeatureCollection","features":[')
                    first = True
                    while offset < max_rows:
                        query = _paged_query(str(ds["query"]), page, offset)
                        bindings = run_query(endpoint, query)
                        if not bindings:
                            break
                        for row in bindings:
                            if not first:
                                handle.write(",")
                            handle.write(json.dumps(
                                _feature(row, lat_var, lon_var),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ))
                            first = False
                            count += 1
                        offset += page
                        if len(bindings) < page:
                            break
                    handle.write("]}")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, destination)
                temp_name = None
                status = "downloaded"
            except Exception as exc:  # noqa: BLE001 — endpoint SPARQL: registra e prosegue
                status = "failed"
                error = str(exc)
                if temp_name:
                    try:
                        os.unlink(temp_name)
                    except FileNotFoundError:
                        pass
        result = {
            "uuid": ds["uuid"],
            "dataset": ds_key,
            "layer_name": ds.get("title"),
            "status": status,
            "features": count,
            "bytes": destination.stat().st_size if destination.exists() else 0,
        }
        if status in {"downloaded", "skipped"}:
            result["local_path"] = str(destination.relative_to(output_root))
        if error:
            result["error"] = error
        results.append(result)
        if call_event:
            call_event({
                "id": str(ds["uuid"]), "label": str(ds.get("title") or ds_key),
                "status": status, **({"error": error} if error else {}),
            })
        if progress:
            progress(index, total)

    downloaded = sum(r["status"] in {"downloaded", "skipped"} for r in results)
    failed = sum(r["status"] == "failed" for r in results)
    summary = {
        "status": "completed" if not failed else "partial",
        "mode": "sparql",
        "layers": total,
        "layers_downloaded": downloaded,
        "layers_failed": failed,
        "results": results,
        "message": f"SPARQL: {downloaded}/{total} query materializzate, {failed} errori.",
    }
    output_root.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        output_root / "_manifest.json",
        json.dumps({
            **summary,
            "source_url": manifest.get("source_url"),
            "endpoint": endpoint,
            "license": manifest.get("license") or "non dichiarata nel registry",
            "attribution": manifest.get("attribution") or source_key,
        }, ensure_ascii=False, indent=2),
    )
    return summary
