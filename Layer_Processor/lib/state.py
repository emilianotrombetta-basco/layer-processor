"""Stato per l'idempotenza: uno stadio rigira solo se cambiano i suoi input.

Semplice fingerprint su file/valori salvato in state/<key>.json. Ogni stadio dichiara
le sue dipendenze (file di input + il registry rilevante); se il fingerprint combatte
con quello salvato, lo stadio è 'up-to-date' e si può saltare.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"


def file_fingerprint(path: Path) -> str:
    p = Path(path)
    if not p.exists():
        return "missing"
    h = hashlib.sha256()
    h.update(str(p.stat().st_size).encode())
    h.update(str(int(p.stat().st_mtime)).encode())
    return h.hexdigest()[:16]


def fingerprint(inputs: list[Path | str]) -> str:
    h = hashlib.sha256()
    for item in inputs:
        p = Path(item)
        h.update(str(p).encode())
        h.update(file_fingerprint(p).encode())
    return h.hexdigest()[:16]


def is_up_to_date(key: str, inputs: list[Path | str]) -> bool:
    f = STATE_DIR / f"{key}.json"
    if not f.exists():
        return False
    try:
        saved = json.loads(f.read_text("utf-8")).get("fingerprint")
    except Exception:
        return False
    return saved == fingerprint(inputs)


def mark_done(key: str, inputs: list[Path | str], meta: dict | None = None) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    payload = {"fingerprint": fingerprint(inputs), "inputs": [str(Path(i)) for i in inputs]}
    if meta:
        payload["meta"] = meta
    (STATE_DIR / f"{key}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
