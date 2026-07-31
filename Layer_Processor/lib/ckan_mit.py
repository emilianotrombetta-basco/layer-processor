"""Adapter CKAN (portale dati.mit.gov.it e simili).

Scarica in locale le risorse di un dataset CKAN e le SOVRASCRIVE su richiesta di
aggiornamento (refresh). Al primo giro scarica ciò che manca; con refresh riscarica
tutto. Serve per i dataset MIT che vanno scaricati e combinati offline:
  - elenco-opere-pubbliche-censite-su-portale-ainop  → layer INFRASTRUTTURE_AINOP
  - opere-incompiute                                  → layer ANALISI_URBANISTICA

discover : package_show → elenco risorse (nome, formato, url, size) → work/catalog/<key>.csv
download : scarica le risorse (formato preferito CSV>XLSX>XLS>JSON, PDF escluso) in
           raw/nazionale/<key>/<nome>.<ext>  + _manifest.json (ripresa/overwrite)
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
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]
UA = {"User-Agent": "LayerProcessor/1.0 (+territorial data pipeline)"}
FORMAT_RANK = {"CSV": 0, "XLSX": 1, "XLS": 2, "JSON": 3}  # PDF/altro esclusi di default
SKIP_FORMATS = {"PDF", "HTML", ""}


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return "_".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split()) or "risorsa"


def _api_base(source: dict[str, Any]) -> str:
    return str(source.get("ckan_api") or "https://dati.mit.gov.it/catalog/api/3/action")


def _package(source: dict[str, Any]) -> dict[str, Any]:
    url = f"{_api_base(source)}/package_show?id={source['ckan_dataset']}"
    with urlopen(Request(url, headers=UA), timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not data.get("success"):
        raise RuntimeError(f"CKAN package_show fallito per {source.get('ckan_dataset')}")
    return data["result"]


def _remote_modified(pkg: dict[str, Any]) -> str | None:
    """Data di ultimo aggiornamento del dataset (pkg + max last_modified risorse)."""
    m = pkg.get("metadata_modified")
    for r in pkg.get("resources", []):
        lm = r.get("last_modified") or r.get("created")
        if lm and (m is None or str(lm) > str(m)):
            m = lm
    return str(m) if m else None


def _state_path(key: str) -> Path:
    return STATE_DIR / f"ckan_{key}.json"


def _stored_modified(key: str) -> str | None:
    p = _state_path(key)
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8")).get("metadata_modified")
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _save_modified(key: str, modified: str | None) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    _state_path(key).write_text(json.dumps(
        {"metadata_modified": modified, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
        ensure_ascii=False), "utf-8")


def _chosen_resources(resources: list[dict[str, Any]], keep_all: bool,
                      rank: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Un file per dataset logico, scegliendo il formato secondo `rank` (default CSV>XLSX>XLS>JSON).
    Con `prefer_formats` nella fonte si può privilegiare gli XLSX. PDF escluso."""
    rank = rank or FORMAT_RANK
    if keep_all:
        return [r for r in resources if (r.get("format") or "").upper() not in SKIP_FORMATS]
    groups: dict[str, dict[str, Any]] = {}
    for r in resources:
        fmt = (r.get("format") or "").upper()
        if fmt in SKIP_FORMATS:
            continue
        key = _slug(re.sub(r"\b(csv|xlsx?|json|formato)\b", "", str(r.get("name") or ""), flags=re.I))
        cur = groups.get(key)
        if cur is None or rank.get(fmt, 9) < rank.get((cur.get("format") or "").upper(), 9):
            groups[key] = r
    return list(groups.values())


