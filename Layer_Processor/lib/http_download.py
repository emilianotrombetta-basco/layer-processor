"""Adapter per fonti nazionali pubblicate come file a URL diretto (zip, csv, xlsx).

Ogni ``download_items`` della fonte è un file scaricato in
``raw/nazionale/<source>/<item>/``. Se ``extract: true`` e il file è uno zip, viene
estratto con l'``unzip`` di sistema (Python zipfile fallisce sugli zip Deflate64,
lezione già appresa nella pipeline Torino). Usato per es. da
``n_istat_censimento_sezioni`` (zip comuni/regionali).
"""
from __future__ import annotations

import csv
import hashlib
import json
import ssl
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
Progress = Callable[[int, int], None]


def _ssl_context() -> ssl.SSLContext:
    """Contesto permissivo per i server gov.it con handshake TLS restrittivo."""
    ctx = ssl.create_default_context()
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return ctx
CSV_COLUMNS = [
    "uuid", "title", "topic", "url", "local_path_or_status", "bytes",
    "source_service", "layer_key", "metadata_url", "download_mode",
    "download_url", "objectid",
]
_UA = "LayerProcessor/1.0 (+https://basco-t.com)"


def _items(source: dict[str, Any]) -> list[dict[str, Any]]:
    items = list(source.get("download_items") or [])
    if not items:
        raise ValueError(f"{source.get('key')}: download_items non configurato")
    return items


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    del status_source
    source_key = str(source["key"])
    items = _items(source)
    rows: list[dict[str, Any]] = []
    manifest_datasets: list[dict[str, Any]] = []
    total = len(items)
    for index, item in enumerate(items, start=1):
        item_key = str(item["key"])
        url = str(item["url"])
        rows.append({
            "uuid": f"{source_key}:{item_key}",
            "title": str(item.get("title") or item_key),
            "topic": str(item.get("topic") or source.get("topic") or "society"),
            "url": str(source.get("url") or url),
            "local_path_or_status": "discovered",
            "bytes": 0,
            "source_service": "file",
            "layer_key": item_key,
            "metadata_url": str(source.get("url") or ""),
            "download_mode": "http_download",
            "download_url": url,
            "objectid": index,
        })
        manifest_datasets.append({
            "uuid": f"{source_key}:{item_key}",
            "key": item_key,
            "title": str(item.get("title") or item_key),
            "url": url,
            "filename": item.get("filename"),
            "extract": bool(item.get("extract")),
            "format": item.get("format") or "file",
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
        "adapter": "http_download",
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


def _filename_for(item: dict[str, Any]) -> str:
    if item.get("filename"):
        return str(item["filename"])
    tail = str(item["url"]).split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return tail or f"{item['key']}.bin"


def _extract_zip(archive: Path, dest: Path) -> tuple[list[str], str | None]:
    """Estrae con l'unzip di sistema (gestisce Deflate64). Best-effort: una singola
    voce problematica (es. nome file con accento non estraibile) NON fa fallire tutto.
    Ritorna (file estratti, eventuale warning). ``stdin=DEVNULL`` evita il blocco sul
    prompt "Continue?" di unzip su write error."""
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["unzip", "-o", "-q", str(archive), "-d", str(dest)],
        check=False, capture_output=True, stdin=subprocess.DEVNULL,
    )
    files = [
        str(p.relative_to(dest.parent))
        for p in sorted(dest.rglob("*")) if p.is_file()
    ]
    warning = None
    if proc.returncode != 0:
        warning = (proc.stderr or b"").decode("utf-8", "replace").strip()[:200] or (
            f"unzip exit {proc.returncode}"
        )
    return files, warning


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
    for index, item in enumerate(datasets, start=1):
        item_key = str(item["key"])
        url = str(item["url"])
        item_dir = output_root / item_key
        filename = _filename_for(item)
        destination = item_dir / filename
        status = "skipped"
        error = None
        sha = None
        size = destination.stat().st_size if destination.exists() else 0
        extracted: list[str] = []
        extract_warning: str | None = None
        try:
            if refresh or not destination.exists():
                item_dir.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                digest = hashlib.sha256()
                written = 0
                tmp = destination.with_suffix(destination.suffix + ".tmp")
                with urllib.request.urlopen(req, timeout=600, context=_ssl_context()) as resp, tmp.open("wb") as out:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        out.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                tmp.replace(destination)
                size = written
                sha = digest.hexdigest()
                status = "downloaded"
            if item.get("extract") and destination.suffix.lower() == ".zip":
                extract_dir = item_dir / "extracted"
                if refresh or status == "downloaded" or not extract_dir.exists():
                    extracted, extract_warning = _extract_zip(destination, extract_dir)
        except Exception as exc:  # noqa: BLE001 — rete/IO: registriamo e proseguiamo
            status = "failed"
            error = str(exc)
        result = {
            "uuid": item["uuid"],
            "dataset": item_key,
            "layer_name": item.get("title"),
            "status": status,
            "bytes": size,
        }
        if sha:
            result["sha256"] = sha
        if status in {"downloaded", "skipped"}:
            result["local_path"] = str(destination.relative_to(output_root))
        if extracted:
            result["extracted_files"] = len(extracted)
        if extract_warning:
            result["extract_warning"] = extract_warning
        if error:
            result["error"] = error
        results.append(result)
        if call_event:
            call_event({
                "id": str(item["uuid"]),
                "label": str(item.get("title") or item_key),
                "status": status,
                **({"error": error} if error else {}),
            })
        if progress:
            progress(index, total)

    downloaded = sum(item["status"] in {"downloaded", "skipped"} for item in results)
    failed = sum(item["status"] == "failed" for item in results)
    summary = {
        "status": "completed" if not failed else "partial",
        "mode": "http_download",
        "layers": total,
        "layers_downloaded": downloaded,
        "layers_failed": failed,
        "license": manifest.get("license"),
        "results": results,
        "message": (
            f"File scaricati: {downloaded}/{total} disponibili, {failed} errori."
        ),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8"
    )
    return summary
