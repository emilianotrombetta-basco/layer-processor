"""Adapter Valle d'Aosta — download LIBERO dalla piattaforma SCT via proxy INVA.

I servizi ArcGIS ``domini1/rest/services/Public/*`` sono protetti da token
(HTTP 499), ma il visualizzatore pubblico li raggiunge attraverso il proxy
``INVA/config/config.ashx`` che inietta il token lato server. Passando da lì
si scaricano liberamente tutti i servizi pubblici (56), senza autenticazione
né iscrizione a SCT-Outil.

- discover : elenca i servizi Public e i loro layer → catalogo (schema Torino).
- download : query paginata per layer → GeoJSON in raw/, saltando i già presenti
             (ripresa) e con limite opzionale per esecuzione (batch). Riprendibile.
"""
from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]

PROXY = "https://mappe.regione.vda.it/INVA/config/config.ashx?"
PUBLIC = "https://mappe.regione.vda.it/domini1/rest/services/Public"
HEADERS = {
    "User-Agent": "LayerProcessor/1.0 (+territorial data pipeline)",
    "Accept": "application/json",
    "Referer": "https://mappe.regione.vda.it/pub/geourbapub/index.html",
}
# Il proxy INVA rifiuta URL troppo lunghi prima che la richiesta raggiunga
# ArcGIS. Con 1.000 objectId la seconda pagina di alcuni layer supera il limite
# HTTP; 500 mantiene sia l'URL sia la risposta entro dimensioni affidabili.
FEATURE_BATCH_SIZE = 500
_CSV_COLUMNS = [
    "uuid", "title", "topic", "url", "local_path_or_status", "bytes",
    "source_service", "layer_key", "metadata_url", "download_mode",
    "download_url", "layer_type", "geometry_type", "objectid",
]


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return "_".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split()) or "layer"


def _proxied(target: str, **params: Any) -> str:
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return PROXY + (f"{target}?{query}" if query else target)


def _get(target: str, *, attempts: int = 3, **params: Any) -> dict[str, Any]:
    url = _proxied(target, **params)
    last: Exception | None = None
    for i in range(attempts):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and data.get("error"):
                raise RuntimeError(f"ArcGIS: {data['error'].get('code')} {data['error'].get('message')}")
            return data
        except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(0.6 * (i + 1))
    raise RuntimeError(f"Richiesta fallita: {last}")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def _service_names() -> list[str]:
    data = _get(PUBLIC, f="json")
    names = []
    for s in data.get("services", []):
        if s.get("type") == "MapServer":
            names.append(str(s.get("name", "")).split("/")[-1])
    return [n for n in names if n]


