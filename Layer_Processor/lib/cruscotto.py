"""Adapter per cruscotto-italia.dati.gov.it — scarica KPI aggregati per comune.

Il cruscotto pubblica un JSON per ciascuno dei ~7900 comuni italiani con ~30
sezioni tematiche pre-aggregate. Questo adapter scarica in parallelo tutti i
comuni e produce un CSV per sezione (indicizzato per codice ISTAT 6 cifre),
pronto per compose_tabular_join.

discover: registra le sezioni richieste.
download: fetch parallelo (ThreadPoolExecutor), produce un CSV per sezione.
"""
from __future__ import annotations

import csv
import json
import os
import ssl
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
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
_BASE = "https://cruscotto-italia.dati.gov.it/data/dashboard"
_WORKERS = 5
_TIMEOUT = 30
_RETRY = 3
_BACKOFF = 2.0

SECTION_KPI_FIELDS: dict[str, list[str]] = {
    "turismo": [
        "totale_strutture", "totale_letti", "totale_camere",
        "indice_turisticita",
    ],
    "pun": [
        "n_totale", "n_attivi", "n_non_attivi", "pct_attivi",
        "n_ac", "n_dc", "potenza_max_kw",
    ],
    "beni_culturali": [
        "n_totale", "n_arco", "n_cultural_on", "n_visitabili",
        "n_con_coordinate",
    ],
    "anac": [
        "count", "distinct_cpv", "importo_totale",
    ],
    "siope": [
        "entrate_totali", "spese_totali", "saldo",
    ],
    "runts": [
        "n_totale", "n_aps", "n_odv", "n_altri",
    ],
}


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _all_istat_codes() -> list[str]:
    """Codici ISTAT 6-cifre correnti da admin GeoJSON (fonte primaria)."""
    codes: set[str] = set()
    admin_path = (ROOT.parent / "Geography_Locations" / "outputs"
                  / "admin_municipalities.geojson")
    if admin_path.exists():
        data = json.loads(admin_path.read_text("utf-8"))
        for feat in data.get("features", []):
            key = feat.get("properties", {}).get("key")
            if key:
                codes.add(str(key).zfill(6))
    if codes:
        return sorted(codes)
    # Fallback XLSX solo se admin non disponibile
    try:
        import openpyxl
        xlsx = ROOT.parent / "Geography_Amministrativi" / "province+regioni+comuni.xlsx"
        if xlsx.exists():
            wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
            for sheet_name in ("Comuni Nord", "Comuni Sud"):
                ws = wb[sheet_name]
                rows = ws.iter_rows(values_only=True)
                headers = [str(h or "").strip() for h in next(rows)]
                prov_idx = headers.index("codice_prov_istat")
                comu_idx = headers.index("codice_comu_istat")
                for vals in rows:
                    if vals[prov_idx] is None:
                        continue
                    prov = str(int(float(str(vals[prov_idx])))).zfill(3)
                    comu = str(int(float(str(vals[comu_idx])))).zfill(3)
                    codes.add(prov + comu)
            wb.close()
    except Exception:
        pass
    return sorted(codes)


def _fetch_commune(istat: str) -> tuple[str, dict[str, Any] | None]:
    import time
    url = f"{_BASE}/{istat}.json"
    for attempt in range(_RETRY):
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_context()) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            return istat, data
        except Exception:
            if attempt < _RETRY - 1:
                time.sleep(_BACKOFF * (attempt + 1))
    return istat, None


