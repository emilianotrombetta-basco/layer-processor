"""Metadati PRG comunali VdA dal geoportale (WordPress) + stato ufficiale.

NON scarica geometrie (quelle arrivano da vda_platform: PRG_Prescrittiva/Motivazionale).
Estrae METADATI utili a PIANI_MATURITA e alla copertura:

- dal feed WordPress ``category/pianificazione/prg`` (wp-json): per ogni comune il
  ``codcom`` (dal link geourbapub) e le date di inserimento/aggiornamento del PRG;
- (best-effort) dallo strato ufficiale ``ServiziGlobali/Siti/MapServer/3``:
  ``codcom → comune → stato_prg`` (adeguamento al PTP), che dà il nome comune e lo stato.

Output: ``work/metadata/r_vda_prg_updates.json`` — un record per comune (codcom).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "LayerProcessor/1.0 (+territorial data pipeline)", "Accept": "application/json"}

WP_API = ("https://geoportale.regione.vda.it/wp-json/wp/v2/posts"
          "?categories=5&per_page=100&_fields=id,slug,date,modified,title,link")
PROXY = "https://mappe.regione.vda.it/INVA/config/config.ashx?"
SITI3 = "https://mappe.regione.vda.it/foundation/rest/services/ServiziGlobali/Siti/MapServer/3"
STATUS_CODES = {
    "INA": "Iter non avviato", "AFF": "Affiancamento", "BCV": "Bozza in corso di valutazione",
    "BVT": "Bozza valutata", "VIC": "Testo definitivo in corso di valutazione",
    "APC": "Approvato, privo di cartografia numerica", "APP": "Approvato",
}


def _get_json(url: str) -> Any:
    with urlopen(Request(url, headers=UA), timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def _codcom(link: str) -> str | None:
    m = re.search(r"codcom=0*(\d+)", link or "")
    return m.group(1).zfill(3) if m else None


def _wp_events() -> dict[str, dict[str, Any]]:
    """codcom -> {events:[{date,modified,title,link}], last_update}."""
    posts = _get_json(WP_API)
    by: dict[str, dict[str, Any]] = {}
    for p in posts if isinstance(posts, list) else []:
        link = p.get("link", "")
        cc = _codcom(link)
        if not cc:
            continue
        rec = by.setdefault(cc, {"codcom": cc, "events": []})
        rec["events"].append({
            "date": p.get("date"), "modified": p.get("modified"),
            "title": _strip(p.get("title", {}).get("rendered", "")), "link": link,
        })
    for rec in by.values():
        rec["events"].sort(key=lambda e: e.get("modified") or e.get("date") or "", reverse=True)
        rec["last_prg_update"] = rec["events"][0].get("modified") or rec["events"][0].get("date")
    return by


def _official_status() -> dict[str, dict[str, Any]]:
    """codcom -> {comune, stato_prg, stato_prg_desc} dallo strato Siti (best-effort)."""
    for url in (f"{SITI3}/query?where=1%3D1&outFields=*&returnGeometry=false&f=json",
                PROXY + f"{SITI3}/query?where=1%3D1&outFields=*&returnGeometry=false&f=json"):
        try:
            data = _get_json(url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            continue
        feats = data.get("features") if isinstance(data, dict) else None
        if not feats:
            continue
        out: dict[str, dict[str, Any]] = {}
        for f in feats:
            a = f.get("attributes", {})
            cc = str(a.get("codcom") or "").zfill(3)
            code = str(a.get("stato_prg") or "").strip().upper()
            if cc == "000" or code == "XXX":  # riga aggregata/placeholder ('EUROPA')
                continue
            out[cc] = {
                "comune": a.get("comune"),
                "stato_prg": code or None,
                "stato_prg_desc": STATUS_CODES.get(code),
            }
        if out:
            return out
    return {}


def fetch(output_dir: Path | None = None) -> dict[str, Any]:
    output_dir = output_dir or (ROOT / "work" / "metadata")
    output_dir.mkdir(parents=True, exist_ok=True)
    events = _wp_events()
    status = _official_status()
    codcoms = sorted(set(events) | set(status))
    records = []
    for cc in codcoms:
        rec = {"codcom": cc, **status.get(cc, {}), **events.get(cc, {})}
        records.append(rec)
    payload = {
        "source": "r_vda_prg_updates",
        "wp_api": WP_API,
        "comuni_con_aggiornamenti": len(events),
        "comuni_con_stato_ufficiale": len(status),
        "records": records,
    }
    out = output_dir / "r_vda_prg_updates.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    return {"status": "completed", "output": str(out),
            "wp_updates": len(events), "official_status": len(status), "records": len(records)}


if __name__ == "__main__":
    r = fetch()
    print(json.dumps(r, ensure_ascii=False, indent=2))
