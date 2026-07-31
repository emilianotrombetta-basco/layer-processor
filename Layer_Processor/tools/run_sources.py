#!/usr/bin/env python3
"""Esegue lo stesso stadio su più fonti e inoltra gli eventi alla dashboard."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["discover", "download"])
    parser.add_argument("--sources", required=True)
    parser.add_argument("--max-services", type=int)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    sources = [item.strip() for item in args.sources.split(",") if item.strip()]
    results: list[dict[str, Any]] = []
    exit_codes: list[int] = []
    for source in sources:
        command = [
            sys.executable,
            "-u",
            "run.py",
            args.stage,
            "--source",
            source,
            "--progress",
        ]
        if args.stage == "download" and args.max_services:
            command.extend(["--max-services", str(args.max_services)])
        if args.stage == "download" and args.refresh:
            command.append("--refresh")
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        result: dict[str, Any] = {}
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            if line.startswith("RESULT_JSON "):
                try:
                    result = json.loads(line.removeprefix("RESULT_JSON "))
                except json.JSONDecodeError:
                    pass
        exit_codes.append(process.wait())
        results.append({"source": source, **result})

    failed = sum(code not in {0, 1} for code in exit_codes)
    partial = sum(
        code == 1 or result.get("status") in {"partial", "batch_completed"}
        for code, result in zip(exit_codes, results)
    )
    status = "failed" if failed == len(sources) else "partial" if failed or partial else "completed"
    combined = {
        "status": status,
        "message": (
            f"{args.stage.title()} multi-fonte terminato: "
            f"{len(sources) - failed}/{len(sources)} fonti elaborate."
        ),
        "sources": results,
        "services": sum(int(item.get("services", 0) or 0) for item in results),
        "layers": sum(int(item.get("layers", 0) or 0) for item in results),
        "downloadable_layers": sum(
            int(item.get("downloadable_layers", 0) or 0) for item in results
        ),
        "layers_downloaded": sum(
            int(item.get("layers_downloaded", 0) or 0) for item in results
        ),
        "layers_failed": sum(
            int(item.get("layers_failed", 0) or 0) for item in results
        ),
    }
    print(
        f"RESULT_JSON {json.dumps(combined, ensure_ascii=False, separators=(',', ':'))}",
        flush=True,
    )
    # Un batch incompleto per scelta dell'utente è una run conclusa e
    # riprendibile, non un errore del processo dashboard.
    return 2 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
