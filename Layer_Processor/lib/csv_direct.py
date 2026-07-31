"""Adapter per fonti nazionali pubblicate come file CSV a URL diretto.

Il più semplice degli adapter: ogni ``csv_datasets`` della fonte è un file CSV
scaricato tal quale in ``raw/nazionale/<source>/<dataset>/``. La conversione in
GeoJSON (per i CSV con coordinate) è demandata alla normalizzazione/composizione,
non al download. Usato per es. da ``n_mimit_carburanti`` (anagrafica impianti +
prezzi). Supporta refresh (sovrascrive) e "solo nuovi" (salta se già presente e
invariato per dimensione).
"""
from __future__ import annotations

import csv
import hashlib
import json
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


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def csv_to_geojson_points(
    csv_path: Path,
    *,
    lat_field: str,
    lon_field: str,
    delimiter: str = "|",
    skip_rows: int = 0,
) -> tuple[dict[str, Any], int, int]:
    """Converte un CSV con colonne lat/lon in una FeatureCollection di punti.
    Ritorna (collection, validi, scartati). Le righe senza coordinate valide o
    fuori dai limiti geografici plausibili per l'Italia sono scartate."""
    features: list[dict[str, Any]] = []
    skipped = 0
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for _ in range(skip_rows):
            handle.readline()
        reader = csv.DictReader(handle, delimiter=delimiter)
        for row in reader:
            lat = _to_float(row.get(lat_field))
            lon = _to_float(row.get(lon_field))
            if lat is None or lon is None or not (34.0 <= lat <= 48.5) or not (5.0 <= lon <= 20.0):
                skipped += 1
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {k: v for k, v in row.items() if k not in (lat_field, lon_field)},
            })
    return ({"type": "FeatureCollection", "features": features}, len(features), skipped)


def _datasets(source: dict[str, Any]) -> list[dict[str, Any]]:
    datasets = list(source.get("csv_datasets") or [])
    if not datasets:
        raise ValueError(f"{source.get('key')}: csv_datasets non configurato")
    return datasets


def _http_size(url: str) -> int:
    """Content-Length via HEAD (0 se ignoto/bloccato)."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return int(resp.headers.get("Content-Length") or 0)
    except Exception:
        return 0


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    del status_source
    source_key = str(source["key"])
    datasets = _datasets(source)
    rows: list[dict[str, Any]] = []
    manifest_datasets: list[dict[str, Any]] = []
    total = len(datasets)
    for index, dataset in enumerate(datasets, start=1):
        dataset_key = str(dataset["key"])
        url = str(dataset["url"])
        rows.append({
            "uuid": f"{source_key}:{dataset_key}",
            "title": str(dataset.get("title") or dataset_key),
            "topic": str(dataset.get("topic") or source.get("topic") or "economy"),
            "url": str(source.get("url") or url),
            "local_path_or_status": "discovered",
            "bytes": 0,
            "source_service": "csv",
            "layer_key": dataset_key,
            "metadata_url": str(source.get("url") or ""),
            "download_mode": "csv_direct",
            "download_url": url,
            "objectid": index,
        })
        manifest_datasets.append({
            "uuid": f"{source_key}:{dataset_key}",
            "key": dataset_key,
            "title": str(dataset.get("title") or dataset_key),
            "url": url,
            "format": "CSV",
            "geometry": dataset.get("geometry"),
            "lat_field": dataset.get("lat_field"),
            "lon_field": dataset.get("lon_field"),
            "delimiter": dataset.get("delimiter", ";"),
            "skip_rows": int(dataset.get("skip_rows") or 0),
            "join_field": dataset.get("join_field"),
            "filename": dataset.get("filename"),
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
    manifest.write_text(json.dumps({
        "source": source_key,
        "adapter": "csv_direct",
        "inventory_count": total,
        "downloadable_count": total,
        "source_url": source.get("url"),
        "license": source.get("license"),
        "datasets": manifest_datasets,
        "services": [
            {"id": item["uuid"], "name": item["title"]}
            for item in manifest_datasets
        ],
    }, ensure_ascii=False, indent=2), "utf-8")
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
    output_root = raw_dir / "nazionale" / source_key
    datasets = list(manifest.get("datasets") or [])
    if dry_run:
        return {"status": "dry_run", "layers": len(datasets)}

    results: list[dict[str, Any]] = []
    total = len(datasets)
    for index, dataset in enumerate(datasets, start=1):
        dataset_key = str(dataset["key"])
        url = str(dataset["url"])
        dataset_dir = output_root / dataset_key
        filename = dataset.get("filename") or f"{dataset_key}.csv"
        destination = dataset_dir / str(filename)
        status = "skipped"
        error = None
        size = destination.stat().st_size if destination.exists() else 0
        try:
            if refresh or not destination.exists():
                dataset_dir.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                digest = hashlib.sha256()
                written = 0
                tmp = destination.with_suffix(destination.suffix + ".tmp")
                with urllib.request.urlopen(req, timeout=180) as resp, tmp.open("wb") as out:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        out.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                tmp.replace(destination)
                size = written
                status = "downloaded"
                sha = digest.hexdigest()
            else:
                sha = None
        except Exception as exc:  # noqa: BLE001 — rete: registriamo e proseguiamo
            status = "failed"
            error = str(exc)
            sha = None
        result = {
            "uuid": dataset["uuid"],
            "dataset": dataset_key,
            "layer_name": dataset.get("title"),
            "status": status,
            "bytes": size,
        }
        if sha:
            result["sha256"] = sha
        if status in {"downloaded", "skipped"}:
            result["csv_path"] = str(destination.relative_to(output_root))
            result["local_path"] = str(destination.relative_to(output_root))
            # I CSV con coordinate diventano GeoJSON di punti: così il compose
            # (che lavora su GeoJSON) li usa senza modifiche. local_path punta al
            # GeoJSON derivato; il CSV grezzo resta in csv_path.
            if (dataset.get("geometry") == "point"
                    and dataset.get("lat_field") and dataset.get("lon_field")
                    and destination.exists()):
                geojson_path = destination.with_suffix(".geojson")
                try:
                    if refresh or status == "downloaded" or not geojson_path.exists():
                        collection, valid, dropped = csv_to_geojson_points(
                            destination,
                            lat_field=str(dataset["lat_field"]),
                            lon_field=str(dataset["lon_field"]),
                            delimiter=str(dataset.get("delimiter") or "|"),
                            skip_rows=int(dataset.get("skip_rows") or 0),
                        )
                        geojson_path.write_text(
                            json.dumps(collection, ensure_ascii=False), "utf-8"
                        )
                        result["points"] = valid
                        result["points_skipped"] = dropped
                    result["local_path"] = str(geojson_path.relative_to(output_root))
                except Exception as exc:  # noqa: BLE001 — conversione best-effort
                    result["geojson_error"] = str(exc)
        if error:
            result["error"] = error
        results.append(result)
        if call_event:
            call_event({
                "id": str(dataset["uuid"]),
                "label": str(dataset.get("title") or dataset_key),
                "status": status,
                **({"error": error} if error else {}),
            })
        if progress:
            progress(index, total)

    downloaded = sum(item["status"] in {"downloaded", "skipped"} for item in results)
    failed = sum(item["status"] == "failed" for item in results)
    summary = {
        "status": "completed" if not failed else "partial",
        "mode": "csv_direct",
        "layers": total,
        "layers_downloaded": downloaded,
        "layers_failed": failed,
        "license": manifest.get("license"),
        "results": results,
        "message": (
            f"CSV diretti: {downloaded}/{total} file disponibili, {failed} errori."
        ),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8"
    )
    return summary
