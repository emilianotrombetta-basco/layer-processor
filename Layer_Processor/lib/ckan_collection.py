"""Adapter CKAN 'collection': raccoglie le risorse (GeoJSON) di PIÙ dataset che
corrispondono a organizzazioni + pattern di titolo, in un'unica fonte.

A differenza di ``ckan_mit`` (un solo ``ckan_dataset``), qui la fonte dichiara
``organizations`` e ``title_patterns`` e l'adapter risolve dinamicamente i
dataset via ``package_search``, scaricando le risorse del formato voluto. Utile
per aggregare, es., "Servizi sul territorio" + "Luoghi e punti di interesse" di
tutte le Comunità di Valle in un'unica fonte SERVIZI_POLARITA.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

Progress = Callable[[int, int], None]
USER_AGENT = "LayerProcessor/1.0 (+local territorial data pipeline)"


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _slug(value: str) -> str:
    return _norm(value).replace(" ", "_") or "risorsa"


def _api(source: dict[str, Any]) -> str:
    return str(source.get("ckan_api") or "https://dati.trentino.it/api/3/action").rstrip("/")


def _get(url: str, *, timeout: int = 60) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def _matching_resources(source: dict[str, Any]) -> list[dict[str, Any]]:
    api = _api(source)
    orgs = source.get("organizations") or [None]
    patterns = [_norm(p) for p in (source.get("title_patterns") or [])]
    formats = {str(f).upper() for f in (source.get("formats") or ["GEOJSON"])}
    out: list[dict[str, Any]] = []
    for org in orgs:
        fq = f"organization:{org}" if org else "*:*"
        data = _get(f"{api}/package_search?{urlencode({'fq': fq, 'rows': 500})}")["result"]
        for pkg in data.get("results", []):
            title_norm = _norm(pkg.get("title") or "")
            if patterns and not any(p in title_norm for p in patterns):
                continue
            for res in pkg.get("resources", []):
                fmt = (res.get("format") or "").upper()
                if not any(fmt.startswith(f) for f in formats):
                    continue
                out.append({
                    "dataset": pkg.get("name"),
                    "dataset_title": pkg.get("title"),
                    "organization": (pkg.get("organization") or {}).get("name"),
                    "resource_id": res.get("id"),
                    "name": res.get("name") or pkg.get("title"),
                    "format": fmt,
                    "url": res.get("url"),
                })
    return out


def discover(source: dict[str, Any], _status_source: Any, work_dir: Path,
             progress: Progress | None = None) -> dict[str, Any]:
    key = str(source["key"])
    resources = _matching_resources(source)
    rows = [{
        "uuid": f"{key}:{r['dataset']}:{r['resource_id']}",
        "title": r["dataset_title"],
        "topic": str(source.get("topic") or "structure"),
        "url": r["url"],
        "local_path_or_status": "discovered",
        "bytes": 0,
        "format": r["format"],
    } for r in resources]
    catalog_path = work_dir / "catalog" / f"{key}.csv"
    manifest_path = work_dir / "catalog" / f"{key}_services.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = catalog_path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["uuid", "title", "topic", "url", "local_path_or_status", "bytes", "format"])
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(catalog_path)
    _atomic_json(manifest_path, {
        "source": key, "adapter": "ckan_collection",
        "livello": str(source.get("livello") or "regione"),
        "resources": resources,
    })
    return {
        "status": "completed",
        "message": f"Scoperta CKAN collection: {len(resources)} risorse da {len({r['dataset'] for r in resources})} dataset.",
        "catalog": str(catalog_path), "manifest": str(manifest_path),
        "services": len(resources), "layers": len(resources),
        "downloadable_layers": len(resources), "view_only_layers": 0,
        "missing_services": [], "failures": [],
    }


def download(manifest_path: Path, raw_dir: Path, *, token_env: str | None = None,
             service_filter: str | None = None, max_services: int | None = None,
             dry_run: bool = False, refresh: bool = False,
             progress: Progress | None = None, call_event: Any = None) -> dict[str, Any]:
    del token_env, call_event
    manifest = json.loads(manifest_path.read_text("utf-8"))
    key = str(manifest.get("source") or manifest_path.stem.replace("_services", ""))
    livello = str(manifest.get("livello") or "regione")
    resources = manifest.get("resources", [])
    if service_filter:
        q = _norm(service_filter)
        resources = [r for r in resources if q in _norm(f"{r.get('dataset_title', '')} {r.get('organization', '')}")]

    output_root = raw_dir / livello / key

    def rel(r: dict[str, Any]) -> Path:
        return Path(f"{_slug(r.get('organization') or 'org')}__{_slug(r.get('dataset_title') or r.get('name'))}.geojson")

    todo = resources if refresh else [r for r in resources if not (output_root / rel(r)).exists()]
    if max_services is not None and max_services > 0:
        todo = todo[:max_services]
    if dry_run:
        return {"status": "dry_run", "message": f"Download simulato: {len(todo)} risorse, {len(resources)} totali.",
                "layers": len(todo), "layers_total": len(resources)}

    results: list[dict[str, Any]] = []
    for i, r in enumerate(todo, 1):
        dst = output_root / rel(r)
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            request = Request(r["url"], headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=180) as response:
                data = response.read()
            tmp = dst.with_suffix(".geojson.tmp")
            tmp.write_bytes(data)
            tmp.replace(dst)
            results.append({"dataset": r.get("dataset"), "local_path": str(rel(r)),
                            "status": "downloaded", "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()})
        except Exception as exc:
            results.append({"dataset": r.get("dataset"), "status": "failed", "reason": str(exc)})
        if progress:
            progress(i, len(todo))

    failed = sum(x["status"] == "failed" for x in results)
    downloaded = sum((output_root / rel(r)).exists() for r in resources)
    status = "partial" if failed else ("completed" if downloaded >= len(resources) else "batch_completed")
    summary = {"status": status,
               "message": f"CKAN collection: {len(results)} risorse elaborate; {downloaded}/{len(resources)} disponibili, {failed} errori.",
               "layers": len(resources), "layers_downloaded": downloaded, "layers_failed": failed, "results": results}
    _atomic_json(output_root / "_manifest.json", summary)
    return summary
