"""Adapter per fonti i cui file cambiano nome (datati) ma sono elencati in una
pagina HTML. discover scrapa la pagina, estrae i link che matchano un pattern e
li registra come dataset; il download riusa ``http_download.download`` (stesso
formato di manifest). Usato per es. da Ministero Salute (dati.salute.gov.it) e
anagrafe scuole MIUR (dati.istruzione.it), dove l'URL del CSV porta la data.
"""
from __future__ import annotations

import csv
import json
import re
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
Progress = Callable[[int, int], None]


def ssl_context() -> ssl.SSLContext:
    """Contesto permissivo: alcuni server gov.it (es. dati.salute.gov.it) rifiutano
    l'handshake TLS di default di Python; SECLEVEL=1 riabilita i cipher accettati."""
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
_UA = "Mozilla/5.0 (LayerProcessor)"


def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as resp:
        return resp.read().decode("utf-8", "replace")


def _resolve_resources(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Per ogni voce ``html_resources`` scrapa la pagina ed estrae gli href che
    matchano ``pattern`` (regex sul nome file). ``limit`` tiene i primi N per
    ordine decrescente (di norma: la versione più recente per data nel nome)."""
    specs = list(source.get("html_resources") or [])
    if not specs:
        raise ValueError(f"{source.get('key')}: html_resources non configurato")
    items: list[dict[str, Any]] = []
    for spec in specs:
        page = str(spec["page"])
        pattern = re.compile(str(spec["pattern"]), re.IGNORECASE)
        html = _fetch_html(page)
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', html)
        seen: set[str] = set()
        matched: list[str] = []
        for href in hrefs:
            if pattern.search(href.rsplit("/", 1)[-1]) and href not in seen:
                seen.add(href)
                matched.append(href)
        matched.sort(reverse=True)  # nome datato → primo = più recente
        limit = int(spec.get("limit") or 1)
        for href in matched[:limit]:
            url = urllib.parse.urljoin(spec.get("base") or page, href)
            filename = urllib.parse.unquote(href.rsplit("/", 1)[-1].split("?", 1)[0])
            items.append({
                "key": str(spec.get("key") or filename.rsplit(".", 1)[0]),
                "title": str(spec.get("title") or filename),
                "url": url,
                "filename": filename,
                "extract": bool(spec.get("extract")),
                "format": filename.rsplit(".", 1)[-1].upper() if "." in filename else "file",
            })
    if not items:
        raise RuntimeError("Nessuna risorsa trovata sulla pagina con i pattern indicati.")
    return items


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    del status_source
    source_key = str(source["key"])
    items = _resolve_resources(source)
    rows: list[dict[str, Any]] = []
    manifest_datasets: list[dict[str, Any]] = []
    total = len(items)
    for index, item in enumerate(items, start=1):
        rows.append({
            "uuid": f"{source_key}:{item['key']}",
            "title": item["title"],
            "topic": str(source.get("topic") or "society"),
            "url": str(source.get("url") or item["url"]),
            "local_path_or_status": "discovered",
            "bytes": 0,
            "source_service": "file",
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
            "extract": item["extract"],
            "format": item["format"],
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
        "adapter": "html_resources",
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
