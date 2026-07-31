"""Stadio 03 · RICONOSCIMENTO.

Input : un catalogo di dataset (schema Torino: uuid,title,topic,url,...).
Output: work/recognition/<ente>.json  (layer → classe canonica, con motivo e tracciabilità)
        work/proposals/<ente>.json     (layer non riconosciuti + classi candidate da rivedere)

Non modifica i dati grezzi: classifica soltanto. Estendere il dizionario in base alle
proposte è un'azione umana (governance come per gli alias comuni).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.recognize import Recognizer  # noqa: E402

WORK = ROOT / "work"
# livello dedotto dal prefisso uuid (come in Torino: r_=regione, p_=provincia, c_=comune)
LEVEL_PREFIX = {"r_": "regione", "p_": "provincia", "c_": "comune"}


def _level(uuid: str) -> str:
    return next((v for k, v in LEVEL_PREFIX.items() if str(uuid).startswith(k)), "sconosciuto")


def run(
    catalog: Path,
    ente: str,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    catalog = Path(catalog)
    rec = Recognizer()
    matched, proposals = [], []
    by_class: Counter = Counter()

    with catalog.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
        total_rows = len(rows)
        if progress:
            progress(0, total_rows)
        for index, row in enumerate(rows, 1):
            title = (row.get("title") or "").strip()
            topic = (row.get("topic") or "").strip()
            uuid = (row.get("uuid") or "").strip()
            if not title:
                if progress and (index % 25 == 0 or index == total_rows):
                    progress(index, total_rows)
                continue
            m = rec.match(title, topic)
            base = {
                "uuid": uuid, "title": title, "topic": topic,
                "url": row.get("url", ""), "ente": ente, "livello": _level(uuid),
            }
            if m.recognized:
                by_class[m.canonical] += 1
                matched.append({**base, "canonical_key": m.canonical,
                                "confidence": m.confidence, "score": round(m.score, 1),
                                "matched": m.matched, "reason": m.reason})
            else:
                proposals.append({**base, "candidates": m.proposals})
            if progress and (index % 25 == 0 or index == total_rows):
                progress(index, total_rows)

    (WORK / "recognition").mkdir(parents=True, exist_ok=True)
    (WORK / "proposals").mkdir(parents=True, exist_ok=True)
    (WORK / "recognition" / f"{ente}.json").write_text(
        json.dumps({"ente": ente, "catalog": str(catalog), "count": len(matched),
                    "by_class": dict(by_class.most_common()), "items": matched},
                   ensure_ascii=False, indent=2), "utf-8")
    (WORK / "proposals" / f"{ente}.json").write_text(
        json.dumps({"ente": ente, "count": len(proposals), "items": proposals},
                   ensure_ascii=False, indent=2), "utf-8")

    total = len(matched) + len(proposals)
    summary = {"ente": ente, "total": total, "recognized": len(matched),
               "unrecognized": len(proposals),
               "coverage_pct": round(100 * len(matched) / total, 1) if total else 0.0,
               "by_class": dict(by_class.most_common())}
    return summary


def _print_summary(s: dict) -> None:
    print(f"\n== Riconoscimento · {s['ente']} ==")
    print(f"  dataset totali   : {s['total']}")
    print(f"  riconosciuti     : {s['recognized']}  ({s['coverage_pct']}%)")
    print(f"  da rivedere      : {s['unrecognized']}  → work/proposals/{s['ente']}.json")
    print("  classi canoniche popolate:")
    for k, v in s["by_class"].items():
        print(f"    {v:>4}  {k}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Riconoscimento layer → classe canonica")
    ap.add_argument("--catalog", required=True, help="CSV con colonne uuid,title,topic,url,...")
    ap.add_argument("--ente", required=True, help="chiave ente (es. r_piemon)")
    args = ap.parse_args()
    _print_summary(run(Path(args.catalog), args.ente))
