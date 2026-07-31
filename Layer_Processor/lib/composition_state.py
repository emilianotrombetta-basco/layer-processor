"""Stato dei prodotti di composizione (stadio 04) per territorio.

Per ogni target in registry/composition_targets.yaml determina se, per un dato
territorio, il layer finale è:

- ``assente``        : mai composto (nessun output in out/<TARGET>/<terr>.geojson);
- ``presente``       : composto e ancora valido (i fingerprint delle sorgenti usate
                       coincidono con i file attuali);
- ``da_aggiornare``  : composto MA una delle sorgenti con cui era stato calcolato è
                       cambiata/è stata riscaricata (fingerprint diverso) → va rifatto.

Il compose, quando produrrà i layer, scriverà accanto al GeoJSON un manifest
``out/<TARGET>/<terr>.manifest.json`` con ``sources: [{path, fingerprint}]``.
Questo modulo confronta quei fingerprint con i file attuali (via lib/state).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from . import state

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
TARGETS_FILE = ROOT / "registry" / "composition_targets.yaml"


def _load_targets() -> dict[str, Any]:
    if not TARGETS_FILE.exists():
        return {}
    data = yaml.safe_load(TARGETS_FILE.read_text("utf-8")) or {}
    return data.get("targets", {}) if isinstance(data, dict) else {}


def _territory_id(scope: dict[str, Any]) -> str:
    return str(scope.get("key") or "regione")


def target_state(key: str, scope: dict[str, Any]) -> dict[str, Any]:
    terr = _territory_id(scope)
    geojson = OUT / key / f"{terr}.geojson"
    manifest = OUT / key / f"{terr}.manifest.json"
    if not geojson.exists() and not manifest.exists():
        return {"state": "assente"}
    data: dict[str, Any] = {}
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text("utf-8"))
        except Exception:
            data = {}
    sources = data.get("sources", []) or []
    stale = [
        s.get("path")
        for s in sources
        if state.file_fingerprint(Path(s.get("path", ""))) != s.get("fingerprint")
    ]
    output_status = str(data.get("status") or "")
    output_partial = output_status in {"partial", "blocked", "failed"}
    return {
        "state": (
            "da_aggiornare"
            if stale
            else "parziale" if output_partial else "presente"
        ),
        "output_status": output_status or None,
        "coverage": data.get("coverage"),
        "features": data.get("features"),
        "composed_at": data.get("composed_at"),
        "sources_total": len(sources),
        "stale_sources": stale[:8],
    }


def targets_for_scope(scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Elenco dei target con stato per il territorio dello scope."""
    result: list[dict[str, Any]] = []
    for key, value in _load_targets().items():
        info = target_state(key, scope)
        result.append({
            "key": key,
            "title": value.get("title", key),
            "geometry": value.get("geometry"),
            "scale": value.get("scale"),
            **info,
        })
    return result