def discover(source: dict[str, Any], status_source: Any, work_dir: Path,
             progress: Progress | None = None) -> dict[str, Any]:
    pkg = _package(source)
    resources = pkg.get("resources", [])
    remote = _remote_modified(pkg)
    stored = _stored_modified(source["key"])
    needs_update = stored is None or (remote is not None and remote != stored)
    rows = []
    for i, r in enumerate(resources, 1):
        rows.append({
            "uuid": f"{source['key']}:{r.get('id')}",
            "title": r.get("name") or r.get("id"),
            "topic": pkg.get("title", ""),
            "url": r.get("url", ""),
            "local_path_or_status": "discovered",
            "bytes": r.get("size") or 0,
            "format": (r.get("format") or "").upper(),
        })
    catalog = work_dir / "catalog" / f"{source['key']}.csv"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    with catalog.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["uuid", "title", "topic", "url", "local_path_or_status", "bytes", "format"])
        w.writeheader(); w.writerows(rows)
    (work_dir / "catalog" / f"{source['key']}_services.json").write_text(json.dumps(
        {"source": source["key"], "adapter": "ckan_mit", "dataset": source["ckan_dataset"],
         "title": pkg.get("title"), "resources": len(rows), "services": rows,
         "last_modified": remote, "downloaded_modified": stored,
         "needs_update": needs_update}, ensure_ascii=False, indent=2), "utf-8")
    if progress:
        progress(len(rows), len(rows))
    return {"status": "completed", "catalog": str(catalog), "services": len(rows),
            "layers": len(rows), "last_modified": remote, "downloaded_modified": stored,
            "needs_update": needs_update, "missing_services": [], "unexpected_services": []}


def _download_file(url: str, dst: Path) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    with urlopen(Request(url, headers=UA), timeout=120) as r, tmp.open("wb") as out:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dst)
    return dst.stat().st_size


def download(source: dict[str, Any], raw_dir: Path, *, refresh: bool = False,
             keep_all_formats: bool = False, max_services: int | None = None,
             dry_run: bool = False, progress: Progress | None = None,
             call_event: CallEvent | None = None) -> dict[str, Any]:
    pkg = _package(source)
    prefer = [f.upper() for f in source.get("prefer_formats", [])]
    rank = {f: i for i, f in enumerate(prefer)} if prefer else None
    chosen = _chosen_resources(pkg.get("resources", []), keep_all_formats, rank)
    out_root = raw_dir / "nazionale" / source["key"]
    # freschezza: se la data remota è cambiata rispetto all'ultimo scarico → overwrite.
    remote = _remote_modified(pkg)
    stored = _stored_modified(source["key"])
    changed = stored is not None and remote is not None and remote != stored
    effective_refresh = refresh or changed

    def dst_of(r: dict[str, Any]) -> Path:
        ext = (r.get("format") or "bin").lower()
        return out_root / f"{_slug(r.get('name') or r.get('id'))}.{ext}"

    todo = chosen if effective_refresh else [r for r in chosen if not dst_of(r).exists()]
    if max_services is not None and max_services > 0:
        todo = todo[:max_services]
    if dry_run:
        return {"status": "dry_run", "resources_total": len(chosen), "to_download": len(todo),
                "last_modified": remote, "downloaded_modified": stored, "changed": changed,
                "message": f"CKAN {source['key']}: {len(todo)} risorse da scaricare su {len(chosen)}"
                           + (" (aggiornamento: data cambiata)" if changed else "") + "."}

    results, total = [], len(todo)
    for i, r in enumerate(todo, 1):
        dst = dst_of(r)
        try:
            n = _download_file(r["url"], dst)
            results.append({"name": r.get("name"), "format": r.get("format"),
                            "local_path": str(dst.relative_to(out_root)), "bytes": n, "status": "downloaded"})
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            results.append({"name": r.get("name"), "status": "failed", "reason": str(exc)})
        if call_event:
            call_event({"id": r.get("id", str(i)), "label": str(r.get("name"))[:60], "status": results[-1]["status"]})
        if progress:
            progress(i, total)

    available = sum(1 for r in chosen if dst_of(r).exists() and dst_of(r).stat().st_size)
    failed = sum(x["status"] == "failed" for x in results)
    complete = available >= len(chosen) and failed == 0
    if complete:  # DB allineato alla data remota: prossimo discover non chiederà update
        _save_modified(source["key"], remote)
    summary = {
        "status": "completed" if complete else ("partial" if failed else "batch_completed"),
        "mode": "ckan", "dataset": source["ckan_dataset"], "last_modified": remote,
        "layers": len(chosen), "layers_downloaded": available, "layers_failed": failed,
        "results": results,
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    return summary
