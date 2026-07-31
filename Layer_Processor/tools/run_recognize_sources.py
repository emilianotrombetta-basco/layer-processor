#!/usr/bin/env python3
"""Riconosce in sequenza tutti i cataloghi di una pipeline territoriale."""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _rows(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    sources = [item.strip() for item in args.sources.split(",") if item.strip()]
    catalogs = [ROOT / "work" / "catalog" / f"{key}.csv" for key in sources]
    missing = [str(path) for path in catalogs if not path.exists()]
    if missing:
        print("Cataloghi mancanti: " + ", ".join(missing), file=sys.stderr)
        return 2
    totals = [_rows(path) for path in catalogs]
    grand_total = sum(totals)
    offset = 0
    exit_codes: list[int] = []
    for source, catalog, source_total in zip(sources, catalogs, totals):
        command = [
            sys.executable,
            "-u",
            "run.py",
            "recognize",
            "--catalog",
            str(catalog),
            "--ente",
            source,
            "--progress",
        ]
        if args.force:
            command.append("--force")
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            if line.startswith("PROGRESS "):
                _, current, _total = line.split()
                print(f"PROGRESS {offset + int(current)} {grand_total}", flush=True)
            else:
                print(line, end="", flush=True)
        exit_codes.append(process.wait())
        offset += source_total
        print(f"PROGRESS {offset} {grand_total}", flush=True)
    return 0 if all(code == 0 for code in exit_codes) else 2


if __name__ == "__main__":
    raise SystemExit(main())
