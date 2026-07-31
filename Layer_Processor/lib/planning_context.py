"""Caricamento e validazione dei profili regionali di pianificazione."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROFILE_FILE = ROOT / "registry" / "regional_planning_profiles.yaml"
TAXONOMY_FILE = ROOT / "registry" / "canonical_taxonomy.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Registry non valido: {path}")
    return data


def load_registry() -> dict[str, Any]:
    """Carica e valida il registry dei contesti regionali."""
    registry = _load_yaml(PROFILE_FILE)
    profiles = registry.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("'profiles' deve essere una mappa")

    canonical = set(_load_yaml(TAXONOMY_FILE).get("classes", {}))
    allowed_levels = {"regione", "provincia", "comune"}

    for code, profile in profiles.items():
        territory = profile.get("territorial_model", {})
        levels = territory.get("planning_levels", [])
        order = territory.get("processing_order", [])
        if not levels or set(levels) - allowed_levels:
            raise ValueError(f"Profilo {code}: planning_levels non valido")
        if set(order) != set(levels):
            raise ValueError(f"Profilo {code}: processing_order e planning_levels divergono")
        skipped = set(territory.get("skipped_levels", {}))
        if skipped & set(levels):
            raise ValueError(f"Profilo {code}: un livello è sia attivo sia escluso")

        for instrument in profile.get("instruments", []):
            if instrument.get("level") not in levels:
                raise ValueError(
                    f"Profilo {code}: {instrument.get('key')} usa un livello non attivo"
                )
        for groups in profile.get("expected_datasets", {}).values():
            for group in groups:
                unknown = set(group.get("canonical_classes", [])) - canonical
                if unknown:
                    raise ValueError(
                        f"Profilo {code}: classi canoniche sconosciute {sorted(unknown)}"
                    )
    return registry


def get_profile(region: str) -> tuple[str, dict[str, Any]]:
    """Trova un profilo tramite codice ISTAT o nome italiano/francese."""
    registry = load_registry()
    profiles = registry["profiles"]
    query = region.strip().casefold()
    code = region.strip().zfill(2) if region.strip().isdigit() else None
    if code in profiles:
        return code, profiles[code]

    for candidate_code, profile in profiles.items():
        names = profile.get("names", {})
        if query in {str(value).casefold() for value in names.values()}:
            return candidate_code, profile
    raise KeyError(f"Nessun profilo regionale per: {region}")


def summarize(region: str) -> dict[str, Any]:
    """Restituisce le aspettative operative essenziali per UI e pipeline."""
    code, profile = get_profile(region)
    territory = profile["territorial_model"]
    return {
        "region_istat": code,
        "key": profile["key"],
        "name": profile["names"]["it"],
        "special_statute": profile.get("special_statute", False),
        "languages": profile.get("languages", ["it"]),
        "planning_levels": territory["planning_levels"],
        "processing_order": territory["processing_order"],
        "skipped_levels": territory.get("skipped_levels", {}),
        "expected_municipalities": territory.get("expected_municipalities"),
        "instruments": [
            {
                "key": item["key"],
                "level": item["level"],
                "required": item.get("required", False),
                "expected_count": item.get("expected_count"),
                "must_conform_to": item.get("must_conform_to"),
            }
            for item in profile.get("instruments", [])
        ],
        "not_expected": profile.get("not_expected", []),
        "official_portals": profile.get("official_portals", []),
    }
