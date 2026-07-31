"""Adapter OMI — Osservatorio Mercato Immobiliare (Agenzia delle Entrate).

Scarica PERIMETRI (geometrie zone OMI) + VALORI (quotazioni €/m²) da tutta Italia
o da territori selezionati, per i semestri scelti. Nessuna autenticazione: usa gli
endpoint pubblici del viewer GeoPOI.

Catena verificata (tutti gli endpoint restituiscono dati liberi):
  zoneomi.php?richiesta=1                      → province [{PROVINCIA, DIZIONE}]
  zoneomi.php?richiesta=2&prov=SIGLA           → comuni   [{DIZIONE, CODCOM(Belfiore)}]
  zoneomi.php?richiesta=5                       → semestri [{SEMESTRE}]  (es. 20252 = 2025/2)
  zoneomi.php?richiesta=3&codcom=CC            → zone     [{ZONA, FASCIA, DIZIONE, LINK_ZONA}]
  zoneomi.php?richiesta=6&codcom=CC&semestre=S → geometrie GeoJSON per zona {zona}
  zoneomi.php?richiesta=8&codcom=CC&semestre=S&zo=ZONA → tipologie presenti [{DESCR_TIPOLOGIA}]
  stampaomi.php?CC/LINK_ZONA/S/T/ZONA/0/0      → tabella valori (compravendita/locazione min/max
                                                 per tipologia e stato conservativo)

Output: raw/nazionale/omi/<semestre>/<PROV>/<CODCOM>.geojson  (zone con valori nelle properties)
        + raw/nazionale/omi/_manifest.json (checkpoint/ripresa)

Alimenta il layer finale di composizione VALORI_OMI.
"""
from __future__ import annotations

import csv
import html
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www1.agenziaentrate.gov.it/servizi/geopoi_omi/"
HEADERS = {
    "User-Agent": "LayerProcessor/1.0 (+territorial data pipeline)",
    "Referer": BASE + "index.htm",
}
Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]

# Campi valore disponibili per feature (per la UI "scegli cosa scaricare").
VALUE_FIELDS = [
    "compravendita_min", "compravendita_max", "compravendita_sup",
    "locazione_min", "locazione_max", "locazione_sup",
]
DIMENSION_FIELDS = ["tipologia", "stato_conservativo"]


def _fetch(url: str, *, as_json: bool, attempts: int = 3) -> Any:
    last: Exception | None = None
    for i in range(attempts):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            return json.loads(body) if as_json else body
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(0.5 * (i + 1))
    raise RuntimeError(f"OMI: richiesta fallita {url}: {last}")


def _zoneomi(richiesta: int, **params: Any) -> Any:
    q = "&".join(f"{k}={v}" for k, v in params.items() if v not in (None, ""))
    return _fetch(f"{BASE}zoneomi.php?richiesta={richiesta}" + (f"&{q}" if q else ""), as_json=True)


# ---- discovery ------------------------------------------------------------
def list_province() -> list[dict[str, str]]:
    return _zoneomi(1) or []


def list_comuni(prov: str) -> list[dict[str, str]]:
    return _zoneomi(2, prov=prov) or []


def list_semestri() -> list[str]:
    rows = _zoneomi(5) or []
    return [str(r.get("SEMESTRE")) for r in rows if r.get("SEMESTRE")]


def last_n_semestri(n: int) -> list[str]:
    """Ultimi n semestri disponibili (n=10 ≈ ultimi 5 anni)."""
    return sorted(list_semestri(), reverse=True)[:max(0, n)]


def discover(work_dir: Path, progress: Progress | None = None) -> dict[str, Any]:
    province = list_province()
    semestri = sorted(list_semestri(), reverse=True)
    catalog = {
        "source": "n_omi",
        "province": province,
        "semestri": semestri,
        "value_fields": VALUE_FIELDS,
        "dimension_fields": DIMENSION_FIELDS,
        "note": "Comuni scaricati on-demand per provincia (richiesta=2). Semestri 20161→attuale.",
    }
    out = work_dir / "catalog" / "omi_catalog.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), "utf-8")
    if progress:
        progress(1, 1)
    return {"status": "completed", "catalog": str(out),
            "province": len(province), "semestri": len(semestri)}


