"""Adapter per i dataflow SDMX di ISTAT (esploradati.istat.it / SDMXWS).

discover costruisce l'URL SDMX-CSV di ogni ``sdmx_datasets`` e lo registra come
dataset; il download riusa ``http_download.download`` (stesso formato di manifest).
URL dati SDMX 2.1: ``{base}/data/{agency},{id},{version}/{key}?format=csv[&start&end]``.
NB: alcuni dataflow (es. ASIA UL) sono aggregati per classe di ampiezza comune,
non per singolo comune: la granularità dipende dal dataflow.
"""
from __future__ import annotations

import csv
import json
import urllib.parse
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
Progress = Callable[[int, int], None]
CSV_COLUMNS = [
    "uuid", "title", "topic", "url", "local_path_or_status", "bytes",
    "source_service", "layer_key", "metadata_url", "download_mode",
    "download_url", "objectid",
]
_DEFAULT_BASE = "https://esploradati.istat.it/SDMXWS/rest"


def _flow_url(base: str, spec: dict[str, Any]) -> str:
    agency = str(spec.get("agency") or "IT1")
    version = str(spec.get("version") or "1.0")
    flow_ref = f"{agency},{spec['dataflow_id']},{version}"
    key = str(spec.get("key_filter") or "all")
    params: list[tuple[str, str]] = [("format", "csv")]
    if spec.get("start"):
        params.append(("startPeriod", str(spec["start"])))
    if spec.get("end"):
        params.append(("endPeriod", str(spec["end"])))
    return f"{base}/data/{flow_ref}/{key}?{urllib.parse.urlencode(params)}"


def _datasets(source: dict[str, Any]) -> list[dict[str, Any]]:
    specs = list(source.get("sdmx_datasets") or [])
    if not specs:
        raise ValueError(f"{source.get('key')}: sdmx_datasets non configurato")
    base = str(source.get("sdmx_base") or _DEFAULT_BASE).rstrip("/")
    items: list[dict[str, Any]] = []
    for spec in specs:
        items.append({
            "key": str(spec["key"]),
            "title": str(spec.get("title") or spec["key"]),
            "url": _flow_url(base, spec),
            "filename": f"{spec['key']}.csv",
            "extract": False,
            "format": "CSV",
        })
    return items


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    del status_source
    source_key = str(source["key"])
    items = _datasets(source)
    rows: list[dict[str, Any]] = []
    manifest_datasets: list[dict[str, Any]] = []
    total = len(items)
    for index, item in enumerate(items, start=1):
        rows.append({
            "uuid": f"{source_key}:{item['key']}",
            "title": item["title"],
            "topic": str(source.get("topic") or "economy"),
            "url": str(source.get("url") or item["url"]),
            "local_path_or_status": "discovered",
            "bytes": 0,
            "source_service": "sdmx",
            "layer_key": item["key"],
            "metadata_url": str(source.get("url") or ""),
            "download_mode": "http_download",
            "download_url": item["url"],
            "objectid": index,
        })
        manifest_datasets.append({
            "uuid": f"{source_key}:{item['key']}",
            "key": item["key"],
            "title": item["title"],
            "url": item["url"],
            "filename": item["filename"],
            "extract": False,
            "format": "CSV",
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
        "adapter": "istat_sdmx",
        "inventory_count": total,
        "downloadable_count": total,
        "source_url": source.get("url"),
        "license": source.get("license"),
        "datasets": manifest_datasets,
        "services": [{"id": item["uuid"], "name": item["title"]} for item in manifest_datasets],
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