def _layer_rows(service: str) -> list[dict[str, Any]]:
    """Layer foglia di un servizio, distinguendo feature e raster.

    I MapServer SCT contengono anche ortofoto e immagini satellitari. Questi
    elementi sono validi nell'inventario, ma l'endpoint ``/query?f=geojson`` è
    utilizzabile soltanto per i Feature Layer. I raster restano quindi
    censiti come riferimenti cartografici senza diventare falsi errori di
    download vettoriale.
    """
    info = _get(f"{PUBLIC}/{service}/MapServer", f="json")
    rows = []
    for layer in info.get("layers", []):
        layer_type = str(layer.get("type") or "")
        if layer_type == "Group Layer" or layer.get("subLayerIds"):
            continue
        lid = int(layer["id"])
        rows.append({
            "service": service,
            "layer_id": lid,
            "name": str(layer.get("name") or f"{service}_{lid}"),
            "layer_type": layer_type,
            "geometry_type": str(layer.get("geometryType") or ""),
            "downloadable": layer_type == "Feature Layer",
        })
    return rows


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    services = _service_names()
    if not services:
        raise RuntimeError("Nessun servizio Public elencato dal proxy VdA.")
    rows: list[dict[str, Any]] = []
    total = len(services)
    for i, service in enumerate(services, start=1):
        try:
            layers = _layer_rows(service)
        except RuntimeError:
            layers = []
        for layer in layers:
            lid = layer["layer_id"]
            metadata_url = f"{PUBLIC}/{service}/MapServer/{lid}"
            downloadable = bool(layer["downloadable"])
            query = (
                _proxied(
                    f"{metadata_url}/query",
                    where="1=1", outFields="*", returnGeometry="true",
                    outSR=4326, f="geojson",
                )
                if downloadable
                else ""
            )
            rows.append({
                "uuid": f"r_vda:{_slug(service)}:{lid:03d}",
                "title": layer["name"],
                "topic": "",
                "url": query or metadata_url,
                "local_path_or_status": "discovered" if downloadable else "metadata_only",
                "bytes": 0,
                "source_service": service,
                "layer_key": str(lid),
                "metadata_url": metadata_url,
                "download_mode": "proxy_geojson" if downloadable else "metadata_only",
                "download_url": query,
                "layer_type": layer["layer_type"],
                "geometry_type": layer["geometry_type"],
                "objectid": len(rows) + 1,
            })
        if progress and (i == total or i % 3 == 0):
            progress(i, total)

    catalog_path = work_dir / "catalog" / "r_vda.csv"
    manifest_path = work_dir / "catalog" / "r_vda_services.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with catalog_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    by_service = {s: sum(r["source_service"] == s for r in rows) for s in services}
    downloadable_rows = [
        row for row in rows if row["download_mode"] == "proxy_geojson"
    ]
    metadata_only_rows = [
        row for row in rows if row["download_mode"] == "metadata_only"
    ]
    _atomic_json(manifest_path, {
        "source": "r_vda",
        "adapter": "vda_platform",
        "proxy": PROXY,
        "services_count": len(services),
        "inventory_count": len(rows),
        "downloadable_count": len(downloadable_rows),
        "metadata_only_count": len(metadata_only_rows),
        "layers": len(rows),
        "by_service": by_service,
        # Una voce per layer scaricabile: la dashboard usa questa collezione
        # come fallback del denominatore di Download.
        "services": [{"id": r["uuid"], "name": r["title"], "service": r["source_service"]}
                     for r in downloadable_rows],
        "metadata_only": [
            {
                "id": row["uuid"],
                "name": row["title"],
                "service": row["source_service"],
                "layer_type": row["layer_type"],
                "metadata_url": row["metadata_url"],
            }
            for row in metadata_only_rows
        ],
        "auth_required": False,
    })
    return {
        "status": "completed",
        "catalog": str(catalog_path),
        "manifest": str(manifest_path),
        "services": len(services),
        "layers": len(rows),
        "downloadable_count": len(downloadable_rows),
        "metadata_only_count": len(metadata_only_rows),
        "missing_services": [],
        "unexpected_services": [],
    }


def _query_layer(query_url: str, out_path: Path, *, call_event: CallEvent | None, label: str) -> dict[str, Any]:
    """Scarica un layer paginando sugli objectIds, via proxy → GeoJSON WGS84."""
    # query_url è già proxato e contiene i parametri geojson; ricavo la base /query
    base = query_url.split(PROXY, 1)[-1].split("/query", 1)[0]  # …/MapServer/<id>
    ids = _get(f"{base}/query", where="1=1", returnIdsOnly="true", f="json").get("objectIds") or []
    if not ids:
        # nessun objectId: provo una query diretta (layer piccoli/particolari)
        data = _get(f"{base}/query", where="1=1", outFields="*", returnGeometry="true", outSR=4326, f="geojson")
        feats = data.get("features", [])
        _atomic_json(out_path, {"type": "FeatureCollection", "features": feats})
        return {"status": "downloaded", "features": len(feats), "bytes": out_path.stat().st_size}
    step = FEATURE_BATCH_SIZE
    features: list[dict[str, Any]] = []
    pages = (len(ids) + step - 1) // step
    for p in range(pages):
        batch = ids[p * step:(p + 1) * step]
        if call_event:
            call_event({"id": f"{base}:{p+1}", "label": f"{label} · pag {p+1}/{pages}",
                        "status": "running", "current": p * step, "total": len(ids)})
        data = _get(f"{base}/query", objectIds=",".join(map(str, batch)),
                    outFields="*", returnGeometry="true", outSR=4326, f="geojson")
        features.extend(data.get("features", []))
        if call_event:
            call_event({"id": f"{base}:{p+1}", "label": f"{label} · pag {p+1}/{pages}",
                        "status": "completed", "items": len(batch)})
    _atomic_json(out_path, {"type": "FeatureCollection", "features": features})
    return {"status": "downloaded", "features": len(features), "bytes": out_path.stat().st_size}