# ---- valori (parsing tabella stampaomi.php) -------------------------------
def _clean(cell: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", cell)).replace("\xa0", " ").strip()


def _num(v: str) -> float | None:
    v = (v or "").replace(".", "").replace(",", ".").strip()
    try:
        return float(v)
    except ValueError:
        return None


def fetch_valori(codcom: str, link_zona: str, semestre: str, tip_letter: str, zona: str) -> list[dict[str, Any]]:
    """Righe quotazione per (zona, tipologia): stato conservativo + min/max compravendita/locazione."""
    url = f"{BASE}stampaomi.php?{codcom}/{link_zona}/{semestre}/{tip_letter}/{zona}/0/0"
    body = _fetch(url, as_json=False)
    rows: list[dict[str, Any]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        cells = [_clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        cells = [c for c in cells if c != ""]
        # riga dati valida = 8 celle: tip, stato, comprMin, comprMax, supC, locMin, locMax, supL
        if len(cells) == 8 and cells[0].lower() not in ("tipologia",) and cells[2].lower() != "min":
            rows.append({
                "tipologia": cells[0],
                "stato_conservativo": cells[1],
                "compravendita_min": _num(cells[2]),
                "compravendita_max": _num(cells[3]),
                "compravendita_sup": cells[4],
                "locazione_min": _num(cells[5]),
                "locazione_max": _num(cells[6]),
                "locazione_sup": cells[7],
            })
    return rows


# ---- download -------------------------------------------------------------
def _tip_letter(descr: str) -> str:
    return (descr or "?")[:1].upper()


def _resolve_comuni(scope: dict[str, Any]) -> list[dict[str, str]]:
    """scope: {mode: 'all'|'province'|'comuni', province:[SIGLE], comuni:[{prov,codcom}]}"""
    mode = scope.get("mode", "all")
    if mode == "comuni":
        return [{"CODCOM": c["codcom"], "prov": c["prov"], "DIZIONE": c.get("nome", "")}
                for c in scope.get("comuni", [])]
    prov_list = scope.get("province") if mode == "province" else [p["PROVINCIA"] for p in list_province()]
    out: list[dict[str, str]] = []
    for prov in prov_list or []:
        for c in list_comuni(prov):
            out.append({"CODCOM": c["CODCOM"], "prov": prov, "DIZIONE": c.get("DIZIONE", "")})
    return out


def _compose_comune(codcom: str, prov: str, semestre: str, fields: list[str]) -> dict[str, Any]:
    """GeoJSON delle zone OMI di un comune+semestre con valori nelle properties."""
    geo = _zoneomi(6, codcom=codcom, semestre=semestre)
    features = (geo.get("dat", {}) or {}).get("features", []) if isinstance(geo, dict) else []
    zone_meta = {z["ZONA"]: z for z in (_zoneomi(3, codcom=codcom) or []) if z.get("ZONA")}
    keep = set(fields or VALUE_FIELDS)
    out_feats = []
    for f in features:
        zona = (f.get("properties", {}) or {}).get("zona")
        meta = zone_meta.get(zona, {})
        link_zona = meta.get("LINK_ZONA", "")
        tipologie = _zoneomi(8, codcom=codcom, semestre=semestre, zo=zona) or []
        quotazioni: list[dict[str, Any]] = []
        for t in tipologie:
            descr = t.get("DESCR_TIPOLOGIA", "")
            try:
                for row in fetch_valori(codcom, link_zona, semestre, _tip_letter(descr), zona):
                    quotazioni.append({k: v for k, v in row.items()
                                       if k in DIMENSION_FIELDS or k in keep})
            except RuntimeError:
                continue
        props = {
            "codcom": codcom, "provincia": prov, "semestre": semestre,
            "zona": zona, "fascia": meta.get("FASCIA"),
            "denominazione": meta.get("DIZIONE"), "link_zona": link_zona,
            "quotazioni": quotazioni,
            "source_uuid": f"omi:{codcom}:{zona}:{semestre}",
            "source_url": BASE + "index.htm",
        }
        out_feats.append({"type": "Feature", "geometry": f.get("geometry"), "properties": props})
    return {"type": "FeatureCollection", "features": out_feats}


def download(
    raw_dir: Path,
    *,
    scope: dict[str, Any] | None = None,
    semesters: Iterable[str] | None = None,
    last_years: int | None = None,
    fields: list[str] | None = None,
    refresh: bool = False,
    max_comuni: int | None = None,
    dry_run: bool = False,
    progress: Progress | None = None,
    call_event: CallEvent | None = None,
) -> dict[str, Any]:
    scope = scope or {"mode": "all"}
    sems = list(semesters or (last_n_semestri(last_years * 2) if last_years else last_n_semestri(2)))
    fields = fields or VALUE_FIELDS
    comuni = _resolve_comuni(scope)
    jobs = [(c, s) for s in sems for c in comuni]
    out_root = raw_dir / "nazionale" / "omi"

    def out_path(codcom: str, prov: str, semestre: str) -> Path:
        return out_root / semestre / prov / f"{codcom}.geojson"

    if not refresh:
        jobs = [(c, s) for (c, s) in jobs if not out_path(c["CODCOM"], c["prov"], s).exists()]
    if max_comuni is not None and max_comuni > 0:
        jobs = jobs[:max_comuni]

    if dry_run:
        return {"status": "dry_run", "comuni": len(comuni), "semestri": sems,
                "layers": len(jobs), "fields": fields,
                "message": f"OMI simulato: {len(jobs)} (comune×semestre) da scaricare, campi {fields}."}

    results: list[dict[str, Any]] = []
    total = len(jobs)
    for i, (c, s) in enumerate(jobs, start=1):
        dst = out_path(c["CODCOM"], c["prov"], s)
        try:
            fc = _compose_comune(c["CODCOM"], c["prov"], s, fields)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(fc, ensure_ascii=False), "utf-8")
            results.append({"codcom": c["CODCOM"], "prov": c["prov"], "semestre": s,
                            "zone": len(fc["features"]), "status": "downloaded"})
        except Exception as exc:
            results.append({"codcom": c["CODCOM"], "prov": c["prov"], "semestre": s,
                            "status": "failed", "reason": str(exc)})
        if call_event:
            call_event({"id": f"{c['prov']}:{c['CODCOM']}:{s}",
                        "label": f"{c.get('DIZIONE') or c['CODCOM']} {s}",
                        "status": results[-1]["status"]})
        if progress:
            progress(i, total)

    failed = sum(r["status"] == "failed" for r in results)
    summary = {
        "status": "partial" if failed else "completed",
        "mode": "omi_geopoi", "auth_required": False,
        "comuni": len(comuni), "semestri": sems, "fields": fields,
        "downloaded": sum(r["status"] == "downloaded" for r in results),
        "failed": failed, "results": results[-200:],
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    return summary
