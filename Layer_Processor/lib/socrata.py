"""Adapter generico per una vista Socrata/SODA."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]
USER_AGENT = "LayerProcessor/1.0 (+local territorial data pipeline)"


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "uuid", "title", "topic", "url", "local_path_or_status", "bytes",
        "service_key", "layer_id", "download_mode",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _json_request(url: str, attempts: int = 4) -> Any:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(min(2 * (attempt + 1), 8))
    raise RuntimeError(f"Socrata non raggiungibile {url}: {last}")


def _query(endpoint: str, params: dict[str, Any]) -> Any:
    return _json_request(f"{endpoint}?{urlencode(params)}")


def _remote_signature(source: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(source["socrata_endpoint"])
    updated = str(source.get("updated_field") or "").strip()
    select = "count(*) as count"
    if updated:
        select += f",max({updated}) as max_update"
    rows = _query(endpoint, {"$select": select})
    row = rows[0] if rows else {}
    return {
        "count": int(row.get("count") or 0),
        "max_update": row.get("max_update"),
    }


def discover(
    source: dict[str, Any],
    _status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    key = str(source["key"])
    endpoint = str(source["socrata_endpoint"])
    signature = _remote_signature(source)
    dataset_id = str(
        source.get("socrata_dataset")
        or endpoint.rstrip("/").split("/")[-1].split(".")[0]
    )
    title = str(source.get("dataset_title") or source.get("ente") or key)
    row = {
        "uuid": f"{key}:{dataset_id}",
        "title": title,
        "topic": str(source.get("topic") or "planningCadastre"),
        "url": endpoint,
        "local_path_or_status": "discovered",
        "bytes": 0,
        "service_key": "socrata",
        "layer_id": dataset_id,
        "download_mode": "socrata_json",
    }
    catalog_path = work_dir / "catalog" / f"{key}.csv"
    manifest_path = work_dir / "catalog" / f"{key}_services.json"
    _atomic_csv(catalog_path, [row])
    manifest = {
        "source": key,
        "livello": str(source.get("livello") or "regione"),
        "services_count": 1,
        "downloadable_count": 1,
        "failures": [],
        "layers": [{
            "layer_key": dataset_id,
            "id": dataset_id,
            "name": title,
            "service_key": "socrata",
            "service": endpoint,
            "topic": row["topic"],
            "downloadable": True,
        }],
        "socrata_endpoint": endpoint,
        "page_size": int(source.get("page_size") or 50_000),
        "updated_field": str(source.get("updated_field") or ""),
        "remote_signature": signature,
    }
    _atomic_json(manifest_path, manifest)
    if progress:
        progress(1, 1)
    return {
        "status": "completed",
        "message": (
            f"Scoperta Socrata completata: {signature['count']} record "
            f"nel dataset {dataset_id}."
        ),
        "catalog": str(catalog_path),
        "manifest": str(manifest_path),
        "services": 1,
        "layers": 1,
        "downloadable_layers": 1,
        "view_only_layers": 0,
        "records": signature["count"],
        "failures": [],
        "missing_services": [],
    }


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
) -> dict[str, Any]:
    del max_services
    manifest = json.loads(manifest_path.read_text("utf-8"))
    key = str(manifest["source"])
    livello = str(manifest.get("livello") or "regione")
    layer = manifest["layers"][0]
    dataset_id = str(layer["id"])
    endpoint = str(manifest["socrata_endpoint"])
    output_root = raw_dir / livello / key
    output_path = output_root / f"{dataset_id}.json"
    summary_path = output_root / "_manifest.json"
    previous: dict[str, Any] = {}
    if summary_path.exists():
        try:
            previous = json.loads(summary_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if service_filter:
        query = service_filter.casefold().strip()
        searchable = f"{dataset_id} {layer.get('name', '')} socrata".casefold()
        if query not in searchable:
            return {
                "status": "completed",
                "message": "Nessun dataset Socrata corrisponde al filtro.",
                "layers": 1,
                "selected_layers": 0,
                "batch_layers": 0,
                "layers_downloaded": int(output_path.exists()),
                "layers_failed": 0,
                "results": previous.get("results", []),
            }

    current_signature = _remote_signature({
        "socrata_endpoint": endpoint,
        "updated_field": manifest.get("updated_field"),
    })
    up_to_date = bool(
        not refresh
        and output_path.exists()
        and output_path.stat().st_size
        and previous.get("remote_signature") == current_signature
    )
    if dry_run:
        return {
            "status": "dry_run",
            "message": (
                "Dataset Socrata già aggiornato."
                if up_to_date
                else f"Dataset Socrata da scaricare: {current_signature['count']} record."
            ),
            "layers": 0 if up_to_date else 1,
            "layers_total": 1,
        }
    if up_to_date:
        return {
            **previous,
            "status": "completed",
            "message": "Dataset Socrata già aggiornato; nessun download necessario.",
        }

    page_size = max(1, min(int(manifest.get("page_size") or 50_000), 50_000))
    expected = int(current_signature["count"])
    pages = max(1, (expected + page_size - 1) // page_size)
    records: list[dict[str, Any]] = []
    for page, offset in enumerate(range(0, expected or 1, page_size), start=1):
        call_id = f"socrata:{dataset_id}:P{page}"
        if call_event:
            call_event({
                "id": call_id,
                "label": f"{layer['name']} · batch {page}",
                "status": "running",
                "current": len(records),
                "total": expected,
            })
        rows = _query(endpoint, {"$limit": page_size, "$offset": offset, "$order": ":id"})
        records.extend(rows)
        if call_event:
            call_event({
                "id": call_id,
                "label": layer["name"],
                "status": "completed",
                "items": len(rows),
                "current": len(records),
                "total": expected,
            })
        if progress:
            progress(page, pages)
        if len(rows) < page_size:
            break
    if len(records) != expected:
        raise RuntimeError(
            f"Download Socrata incompleto: {len(records)}/{expected} record."
        )
    _atomic_json(output_path, {
        "dataset": dataset_id,
        "source": endpoint,
        "remote_signature": current_signature,
        "records": records,
    })
    result = {
        "layer_key": dataset_id,
        "service_key": "socrata",
        "layer_id": dataset_id,
        "name": layer["name"],
        "source_url": endpoint,
        "local_path": output_path.name,
        "status": "downloaded",
        "features": len(records),
        "batches": pages,
        "bytes": output_path.stat().st_size,
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }
    summary = {
        "status": "completed",
        "message": f"Download Socrata completato: {len(records)} record.",
        "layers": 1,
        "selected_layers": 1,
        "batch_layers": 1,
        "layers_downloaded": 1,
        "layers_failed": 0,
        "remote_signature": current_signature,
        "results": [result],
    }
    _atomic_json(summary_path, summary)
    return summary
