#!/usr/bin/env python3
"""Orchestratore del Layer_Processor.

Non è un monolite: instrada verso gli stadi (stages/stage_0N_*.py), tutti idempotenti.
Uso:
    python3 run.py discover --source r_piemon
    python3 run.py download --source r_piemon
    python3 run.py sync --region 02
    python3 run.py recognize --catalog work/catalog/r_piemon.csv --ente r_piemon
    python3 run.py context --region 02
    python3 run.py status

Ogni stadio rigira solo se i suoi input sono cambiati (vedi lib/state.py). Il vecchio
archivio Torino è soltanto un golden test: Scoperta e Download possono ricrearlo da zero.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import planning_context, state  # noqa: E402
from lib.config import get_paths as _get_paths  # noqa: E402
from stages import stage_01_discover as s01  # noqa: E402


def _sources_registry() -> dict:
    return yaml.safe_load((ROOT / "registry" / "sources.yaml").read_text("utf-8"))


def _source(key: str) -> dict:
    for item in _sources_registry().get("sources", []):
        if item.get("key") == key:
            return item
    raise KeyError(f"Fonte non trovata: {key}")


def _progress(enabled: bool):
    if not enabled:
        return None
    return lambda current, total: print(  # noqa: E731
        f"PROGRESS {current} {total}", flush=True
    )


def _result(payload: dict) -> None:
    """Emette un riepilogo leggibile e una riga stabile per la dashboard."""
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"RESULT_JSON {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}", flush=True)


def _call_event(enabled: bool):
    if not enabled:
        return None
    return lambda payload: print(  # noqa: E731
        f"CALL_JSON {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}",
        flush=True,
    )


def cmd_discover(args) -> int:
    try:
        source = _source(args.source)
        status_source = _source("r_vda_prg_status") if source.get("adapter") == "vda_sct" else None
        summary = s01.run(
            source,
            work_dir=_get_paths()["work"],
            status_source=status_source,
            progress=_progress(args.progress),
        )
    except (KeyError, NotImplementedError, RuntimeError, OSError, ValueError) as exc:
        _result({"status": "failed", "message": f"Scoperta fallita: {exc}", "error": str(exc)})
        return 2
    summary.setdefault("status", "completed")
    summary.setdefault(
        "message",
        f"Scoperta completata: {summary.get('services', 0)} servizi, "
        f"{summary.get('layers', 0)} layer.",
    )
    _result(summary)
    has_errors = bool(
        summary.get("missing_services")
        or summary.get("failures")
        or summary.get("missing_maps")
        or summary.get("status") == "partial"
    )
    return 1 if has_errors else 0


def cmd_download(args) -> int:
    from stages import stage_02_download as s02

    try:
        source = _source(args.source)
        paths = _get_paths()
        manifest = paths["work"] / "catalog" / f"{args.source}_services.json"
        if not manifest.exists():
            print(f"Manifest non trovato: {manifest}. Eseguo prima discover.", flush=True)
            status_source = _source("r_vda_prg_status") if source.get("adapter") == "vda_sct" else None
            s01.run(
                source,
                work_dir=paths["work"],
                status_source=status_source,
                progress=_progress(args.progress),
            )
        summary = s02.run(
            source,
            manifest_path=manifest,
            raw_dir=paths["raw"],
            service_filter=args.service,
            max_services=args.max_services,
            dry_run=args.dry_run,
            refresh=getattr(args, "refresh", False),
            progress=_progress(args.progress),
            call_event=_call_event(args.progress),
        )
    except (KeyError, NotImplementedError, RuntimeError, OSError, ValueError) as exc:
        _result({"status": "failed", "message": f"Download fallito: {exc}", "error": str(exc)})
        return 2
    summary.setdefault("message", f"Download terminato con stato {summary.get('status', 'sconosciuto')}.")
    _result(summary)
    if summary.get("status") == "authentication_required":
        return 3
    return 1 if summary.get("status") in {"partial", "failed"} else 0


def cmd_sync(args) -> int:
    region = args.region.strip().zfill(2)
    sources = {
        "01": ["r_piemon"],
        "02": ["r_vda"],
        "03": ["r_lombar", "r_lombar_pgtweb", "r_lombar_ptm"],
        "04": ["r_tn_pup", "r_tn_pericolosita", "r_tn_servizi_valli",
               "r_bz_piani", "r_bz_piani_gvcc", "r_bz_pericoli",
               "r_bz_geologia", "r_bz_idrologia"],
        "05": ["r_veneto"],
        "06": ["r_fvg_ppr", "r_fvg_siti_prot", "r_fvg_zone_vinc"],
        "07": ["r_liguria"],
        "08": ["r_emilia_romagna_pug", "r_emilia_romagna_psc",
               "p_bo_ptcp_tutele", "p_fe_ptcp_tutele", "p_fc_ptcp_tutele",
               "p_mo_ptcp_tutele", "p_pr_ptcp_tutele", "p_pc_ptcp_tutele",
               "p_ra_ptcp_tutele", "p_re_ptcp_tutele"],
        "12": ["r_lazio"],
        "17": ["r_basilicata"],
        "20": ["r_sardegna"],
    }
    if region not in sources:
        print(
            f"sync regionale non ancora implementato per la regione {region}.",
            file=sys.stderr,
        )
        return 2
    result = 0
    for source_key in sources[region]:
        discover_args = argparse.Namespace(source=source_key, progress=args.progress)
        source_result = cmd_discover(discover_args)
        if source_result not in (0, 1):
            return source_result
        result = max(result, source_result)
    for source_key in sources[region]:
        download_args = argparse.Namespace(
            source=source_key,
            service=args.service,
            max_services=args.max_services,
            dry_run=args.dry_run,
            progress=args.progress,
            refresh=False,
        )
        source_result = cmd_download(download_args)
        if source_result not in (0, 1):
            return source_result
        result = max(result, source_result)
    return result


def cmd_recognize(args) -> int:
    from stages import stage_03_recognize as s03

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
    progress = _progress(args.progress)
    summary = s03.run(catalog, args.ente, progress=progress)
    s03._print_summary(summary)
    state.mark_done(key, deps, meta=summary)
    return 0


def cmd_compose(args) -> int:
    from stages import stage_04_compose as s04

    targets = [t.strip() for t in (args.targets or "").split(",") if t.strip()]
    scope = {"level": args.scope_level, "key": args.scope_key, "name": args.scope_name}
    try:
        summary = s04.run(
            targets=targets,
            scope=scope,
            progress=_progress(args.progress),
            call_event=_call_event(args.progress),
        )
    except (NotImplementedError, RuntimeError, OSError, ValueError) as exc:
        _result({"status": "failed", "message": f"Composizione fallita: {exc}", "error": str(exc)})
        return 2
    summary.setdefault("message", f"Composizione: {summary.get('status', 'sconosciuto')}.")
    _result(summary)
    # Una composizione parziale è una run conclusa con un avvertimento leggibile
    # (es. inventario vincoli ancora incompleto), non un crash del processo.
    return 1 if summary.get("status") == "failed" else 0


def cmd_omi(args) -> int:
    from lib import omi
    paths = _get_paths()
    if args.action == "discover":
        _result(omi.discover(paths["work"], progress=_progress(args.progress)))
        return 0
    scope: dict = {"mode": args.scope}
    if args.scope == "province":
        scope["province"] = [p.strip().upper() for p in (args.province or "").split(",") if p.strip()]
    sems = [s.strip() for s in (args.semesters or "").split(",") if s.strip()] or None
    fields = [f.strip() for f in (args.fields or "").split(",") if f.strip()] or None
    try:
        summary = omi.download(
            paths["raw"], scope=scope, semesters=sems, last_years=args.last_years,
            fields=fields, refresh=args.refresh, max_comuni=args.max_comuni,
            dry_run=args.dry_run, progress=_progress(args.progress),
            call_event=_call_event(args.progress),
        )
    except (RuntimeError, OSError, ValueError) as exc:
        _result({"status": "failed", "message": f"OMI fallito: {exc}", "error": str(exc)})
        return 2
    summary.setdefault("message", f"OMI: {summary.get('status')}.")
    _result(summary)
    return 1 if summary.get("status") in {"partial", "failed"} else 0


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


def cmd_context(args) -> int:
    try:
        summary = planning_context.summarize(args.region)
    except (KeyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print(f"Contesto: {summary['name']} (ISTAT {summary['region_istat']})")
    print(f"Livelli: {' → '.join(summary['processing_order'])}")
    for level, details in summary["skipped_levels"].items():
        print(f"Escluso: {level} — {details['reason'].strip()}")
    print(f"Comuni attesi: {summary['expected_municipalities']}")
    print("Strumenti attesi:")
    for item in summary["instruments"]:
        relation = (
            f", conforme a {item['must_conform_to']}"
            if item.get("must_conform_to")
            else ""
        )
        print(
            f"  {item['key']} · {item['level']} · "
            f"copertura attesa {item['expected_count']}{relation}"
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Orchestratore Layer_Processor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    discover = sub.add_parser("discover", help="Stadio 01: legge il catalogo di una fonte")
    discover.add_argument("--source", required=True, help="Chiave della fonte in sources.yaml")
    discover.add_argument("--progress", action="store_true")
    discover.set_defaults(func=cmd_discover)

    download = sub.add_parser("download", help="Stadio 02: scarica i dati scoperti")
    download.add_argument("--source", required=True, help="Chiave della fonte in sources.yaml")
    download.add_argument("--service", help="Limita il download a servizio/nome indicato")
    download.add_argument("--max-services", type=int,
                          help="Quanti layer per esecuzione (omesso = tutti i pendenti)")
    download.add_argument("--refresh", action="store_true",
                          help="Riscarica anche i layer già presenti (default: solo i nuovi)")
    download.add_argument("--dry-run", action="store_true")
    download.add_argument("--progress", action="store_true")
    download.set_defaults(func=cmd_download)

    sync = sub.add_parser("sync", help="Discover + download per una regione")
    sync.add_argument("--region", required=True, help="Codice ISTAT regione")
    sync.add_argument("--service", help="Limita il download a un servizio")
    sync.add_argument("--max-services", type=int)
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--progress", action="store_true")
    sync.set_defaults(func=cmd_sync)

    r = sub.add_parser("recognize", help="Stadio 03: riconosce i layer di un catalogo")
    r.add_argument("--catalog", required=True)
    r.add_argument("--ente", required=True)
    r.add_argument("--force", action="store_true")
    r.add_argument(
        "--progress",
        action="store_true",
        help="Emette avanzamento machine-readable per la dashboard locale",
    )
    r.set_defaults(func=cmd_recognize)

    st = sub.add_parser("status", help="Mostra lo stato della catena")
    st.set_defaults(func=cmd_status)

    omi_p = sub.add_parser("omi", help="Scarica/aggiorna il DB OMI (perimetri + valori)")
    omi_p.add_argument("--action", choices=["discover", "download"], default="download")
    omi_p.add_argument("--scope", default="all", help="all | province | comuni")
    omi_p.add_argument("--province", help="sigle province separate da virgola (scope=province)")
    omi_p.add_argument("--last-years", type=int, dest="last_years", help="ultimi N anni (2N semestri)")
    omi_p.add_argument("--semesters", help="semestri espliciti, es. 20252,20251")
    omi_p.add_argument("--fields", help="campi valore da tenere (default: tutti)")
    omi_p.add_argument("--max-comuni", type=int, dest="max_comuni", help="limite per esecuzione")
    omi_p.add_argument("--refresh", action="store_true")
    omi_p.add_argument("--dry-run", action="store_true")
    omi_p.add_argument("--progress", action="store_true")
    omi_p.set_defaults(func=cmd_omi)

    comp = sub.add_parser("compose", help="Stadio 04: componi i target selezionati")
    comp.add_argument("--targets", help="Chiavi target separate da virgola")
    comp.add_argument("--scope-level", dest="scope_level", default="")
    comp.add_argument("--scope-key", dest="scope_key", default="")
    comp.add_argument("--scope-name", dest="scope_name", default="")
    comp.add_argument("--progress", action="store_true")
    comp.set_defaults(func=cmd_compose)

    ctx = sub.add_parser(
        "context",
        help="Mostra ciò che la pipeline si aspetta da una regione",
    )
    ctx.add_argument("--region", required=True, help="Codice ISTAT o nome regione")
    ctx.add_argument("--json", action="store_true", help="Output JSON per dashboard/API")
    ctx.set_defaults(func=cmd_context)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