def _datasets(source: dict[str, Any]) -> list[dict[str, Any]]:
    sections = list(source.get("cruscotto_sections") or SECTION_KPI_FIELDS.keys())
    items: list[dict[str, Any]] = []
    for sec in sections:
        items.append({
            "key": f"cruscotto_{sec}",
            "title": f"Cruscotto Italia — {sec}",
            "section": sec,
            "fields": SECTION_KPI_FIELDS.get(sec, []),
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
            "topic": str(source.get("topic") or "society"),
            "url": _BASE,
            "local_path_or_status": "discovered",
            "bytes": 0,
            "source_service": "cruscotto",
            "layer_key": item["key"],
            "metadata_url": _BASE,
            "download_mode": "cruscotto_bulk",
            "download_url": _BASE,
            "objectid": index,
        })
        manifest_datasets.append({
            "uuid": f"{source_key}:{item['key']}",
            **item,
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
        "adapter": "cruscotto",
        "inventory_count": total,
        "downloadable_count": total,
        "source_url": source.get("url") or _BASE,
        "license": source.get("license"),
        "attribution": source.get("attribution"),
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


def _extract_section_kpi(data: dict[str, Any], section: str, fields: list[str]) -> dict[str, Any]:
    sec_data = data.get(section)
    if not sec_data or not isinstance(sec_data, dict):
        return {}
    if section == "turismo":
        cap = sec_data.get("capacita_comune", {})
        if not isinstance(cap, dict):
            return {}
        return {f: cap.get(f) for f in fields if cap.get(f) is not None}
    if section == "siope":
        anno = str(sec_data.get("anno_default", ""))
        pa = sec_data.get("per_anno", {}).get(anno, {})
        if not isinstance(pa, dict):
            return {}
        out: dict[str, Any] = {}
        if pa.get("totale_anno") is not None:
            out["spese_totali"] = pa["totale_anno"]
        entrate = pa.get("entrate", {})
        if isinstance(entrate, dict) and entrate.get("totale_anno") is not None:
            out["entrate_totali"] = entrate["totale_anno"]
        if pa.get("saldo_cassa") is not None:
            out["saldo"] = pa["saldo_cassa"]
        return out
    kpi = sec_data.get("kpi", sec_data)
    if not isinstance(kpi, dict):
        return {}
    return {f: kpi.get(f) for f in fields if kpi.get(f) is not None}


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

    cache_dir = output_root / "_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    codes = _all_istat_codes()
    total_codes = len(codes)

    to_fetch = []
    cached_data: dict[str, dict[str, Any]] = {}
    for code in codes:
        cached = cache_dir / f"{code}.json"
        if not refresh and cached.exists():
            try:
                cached_data[code] = json.loads(cached.read_text("utf-8"))
            except Exception:
                to_fetch.append(code)
        else:
            to_fetch.append(code)

    fetched = len(cached_data)
    failed_codes: list[str] = []
    if to_fetch:
        import time
        batch_size = _WORKERS * 4
        for batch_start in range(0, len(to_fetch), batch_size):
            batch = to_fetch[batch_start:batch_start + batch_size]
            with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
                futures = {pool.submit(_fetch_commune, code): code for code in batch}
                for future in as_completed(futures):
                    code, data = future.result()
                    if data:
                        cached_data[code] = data
                        try:
                            (cache_dir / f"{code}.json").write_text(
                                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                                "utf-8",
                            )
                        except Exception:
                            pass
                        fetched += 1
                    else:
                        failed_codes.append(code)
            if progress and fetched % 100 == 0:
                progress(fetched, total_codes)
            if batch_start + batch_size < len(to_fetch):
                time.sleep(1.0)
        if progress:
            progress(fetched, total_codes)

    results: list[dict[str, Any]] = []
    for ds in datasets:
        section = ds["section"]
        fields = ds.get("fields") or list(SECTION_KPI_FIELDS.get(section, []))
        ds_key = ds["key"]
        csv_path = output_root / ds_key / f"{ds_key}.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        all_extra_fields: set[str] = set()
        rows_data: list[tuple[str, dict[str, Any]]] = []
        for code in codes:
            data = cached_data.get(code)
            if not data:
                continue
            extracted = _extract_section_kpi(data, section, fields)
            if extracted:
                all_extra_fields.update(extracted.keys())
                rows_data.append((code, extracted))

        sorted_fields = sorted(all_extra_fields)
        header = ["codice_istat"] + sorted_fields
        fd, tmp = tempfile.mkstemp(prefix=f".{csv_path.name}.", dir=csv_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
                writer.writeheader()
                for code, row in rows_data:
                    writer.writerow({"codice_istat": code, **row})
            os.replace(tmp, csv_path)
        except Exception:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise

        results.append({
            "uuid": ds["uuid"],
            "dataset": ds_key,
            "layer_name": ds.get("title"),
            "status": "downloaded",
            "rows": len(rows_data),
            "bytes": csv_path.stat().st_size,
            "local_path": f"{ds_key}/{ds_key}.csv",
        })
        if call_event:
            call_event({
                "id": ds["uuid"], "label": ds.get("title", ds_key),
                "status": "downloaded", "rows": len(rows_data),
            })

    summary = {
        "status": "completed",
        "mode": "cruscotto_bulk",
        "layers": len(datasets),
        "layers_downloaded": len(results),
        "layers_failed": 0,
        "comuni_fetched": fetched,
        "comuni_failed": len(failed_codes),
        "results": results,
        "message": f"Cruscotto: {fetched}/{total_codes} comuni scaricati, {len(failed_codes)} errori.",
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8",
    )
    return summary
