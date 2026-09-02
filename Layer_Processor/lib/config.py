"""Configurazione path del Layer Processor.

Legge ``config.yaml`` dalla root del progetto e risolve ogni percorso
in modo assoluto.  Usare :func:`get_paths` per ottenere il dict dei
path risolti, oppure le singole funzioni helper.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config.yaml"

_DEFAULTS: dict[str, str] = {
    "raw": "raw",
    "work": "work",
    "out": "out",
    "state": "state",
    "admin": "../Geography_Locations/outputs",
}


def _resolve(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (ROOT / p).resolve()


def load_raw() -> dict[str, Any]:
    if CONFIG_FILE.exists():
        return yaml.safe_load(CONFIG_FILE.read_text("utf-8")) or {}
    return {}


def get_paths() -> dict[str, Path]:
    cfg = load_raw()
    raw_paths = cfg.get("paths") or {}
    return {key: _resolve(str(raw_paths.get(key, default))) for key, default in _DEFAULTS.items()}


def save_paths(paths: dict[str, str]) -> None:
    cfg = load_raw()
    cfg.setdefault("paths", {})
    for key, value in paths.items():
        if key in _DEFAULTS:
            cfg["paths"][key] = value
    CONFIG_FILE.write_text(
        yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        "utf-8",
    )


def raw_dir() -> Path:
    return get_paths()["raw"]


def work_dir() -> Path:
    return get_paths()["work"]


def out_dir() -> Path:
    return get_paths()["out"]


def state_dir() -> Path:
    return get_paths()["state"]


def admin_dir() -> Path:
    return get_paths()["admin"]
