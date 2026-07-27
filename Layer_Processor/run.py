#!/usr/bin/env python3
"""Orchestratore del Layer_Processor.

Non è un monolite: instrada verso gli stadi (stages/stage_0N_*.py), tutti idempotenti.
Uso:
    python3 run.py recognize --catalog ../Nord/piemonte/_catalog.csv --ente r_piemon
    python3 run.py status

Ogni stadio rigira solo se i suoi input sono cambiati (vedi lib/state.py). Il pilota
corrente parte dallo stadio 03 (i dati Torino sono già scaricati in ../Nord/piemonte/).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import state  # noqa: E402
from stages import stage_03_recognize as s03  # noqa: E402


def cmd_recognize(args) -> int:
    catalog = Path(args.catalog).resolve()
    if not catalog.exists():
        print(f"catalogo non trovato: {catalog}", file=sys.stderr)
        return 2
    key = f"recognize_{args.ente}"
    deps = [catalog, ROOT / "registry" / "layer_dictionary.yaml",
            ROOT / "registry" / "canonical_taxonomy.yaml"]
    if not args.force and state.is_up_to_date(key, deps):
        print(f"[skip] {key}: già aggiornato (usa --force per rifare)")
        return 0
    summary = s03.run(catalog, args.ente)
    s03._print_summary(summary)
    state.mark_done(key, deps, meta=summary)
    return 0


def cmd_status(_args) -> int:
    state_dir = ROOT / "state"
    files = sorted(state_dir.glob("*.json")) if state_dir.exists() else []
    if not files:
        print("Nessuno stadio ancora eseguito.")
        return 0
    print("Stato degli stadi:")
    for f in files:
        data = json.loads(f.read_text("utf-8"))
        meta = data.get("meta", {})
        extra = ""
        if "coverage_pct" in meta:
            extra = f"  · {meta['recognized']}/{meta['total']} riconosciuti ({meta['coverage_pct']}%)"
        print(f"  {f.stem}{extra}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Orchestratore Layer_Processor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("recognize", help="Stadio 03: riconosce i layer di un catalogo")
    r.add_argument("--catalog", required=True)
    r.add_argument("--ente", required=True)
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_recognize)

    st = sub.add_parser("status", help="Mostra lo stato della catena")
    st.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
