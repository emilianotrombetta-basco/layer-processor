#!/usr/bin/env python3
"""Genera l'overlay dei comuni lombardi correnti per dashboard e composizione.

Non modifica il registro nazionale storico: sostituisce la sola Lombardia in
lettura tramite un file separato, ricostruibile dal servizio ufficiale già
acquisito dallo stadio Download.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
SOURCE = (
    ROOT
    / "raw"
    / "regione"
    / "r_lombar"
    / "limiti_amministrativi"
    / "L3_comuni_correnti_della_lombardia.geojson"
)
BASE = WORKSPACE / "Geography_Locations" / "outputs" / "admin_municipalities.geojson"
OUTPUT = (
    WORKSPACE
    / "Geography_Locations"
    / "outputs"
    / "admin_municipalities_lombardia_current.geojson"
)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _title_name(value: Any) -> str:
    words = str(value or "").replace("`", "'").strip().title().split()
    lower = {"Con", "E", "Di", "Del", "Della", "Dei", "Degli", "Delle", "In", "Sul", "Sulla"}
    return " ".join(word.casefold() if index and word in lower else word for index, word in enumerate(words))


def _istat(properties: dict[str, Any]) -> str:
    raw = properties.get("ISTAT")
    if raw is None:
        raw = properties.get("COD_ISTAT")
    digits = "".join(char for char in str(raw or "") if char.isdigit())
    return digits.zfill(6)


def build() -> dict[str, Any]:
    if not SOURCE.exists():
        raise RuntimeError(
            "Confini Lombardia mancanti. Eseguire: "
            "python3 run.py download --source r_lombar --service limiti_amministrativi"
        )
    source = json.loads(SOURCE.read_text("utf-8"))
    base = json.loads(BASE.read_text("utf-8"))
    previous_names = {
        str(feature["properties"]["key"]): str(feature["properties"]["name"])
        for feature in base.get("features", [])
        if str(feature.get("properties", {}).get("reg_key")) == "03"
    }
    features: list[dict[str, Any]] = []
    codes: set[str] = set()
    invalid: list[str] = []
    for feature in source.get("features", []):
        properties = feature.get("properties") or {}
        code = _istat(properties)
        if len(code) != 6 or not code.isdigit() or code in codes:
            raise RuntimeError(f"Codice ISTAT Lombardia non valido o duplicato: {code}")
        geometry = feature.get("geometry")
        geom = shape(geometry) if geometry else None
        if geom is None or geom.is_empty or not geom.is_valid:
            invalid.append(code)
            continue
        codes.add(code)
        centroid = geom.centroid
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "key": code,
                    "prov_key": code[:3],
                    "reg_key": "03",
                    "name": previous_names.get(code) or _title_name(properties.get("NOME_COM")),
                    "centroid": [round(centroid.x, 6), round(centroid.y, 6)],
                },
                "geometry": geometry,
            }
        )
    features.sort(key=lambda item: str(item["properties"]["key"]))
    if len(features) != 1501:
        raise RuntimeError(
            f"Attesi 1.501 comuni correnti, ottenuti {len(features)}; "
            f"geometrie non valide: {invalid[:10]}"
        )
    collection = {
        "type": "FeatureCollection",
        "name": "Comuni correnti della Lombardia",
        "source": (
            "https://www.cartografia.servizirl.it/arcgis1/rest/services/"
            "territorio/limiti_amministrativi_dbt_cr_pub/MapServer/3"
        ),
        "features": features,
    }
    _atomic_json(OUTPUT, collection)
    return {
        "status": "completed",
        "output": str(OUTPUT),
        "municipalities": len(features),
        "invalid": invalid,
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