def download(
    manifest_path: Path,
    raw_dir: Path,
    *,
    service_filter: str | None = None,
    max_services: int | None = None,
    dry_run: bool = False,
    refresh: bool = False,
    progress: Progress | None = None,
    call_event: CallEvent | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    catalog = Path(manifest_path).parent / "r_vda.csv"
    rows = list(csv.DictReader(catalog.open(encoding="utf-8"))) if catalog.exists() else []
    # Il catalogo conserva anche raster e ortofoto come riferimenti utili per
    # il viewer, ma il download di questo adapter produce esclusivamente
    # GeoJSON vettoriali.
    rows = [row for row in rows if row.get("download_mode") == "proxy_geojson"]
    output_root = raw_dir / "regione" / "r_vda"
    output_root.mkdir(parents=True, exist_ok=True)
    stale = output_root / "_auth_required.json"
    if stale.exists():
        stale.unlink()

    def out_path(row: dict[str, Any]) -> Path:
        return output_root / _slug(row["source_service"]) / f"{int(row['layer_key']):03d}_{_slug(row['title'])}.geojson"

    if service_filter:
        q = _slug(service_filter)
        rows = [r for r in rows if q in _slug(r["source_service"]) or q in _slug(r["title"])]
    all_rows = rows
    if not refresh:
        rows = [r for r in all_rows if not out_path(r).exists()]
    if max_services is not None and max_services > 0:
        rows = rows[:max_services]

    def available() -> int:
        return sum(1 for r in all_rows if out_path(r).exists() and out_path(r).stat().st_size)

    if dry_run:
        return {"status": "dry_run", "layers": len(rows), "layers_total": len(all_rows),
                "message": f"Download simulato: {len(rows)} layer vettoriali nel prossimo batch, {len(all_rows)} scaricabili complessivi."}

    results: list[dict[str, Any]] = []
    total = len(rows)

    def checkpoint(status: str) -> None:
        _atomic_json(output_root / "_manifest.json", {
            "status": status, "mode": "proxy_platform", "auth_required": False,
            "layers": len(all_rows), "batch_layers": total,
            "layers_downloaded": available(),
            "layers_failed": sum(r["status"] == "failed" for r in results),
            "results": results,
        })

    for i, row in enumerate(rows, start=1):
        dst = out_path(row)
        try:
            result = _query_layer(row["download_url"], dst, call_event=call_event, label=row["title"])
        except Exception as exc:
            result = {"status": "failed", "reason": str(exc)}
        results.append({"service": row["source_service"], "layer_name": row["title"],
                        "local_path": str(dst.relative_to(output_root)) if result["status"] == "downloaded" else "",
                        **result})
        checkpoint("running")
        if progress:
            progress(i, total)

    downloaded = available()
    failed = sum(r["status"] == "failed" for r in results)
    status = "partial" if failed else ("completed" if downloaded >= len(all_rows) else "batch_completed")
    summary = {
        "status": status, "mode": "proxy_platform", "auth_required": False,
        "message": f"Elaborati {len(results)} layer vettoriali; {downloaded}/{len(all_rows)} disponibili, {failed} errori.",
        "layers": len(all_rows), "batch_layers": total,
        "layers_downloaded": downloaded, "layers_failed": failed, "results": results,
    }
    _atomic_json(output_root / "_manifest.json", summary)
    return summary
