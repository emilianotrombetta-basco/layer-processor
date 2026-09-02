"""Motore geometrico dei prodotti finali dello stadio 04.

Il motore lavora soltanto con dati locali già acquisiti. Non colma assenze con
inferenze: se manca un input obbligatorio il target viene dichiarato bloccato,
oppure (per il Semaforo) classificato UNASSESSED.
"""
from __future__ import annotations

import functools
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml
import shapefile
from shapely import STRtree
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from . import state

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent

from .config import get_paths as _cfg_paths  # noqa: E402

def _init_paths():
    p = _cfg_paths()
    return p["admin"], p["raw"], p["work"], p["out"]

ADMIN_DIR, RAW, WORK, OUT = _init_paths()
CURRENT_MUNICIPALITY_OVERLAYS = {
    "03": ADMIN_DIR / "admin_municipalities_lombardia_current.geojson",
    "05": ADMIN_DIR / "admin_municipalities_veneto_current.geojson",
}
LOMBARDIA_CURRENT_MUNICIPALITIES = CURRENT_MUNICIPALITY_OVERLAYS["03"]
TARGETS_FILE = ROOT / "registry" / "composition_targets.yaml"

STATUS_SOURCE_VDA = (
    RAW / "regione" / "r_vda" / "prg_prescrittiva"
    / "060_stato_iter_di_adeguamento_al_ptp.geojson"
)
STATUS_SOURCE_LOMBARDIA = (
    RAW / "regione" / "r_lombar_pgtweb" / "ijqk-ahfp.json"
)
ZONE_SOURCE_VDA = (
    RAW / "regione" / "r_vda" / "prg_prescrittiva" / "061_p4_zone.geojson"
)

MAX_SOURCE_FILE_MB = 200

CONSTRAINT_CLASSES = {
    "DISSESTO_GEOLOGICO",
    "RISCHIO_IDRAULICO",
    "VINCOLO_IDROGEOLOGICO",
    "VINCOLI_PAESAGGISTICI",
    "AREE_PROTETTE",
    "RETE_ECOLOGICA",
    "ACQUE",
    "AGRICOLTURA",
    "ENERGIA",
    "FERROVIA",
    "VIABILITA",
    "SOSTA_ACCESSI",
    "PRG_ZONING",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return json.loads(path.read_text(enc))
        except (UnicodeDecodeError, ValueError):
            if enc == "latin-1":
                raise
            continue


def _bbox_intersects(
    bounds: tuple[float, float, float, float] | list[float],
    scope_bounds: tuple[float, float, float, float] | None,
) -> bool:
    if scope_bounds is None:
        return True
    return not (
        bounds[2] < scope_bounds[0]
        or bounds[0] > scope_bounds[2]
        or bounds[3] < scope_bounds[1]
        or bounds[1] > scope_bounds[3]
    )


def _reproject_geometry(geo: dict[str, Any], transformer: Any) -> dict[str, Any]:
    """Riproietta le coordinate di una geometria GeoJSON usando un Transformer pyproj."""
    def _xform(coords: Any) -> Any:
        if isinstance(coords[0], (int, float)):
            x, y = transformer.transform(coords[0], coords[1])
            return [x, y, *coords[2:]] if len(coords) > 2 else [x, y]
        return [_xform(c) for c in coords]
    return {**geo, "coordinates": _xform(geo.get("coordinates", []))}


def _shp_transformer(path: Path) -> Any | None:
    """Se lo SHP è in CRS proiettato, restituisce un Transformer verso WGS84."""
    prj = path.with_suffix(".prj")
    if not prj.exists():
        return None
    try:
        from pyproj import CRS, Transformer
        src = CRS.from_wkt(prj.read_text(encoding="utf-8"))
        if src.is_geographic:
            return None
        return Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
    except Exception:
        return None


def _iter_source_features(
    path: Path,
    scope_bounds: tuple[float, float, float, float] | None = None,
) -> Iterable[dict[str, Any]]:
    """Legge GeoJSON e Shapefile senza caricare per forza l'intera fonte.

    L'export HOTOSM nazionale scrive una feature GeoJSON per riga; il percorso
    streaming evita di materializzare in RAM oltre 400 MB. Gli altri GeoJSON
    mantengono il lettore ordinario già usato dalla pipeline.
    """
    suffix = path.suffix.lower()
    if suffix == ".shp":
        transformer = _shp_transformer(path)
        filter_bounds = scope_bounds
        if transformer and scope_bounds:
            from pyproj import CRS, Transformer
            inv = Transformer.from_crs(CRS.from_epsg(4326), transformer.source_crs, always_xy=True)
            x0, y0 = inv.transform(scope_bounds[0], scope_bounds[1])
            x1, y1 = inv.transform(scope_bounds[2], scope_bounds[3])
            filter_bounds = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        for enc in ("utf-8", "latin-1"):
            try:
                reader = shapefile.Reader(str(path), encoding=enc)
                field_names = [field[0] for field in reader.fields[1:]]
                records = list(reader.iterShapeRecords())
                break
            except Exception:
                if enc == "latin-1":
                    raise
                continue
        for item in records:
            try:
                sbbox = item.shape.bbox
            except AttributeError:
                pts = item.shape.points
                if not pts:
                    continue
                sbbox = (pts[0][0], pts[0][1], pts[0][0], pts[0][1])
            if not _bbox_intersects(sbbox, filter_bounds):
                continue
            geo = item.shape.__geo_interface__
            if transformer:
                geo = _reproject_geometry(geo, transformer)
            yield {
                "type": "Feature",
                "geometry": geo,
                "properties": {
                    k: v.isoformat() if isinstance(v, (datetime,)) or type(v).__name__ == "date" else v
                    for k, v in zip(field_names, item.record)
                },
            }
        return
    if suffix == ".geojson" and path.name.startswith("hotosm_"):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                value = line.strip().removesuffix(",")
                if not value.startswith('{ "type": "Feature"'):
                    continue
                feature = json.loads(value)
                geometry = feature.get("geometry") or {}
                if geometry.get("type") == "Point" and scope_bounds:
                    coordinates = geometry.get("coordinates") or []
                    if len(coordinates) >= 2 and not _bbox_intersects(
                        (coordinates[0], coordinates[1], coordinates[0], coordinates[1]),
                        scope_bounds,
                    ):
                        continue
                yield feature
        return
    yield from _read_json(path).get("features", [])


def _poi_class(properties: dict[str, Any]) -> tuple[str | None, str | None]:
    for family in ("amenity", "shop", "tourism", "man_made"):
        value = properties.get(family)
        if value not in (None, ""):
            return family, str(value)
    return None, None


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


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


_ENTE_LICENSE: dict[str, tuple[str, str]] = {
    "n_hotosm_poi": ("ODbL 1.0", "© OpenStreetMap contributors; export HOTOSM"),
    "n_arco_beni_culturali": ("CC BY-SA 4.0", "ICCD-MIC — ArCo Knowledge Graph"),
    "n_cultura_on": ("CC BY-SA 4.0", "MIC — Cultura ON"),
    "n_cruscotto_italia": ("IODL 2.0 / CC BY 4.0", "Cruscotto Italia — dati.gov.it"),
    "n_anncsu": ("CC BY 4.0 (High Value Dataset)", "ANNCSU — Agenzia Entrate + ISTAT"),
    "n_istat_censimento_sezioni": ("CC BY 3.0 IT", "ISTAT — Censimento permanente 2023"),
    "n_istat_basi_territoriali": ("CC BY 3.0 IT", "ISTAT — Basi territoriali 2021"),
    "n_istat_asia_ul": ("CC BY 3.0 IT", "ISTAT — ASIA Unità Locali"),
    "n_istat_posas": ("CC BY 3.0 IT", "ISTAT — Demografia POSAS"),
    "n_istat_turismo": ("CC BY 3.0 IT", "ISTAT — Turismo ricettività"),
    "n_istat_pendolarismo": ("CC BY 3.0 IT", "ISTAT — Matrice pendolarismo"),
    "n_anac_opendata": ("CC BY 4.0", "ANAC — BDNCP appalti pubblici OCDS"),
    "n_mef_irpef": ("Open data MEF", "MEF — IRPEF comunale"),
    "n_mef_immobili_pubblici": ("Open data MEF", "MEF — Immobili pubblici"),
    "n_ispra_suolo": ("IODL 2.0", "ISPRA — Consumo di suolo"),
    "n_ispra_rifiuti": ("IODL 2.0", "ISPRA — Catasto rifiuti"),
    "n_ispra_idrogeo": ("IODL 2.0", "ISPRA — IdroGEO"),
    "n_catasto_inspire": ("CC BY 4.0", "Agenzia Entrate — Catasto INSPIRE"),
    "n_agcom_connettivita": ("AGCOM open data", "AGCOM — Broadband Map"),
    "n_mimit_carburanti": ("Open data MIMIT", "MIMIT — Osservatorio Carburanti"),
    "n_salute_presidi": ("IODL 2.0", "Ministero della Salute"),
    "n_miur_scuole": ("Open data MIM", "MIM — Anagrafe scuole"),
    "n_siope": ("Open data MEF", "MEF/Banca d'Italia — SIOPE"),
    "n_colonnine_ricarica": ("Open data", "PUN — Infrastrutture ricarica"),
    "n_omi": ("Open data AdE", "Agenzia Entrate — OMI"),
    "n_aci_opendata": ("Open data ACI", "ACI — Parco circolante"),
    "n_runts": ("D.Lgs 117/2017", "Min. Lavoro — RUNTS"),
}
_REGIONAL_LICENSE = ("Open data regionale", "")


def _license_for_ente(ente: str) -> tuple[str, str]:
    if ente in _ENTE_LICENSE:
        return _ENTE_LICENSE[ente]
    if ente.startswith("r_"):
        return _REGIONAL_LICENSE
    return ("non dichiarata", "")


@functools.lru_cache(maxsize=1)
def _load_admin() -> tuple[tuple[dict[str, Any], ...], dict[str, str], dict[str, str]]:
    municipalities = _read_json(ADMIN_DIR / "admin_municipalities.geojson")["features"]
    for region_key, overlay_path in CURRENT_MUNICIPALITY_OVERLAYS.items():
        if not overlay_path.exists():
            continue
        municipalities = [
            feature
            for feature in municipalities
            if str(feature.get("properties", {}).get("reg_key")) != region_key
        ] + _read_json(overlay_path)["features"]
    provinces = {
        str(f["properties"]["key"]): str(f["properties"]["name"])
        for f in _read_json(ADMIN_DIR / "admin_provinces.geojson")["features"]
    }
    regions = {
        str(f["properties"]["key"]): str(f["properties"]["name"])
        for f in _read_json(ADMIN_DIR / "admin_regions.geojson")["features"]
    }
    return tuple(municipalities), provinces, regions


def _scope_municipalities(scope: dict[str, Any]) -> list[dict[str, Any]]:
    municipalities, provinces, regions = _load_admin()
    level = str(scope.get("level") or "region")
    key = str(scope.get("key") or "")
    selected: list[dict[str, Any]] = []
    for feature in municipalities:
        props = feature["properties"]
        if level == "region" and str(props.get("reg_key")) != key:
            continue
        if level == "province" and str(props.get("prov_key")) != key:
            continue
        if level == "municipality" and str(props.get("key")) != key:
            continue
        copied = {**feature, "properties": dict(props)}
        copied["properties"]["province"] = provinces.get(str(props.get("prov_key")), "")
        copied["properties"]["region"] = regions.get(str(props.get("reg_key")), "")
        selected.append(copied)
    if not selected:
        raise ValueError(f"Nessun comune trovato per scope {level}:{key}")
    return selected


def _source_record(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    return {"path": str(resolved), "fingerprint": state.file_fingerprint(resolved)}


def _write_target(
    target: str,
    scope: dict[str, Any],
    features: list[dict[str, Any]],
    sources: Iterable[Path],
    *,
    status: str,
    coverage: dict[str, Any],
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    territory = str(scope.get("key") or "regione")
    target_dir = OUT / target
    geojson_path = target_dir / f"{territory}.geojson"
    manifest_path = target_dir / f"{territory}.manifest.json"
    source_paths = sorted({Path(p).resolve() for p in sources if Path(p).exists()})
    composed_at = _now()
    collection = {
        "type": "FeatureCollection",
        "name": f"{target}_{territory}",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features,
    }
    manifest = {
        "target": target,
        "scope": scope,
        "status": status,
        "features": len(features),
        "composed_at": composed_at,
        "coverage": coverage,
        "sources": [_source_record(p) for p in source_paths],
        "diagnostics": diagnostics or {},
        "output": str(geojson_path.resolve()),
    }
    _atomic_json(geojson_path, collection)
    _atomic_json(manifest_path, manifest)
    return {
        "target": target,
        "status": status,
        "features": len(features),
        "path": str(geojson_path),
        "manifest": str(manifest_path),
        "coverage": coverage,
    }


def _status_config(region: str) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    config = yaml.safe_load(TARGETS_FILE.read_text("utf-8"))
    target = config["targets"]["PIANI_MATURITA"]
    mapping_key = {"02": "valle_d_aosta", "03": "lombardia"}[region]
    return target["regional_mappings"][mapping_key], target["statuses"]


def _compose_plan_maturity_lombardia(
    scope: dict[str, Any],
    municipalities: list[dict[str, Any]],
) -> dict[str, Any]:
    if not STATUS_SOURCE_LOMBARDIA.exists():
        return {
            "target": "PIANI_MATURITA",
            "status": "blocked",
            "message": (
                "Inventario PGTWEB mancante: eseguire Scoperta e Download "
                "della fonte r_lombar_pgtweb."
            ),
        }
    mapping_codes, status_defs = _status_config("03")
    records = _read_json(STATUS_SOURCE_LOMBARDIA).get("records", [])
    # La vista Socrata replica lo stesso piano per le diverse sezioni del
    # procedimento. Questa chiave conserva un solo record amministrativo.
    plans: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for record in records:
        code = str(record.get("cod_istat") or "").strip().zfill(6)
        if not code:
            continue
        key = (
            code,
            str(record.get("descr_piano") or ""),
            str(record.get("data_ins") or ""),
            str(record.get("tipo_piano") or ""),
        )
        plans[key] = record
    by_municipality: dict[str, list[dict[str, Any]]] = {}
    for key, record in plans.items():
        by_municipality.setdefault(key[0], []).append(record)

    processed_at = _now()
    source_date = datetime.fromtimestamp(
        STATUS_SOURCE_LOMBARDIA.stat().st_mtime, timezone.utc
    ).isoformat(timespec="seconds")
    output: list[dict[str, Any]] = []
    without_records: list[str] = []
    status_counts: dict[str, int] = {}
    for admin in municipalities:
        ap = admin["properties"]
        istat = str(ap["key"])
        municipality_plans = by_municipality.get(istat, [])
        current = [
            item for item in municipality_plans
            if str(item.get("stato_pgt") or "").casefold() == "vigente"
        ]
        current_plan = max(
            current,
            key=lambda item: (
                str(item.get("data_burl") or ""),
                str(item.get("data_ins") or ""),
            ),
            default=None,
        )
        active = [
            item for item in municipality_plans
            if str(item.get("stato_pgt") or "").casefold()
            not in {"vigente", "storico", "chiuso"}
        ]
        active_plan = max(
            active,
            key=lambda item: str(item.get("data_ins") or ""),
            default=None,
        )
        selected = current_plan or active_plan
        if current_plan:
            cartography = str(current_plan.get("stato_caric_pgt") or "")
            raw_status = (
                "VIGENTE_CARTOGRAFIA_CARICATA"
                if cartography.casefold() == "caricato"
                else "VIGENTE_CARTOGRAFIA_NON_CARICATA"
            )
        elif selected:
            phase = _norm(selected.get("fase_pgt")).replace(" ", "_").upper()
            raw_status = (
                "APPROVAZIONE_NON_VIGENTE"
                if phase == "APPROVAZIONE"
                else phase if phase in mapping_codes else "NON_DETERMINATO"
            )
            cartography = str(selected.get("stato_caric_pgt") or "")
        else:
            raw_status = "NON_DETERMINATO"
            cartography = "Non determinato"
            without_records.append(istat)
        normalized = mapping_codes.get(raw_status, "NON_DETERMINATO")
        definition = status_defs[normalized]
        status_counts[normalized] = status_counts.get(normalized, 0) + 1
        properties = {
            "codice_istat": istat,
            "comune": ap["name"],
            "provincia": ap["province"],
            "regione": ap["region"],
            "plan_name": str((selected or {}).get("tipo_piano") or "PGT"),
            "plan_description": (selected or {}).get("descr_piano"),
            "plan_status_raw": raw_status,
            "plan_status_code": normalized,
            "plan_status_label": definition["label"],
            "plan_status_rank": definition["rank"],
            "pgtweb_state": (selected or {}).get("stato_pgt"),
            "pgtweb_phase": (selected or {}).get("fase_pgt"),
            "cartography_status": cartography,
            "procedure_date": (selected or {}).get("data_ins"),
            "approval_date": (selected or {}).get("data_atto"),
            "burl_number": (selected or {}).get("num_burl"),
            "burl_date": (selected or {}).get("data_burl"),
            "ongoing_procedure_phase": (active_plan or {}).get("fase_pgt"),
            "ongoing_procedure_type": (active_plan or {}).get("tipo_piano"),
            "ongoing_procedure_date": (active_plan or {}).get("data_ins"),
            "source_uuid": "r_lombar_pgtweb:ijqk-ahfp",
            "source_title": "PGTWEB — Inventario dei piani",
            "source_url": (
                "https://www.dati.lombardia.it/resource/ijqk-ahfp.json"
            ),
            "source_date": source_date,
            "processed_at": processed_at,
            "coverage_status": "complete" if selected else "missing",
        }
        output.append({
            "type": "Feature",
            "geometry": admin["geometry"],
            "properties": properties,
        })
    coverage = {
        "municipalities_expected": len(municipalities),
        "municipalities_with_records": len(municipalities) - len(without_records),
        "complete": not without_records,
        "source_records": len(records),
        "deduplicated_plans": len(plans),
        "status_counts": status_counts,
    }
    return _write_target(
        "PIANI_MATURITA",
        scope,
        output,
        [
            STATUS_SOURCE_LOMBARDIA,
            LOMBARDIA_CURRENT_MUNICIPALITIES,
            TARGETS_FILE,
        ],
        status="completed" if not without_records else "partial",
        coverage=coverage,
        diagnostics={"municipalities_without_pgtweb_records": without_records},
    )


def _compose_plan_maturity_national_fallback(
    scope: dict[str, Any],
    municipalities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fallback nazionale: NON_DETERMINATO per tutte le regioni senza adapter dedicato."""
    config = yaml.safe_load(TARGETS_FILE.read_text("utf-8"))
    status_defs = config["targets"]["PIANI_MATURITA"]["statuses"]
    nd = status_defs["NON_DETERMINATO"]
    processed_at = _now()
    admin_path = ADMIN_DIR / "admin_municipalities.geojson"
    source_date = datetime.fromtimestamp(
        admin_path.stat().st_mtime, timezone.utc
    ).isoformat(timespec="seconds")
    features: list[dict[str, Any]] = []
    for admin in municipalities:
        ap = admin["properties"]
        features.append({
            "type": "Feature",
            "geometry": admin["geometry"],
            "properties": {
                "codice_istat": str(ap["key"]),
                "comune": ap["name"],
                "provincia": ap["province"],
                "regione": ap["region"],
                "plan_name": None,
                "plan_status_raw": None,
                "plan_status_code": "NON_DETERMINATO",
                "plan_status_label": nd["label"],
                "plan_status_rank": nd["rank"],
                "cartography_status": "non_determinato_dalla_fonte",
                "procedure_date": None,
                "source_uuid": "istat:confini_amministrativi:comuni",
                "source_title": "Confini amministrativi comunali (fallback nazionale)",
                "source_url": None,
                "source_date": source_date,
                "processed_at": processed_at,
                "coverage_status": "minimal",
            },
        })
    return _write_target(
        "PIANI_MATURITA",
        scope,
        features,
        [admin_path, TARGETS_FILE],
        status="partial",
        coverage={
            "municipalities_expected": len(municipalities),
            "municipalities_with_status": len(features),
            "complete": False,
            "detail": "Fallback nazionale — stato piani non determinabile senza fonte regionale",
        },
    )


def compose_plan_maturity(scope: dict[str, Any]) -> dict[str, Any]:
    municipalities = _scope_municipalities(scope)
    region_keys = {str(f["properties"]["reg_key"]) for f in municipalities}
    if region_keys == {"03"}:
        return _compose_plan_maturity_lombardia(scope, municipalities)
    if region_keys not in ({"02"}, ):
        return _compose_plan_maturity_national_fallback(scope, municipalities)
    if not STATUS_SOURCE_VDA.exists():
        return {
            "target": "PIANI_MATURITA",
            "status": "blocked",
            "message": f"Input mancante: {STATUS_SOURCE_VDA}",
        }

    mapping_codes, status_defs = _status_config("02")
    status_data = _read_json(STATUS_SOURCE_VDA)
    by_istat: dict[str, dict[str, Any]] = {}
    for feature in status_data.get("features", []):
        props = feature.get("properties") or {}
        code = str(props.get("codcom") or "").strip().zfill(3)
        if code.strip("0"):
            by_istat[f"007{code}"] = props

    processed_at = _now()
    output: list[dict[str, Any]] = []
    missing: list[str] = []
    for admin in municipalities:
        ap = admin["properties"]
        istat = str(ap["key"])
        source_props = by_istat.get(istat)
        if not source_props:
            missing.append(istat)
            continue
        raw_status = str(source_props.get("stato_prg") or "").strip().upper()
        normalized = mapping_codes.get(raw_status, "NON_DETERMINATO")
        definition = status_defs[normalized]
        properties = {
            "codice_istat": istat,
            "comune": ap["name"],
            "provincia": ap["province"],
            "regione": ap["region"],
            "plan_name": "PRG/PRGC",
            "plan_status_raw": raw_status,
            "plan_status_code": normalized,
            "plan_status_label": definition["label"],
            "plan_status_rank": definition["rank"],
            "cartography_status": (
                "in_fase_di_consegna"
                if normalized == "APPROVATO_CARTOGRAFIA_IN_CONSEGNA"
                else "non_determinato_dalla_fonte"
            ),
            "procedure_date": None,
            "source_uuid": "r_vda:prg_prescrittiva:060",
            "source_title": "Stato iter di adeguamento al PTP",
            "source_url": (
                "https://mappe.regione.vda.it/pub/geonavitg/geopiani.asp"
            ),
            "source_date": datetime.fromtimestamp(
                STATUS_SOURCE_VDA.stat().st_mtime, timezone.utc
            ).isoformat(timespec="seconds"),
            "processed_at": processed_at,
            "coverage_status": "complete",
        }
        output.append({
            "type": "Feature",
            "geometry": admin["geometry"],
            "properties": properties,
        })
    coverage = {
        "municipalities_expected": len(municipalities),
        "municipalities_with_status": len(output),
        "complete": not missing,
    }
    return _write_target(
        "PIANI_MATURITA",
        scope,
        output,
        [
            STATUS_SOURCE_VDA,
            ADMIN_DIR / "admin_municipalities.geojson",
            TARGETS_FILE,
        ],
        status="completed" if not missing else "partial",
        coverage=coverage,
        diagnostics={"municipalities_without_status": missing},
    )


def _region_entities(region: str) -> list[str]:
    """Tutte le chiavi-fonte (`key`) di una regione, lette da sources.yaml per
    `region_istat`. Così il compose funziona per ogni regione con dati, non solo
    quelle hardcoded."""
    sources_file = ROOT / "registry" / "sources.yaml"
    try:
        data = yaml.safe_load(sources_file.read_text("utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    keys: list[str] = []
    for source in data.get("sources", []) or []:
        if (
            str(source.get("region_istat") or "") == str(region)
            or source.get("applies_to_all_regions") is True
        ) and source.get("key"):
            keys.append(str(source["key"]))
    return keys


def _recognition_for_region(region: str) -> tuple[Path, list[dict[str, Any]]]:
    """Unisce il riconoscimento di TUTTE le entità della regione (una regione può
    avere più fonti: es. Trentino-Alto Adige = r_tn_pup + r_tn_pericolosita +
    r_bz_piani + …). Ogni item porta con sé l'`ente` per risolvere il file grezzo."""
    rec_dir = WORK / "recognition"
    items: list[dict[str, Any]] = []
    for entity in _region_entities(region):
        path = rec_dir / f"{entity}.json"
        if not path.exists():
            continue
        for item in _read_json(path).get("items", []):
            items.append({**item, "ente": item.get("ente") or entity})
    return rec_dir, items


def _file_slug(value: str) -> str:
    """Slug identico a quello degli adapter WFS/ArcGIS/CKAN (per ricostruire i
    nomi file dei GeoJSON scaricati)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "_".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split()) or "layer"


def _source_root(ente: str) -> Path | None:
    for livello in ("nazionale", "regione", "provincia", "comune"):
        root = RAW / livello / ente
        if root.exists():
            return root
    return None


def _resolve_raw(item: dict[str, Any]) -> Path | None:
    """UUID → file GeoJSON grezzo, indipendente dall'adapter. Prova in ordine:
    convenzioni storiche VdA/Liguria, match per `uuid` nel `_manifest.json` di
    download (piemonte_catalog), ricostruzione nome file (wfs_generic/arcgis),
    match CKAN per dataset. Restituisce il primo file esistente o None."""
    uuid = str(item.get("uuid") or "")
    parts = uuid.split(":")
    if not parts or not parts[0]:
        return None
    ente = str(item.get("ente") or parts[0])

    # 1) convenzioni storiche a cartelle annidate (VdA / Liguria)
    if parts[0] == "r_vda" and len(parts) == 3:
        base = RAW / "regione" / "r_vda" / parts[1]
        for ext in ("geojson", "shp"):
            matches = sorted(base.glob(f"{parts[2]}_*.{ext}"))
            if matches:
                return matches[0]
        return None
    if parts[0] == "r_liguria" and len(parts) == 3:
        base = RAW / "regione" / "r_liguria"
        for ext in ("geojson", "shp"):
            matches = sorted(base.glob(f"{parts[1]}_*/{parts[2]}_*.{ext}"))
            if matches:
                return matches[0]
        return None

    root = _source_root(ente)
    if root is None:
        return None

    # 2) match per uuid nel manifest di download
    results: list[dict[str, Any]] = []
    manifest = root / "_manifest.json"
    if manifest.exists():
        try:
            data = _read_json(manifest)
            results = data.get("results") or data.get("datasets") or []
        except Exception:
            results = []
        for row in results:
            row_uuid = str(row.get("uuid") or "")
            if row_uuid == uuid and row.get("local_path"):
                candidate = root / str(row["local_path"])
                if candidate.exists():
                    return candidate
            # ArcGIS manifests: match by service_key:layer_id → uuid tail
            if not row_uuid and len(parts) >= 3:
                lk = str(row.get("layer_key") or "")
                if lk == ":".join(parts[1:]):
                    for field in ("local_path", "path"):
                        lp = row.get(field)
                        if lp:
                            candidate = root / str(lp)
                            if candidate.exists():
                                return candidate
            # websit_xml / piemonte_catalog: match by archive name → uuid tail
            if not row_uuid and len(parts) >= 2:
                archive = str(row.get("archive") or "")
                if archive and archive == parts[-1]:
                    for field in ("local_path", "path"):
                        lp = row.get(field)
                        if lp:
                            candidate = root / str(lp)
                            if candidate.exists():
                                return candidate

    # 3) ricostruzione nome file per adapter deterministici
    rest = uuid.split(":", 1)[1] if len(parts) > 1 else ""
    for ext in ("geojson", "shp"):
        candidate = root / f"{_file_slug(rest)}.{ext}"
        if candidate.exists():
            return candidate
    for ext in ("geojson", "shp"):
        glob_matches = sorted(root.glob(f"L{parts[-1]}_*.{ext}"))
        if glob_matches:
            return glob_matches[0]
    # arcgis_rest: anche in sottocartelle service_key/
    if len(parts) >= 3:
        svc = parts[1]
        for ext in ("geojson", "shp"):
            glob_matches = sorted(root.glob(f"{svc}/L{parts[-1]}_*.{ext}"))
            if glob_matches:
                return glob_matches[0]

    # 4) ckan_collection: match nel manifest per dataset
    if len(parts) >= 2 and results:
        for row in results:
            if str(row.get("dataset") or "") == parts[1]:
                for field in ("local_path", "path"):
                    lp = row.get(field)
                    if lp:
                        candidate = root / str(lp)
                        if candidate.exists():
                            return candidate
    return None


def _constraint_family(canonical: str) -> str:
    if canonical in {"DISSESTO_GEOLOGICO", "RISCHIO_IDRAULICO", "VINCOLO_IDROGEOLOGICO"}:
        return "inedificabilita_e_dissesto"
    if canonical == "VINCOLI_PAESAGGISTICI":
        return "paesaggio_e_beni_culturali"
    if canonical in {"AREE_PROTETTE", "RETE_ECOLOGICA", "AGRICOLTURA"}:
        return "natura_e_biodiversita"
    if canonical == "ACQUE":
        return "acque"
    if canonical in {"ENERGIA", "FERROVIA", "VIABILITA", "SOSTA_ACCESSI"}:
        return "infrastrutture_e_fasce_rispetto"
    return "disciplina_urbanistica"


def _constraint_severity(item: dict[str, Any]) -> tuple[str, str]:
    canonical = str(item.get("canonical_key") or "")
    text = _norm(item.get("title"))
    blocking_terms = (
        "pericolosita molto elevata",
        "frana attiva",
        "conoide attivo non protetta",
        "inedificabil",
    )
    if canonical in {"DISSESTO_GEOLOGICO", "RISCHIO_IDRAULICO"} and any(
        term in text for term in blocking_terms
    ):
        return "blocking", "Possibile incompatibilità esplicita: verificare disciplina e classe della fonte."
    if canonical in {
        "DISSESTO_GEOLOGICO",
        "RISCHIO_IDRAULICO",
        "VINCOLO_IDROGEOLOGICO",
        "VINCOLI_PAESAGGISTICI",
        "AREE_PROTETTE",
        "PRG_ZONING",
    }:
        return "conditional", "Intervento subordinato alla disciplina e alle autorizzazioni applicabili."
    return "informative", "Elemento territoriale informativo; nessun effetto edificatorio automatico."


def _valid_geometry(value: Any) -> BaseGeometry | None:
    if not value:
        return None
    try:
        geom = shape(value)
        if geom.is_empty:
            return None
        if not geom.is_valid and geom.geom_type in {"Polygon", "MultiPolygon"}:
            geom = geom.buffer(0)
        return None if geom.is_empty else geom
    except Exception:
        return None


def compose_constraints(scope: dict[str, Any]) -> dict[str, Any]:
    municipalities = _scope_municipalities(scope)
    regions = {str(f["properties"]["reg_key"]) for f in municipalities}
    if len(regions) != 1:
        raise ValueError("Lo scope deve appartenere a una sola regione.")
    region = next(iter(regions))
    _recognition_path, items = _recognition_for_region(region)
    if not items:
        return {
            "target": "VINCOLI_COMUNALI",
            "status": "blocked",
            "message": "Riconoscimento regionale assente: eseguire prima Scoperta e Riconoscimento.",
        }

    candidates: list[tuple[dict[str, Any], Path]] = []
    missing_sources: list[str] = []
    for item in items:
        if item.get("canonical_key") not in CONSTRAINT_CLASSES:
            continue
        path = _resolve_raw(item)
        if path and path.exists():
            candidates.append((item, path))
        else:
            missing_sources.append(str(item.get("uuid") or ""))
    if not candidates:
        return {
            "target": "VINCOLI_COMUNALI",
            "status": "blocked",
            "message": "Nessun layer di vincolo riconosciuto è disponibile localmente.",
        }

    admin_geometries = [_valid_geometry(f["geometry"]) for f in municipalities]
    usable = [(f, g) for f, g in zip(municipalities, admin_geometries) if g is not None]
    admin_features = [pair[0] for pair in usable]
    admin_shapes = [pair[1] for pair in usable]
    tree = STRtree(admin_shapes)
    scope_bounds = (
        min(geom.bounds[0] for geom in admin_shapes),
        min(geom.bounds[1] for geom in admin_shapes),
        max(geom.bounds[2] for geom in admin_shapes),
        max(geom.bounds[3] for geom in admin_shapes),
    )
    output: list[dict[str, Any]] = []
    invalid = 0
    source_failures: list[dict[str, str]] = []
    skipped_large: list[dict[str, Any]] = []
    max_bytes = MAX_SOURCE_FILE_MB * 1_000_000
    processed_at = _now()

    for item, path in candidates:
        if not path.name.startswith("hotosm_") and path.stat().st_size > max_bytes:
            skipped_large.append({"path": str(path), "mb": path.stat().st_size // 1_000_000})
            continue
        canonical = str(item.get("canonical_key") or "")
        severity, effect = _constraint_severity(item)
        source_date = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(
            timespec="seconds"
        )
        try:
            feature_iter = _iter_source_features(path, scope_bounds)
        except Exception as exc:
            source_failures.append({"path": str(path), "reason": str(exc)})
            continue
        try:
            source_features_list = list(feature_iter)
        except Exception as exc:
            source_failures.append({"path": str(path), "reason": str(exc)})
            continue
        for source_feature in source_features_list:
            source_geom = _valid_geometry(source_feature.get("geometry"))
            if source_geom is None:
                invalid += 1
                continue
            for index in tree.query(source_geom, predicate="intersects"):
                admin = admin_features[int(index)]
                admin_geom = admin_shapes[int(index)]
                try:
                    clipped = source_geom.intersection(admin_geom)
                except Exception:
                    invalid += 1
                    continue
                if clipped.is_empty:
                    continue
                area_pct = (
                    round(min(100.0, clipped.area / admin_geom.area * 100), 6)
                    if admin_geom.area and clipped.geom_type in {"Polygon", "MultiPolygon"}
                    else 0.0
                )
                ap = admin["properties"]
                sp = source_feature.get("properties") or {}
                feature_id = next(
                    (sp.get(k) for k in ("objectid", "OBJECTID", "fid", "id") if sp.get(k) is not None),
                    None,
                )
                output.append({
                    "type": "Feature",
                    "geometry": mapping(clipped),
                    "properties": {
                        "codice_istat": ap["key"],
                        "comune": ap["name"],
                        "provincia": ap["province"],
                        "regione": ap["region"],
                        "constraint_family": _constraint_family(canonical),
                        "constraint_name": item.get("title") or path.stem,
                        "severity": severity,
                        "effect": effect,
                        "legal_reference": None,
                        "source_coverage_pct": area_pct,
                        "source_feature_id": feature_id,
                        "source_uuid": item.get("uuid"),
                        "source_title": item.get("title"),
                        "source_url": item.get("url"),
                        "source_date": source_date,
                        "processed_at": processed_at,
                        "coverage_status": "partial",
                        "canonical_key": canonical,
                        "match_confidence": item.get("confidence"),
                    },
                })

    catalog_total = 0
    catalog_path = WORK / "catalog" / (f"r_vda.csv" if region == "02" else "r_liguria.csv")
    if catalog_path.exists():
        with catalog_path.open("r", encoding="utf-8-sig") as handle:
            catalog_total = max(0, sum(1 for _ in handle) - 1)
    coverage = {
        "inventory_complete": False,
        "recognized_constraint_sources_available": len(candidates),
        "recognized_constraint_sources_missing": len(missing_sources),
        "regional_catalog_layers": catalog_total,
        "note": "Inventario ancora parziale: le assenze non possono essere interpretate come assenza di vincoli.",
    }
    return _write_target(
        "VINCOLI_COMUNALI",
        scope,
        output,
        [
            _recognition_path,
            ADMIN_DIR / "admin_municipalities.geojson",
            TARGETS_FILE,
            *[path for _, path in candidates],
        ],
        status="partial",
        coverage=coverage,
        diagnostics={
            "invalid_or_unreadable_features": invalid,
            "source_failures": source_failures,
            "missing_source_uuids": missing_sources[:100],
            "skipped_large_files": skipped_large,
        },
    )


def compose_buildability(scope: dict[str, Any]) -> dict[str, Any]:
    municipalities = _scope_municipalities(scope)
    regions = {str(f["properties"]["reg_key"]) for f in municipalities}
    territory = str(scope.get("key") or "regione")
    plan_output = OUT / "PIANI_MATURITA" / f"{territory}.geojson"
    constraints_manifest = OUT / "VINCOLI_COMUNALI" / f"{territory}.manifest.json"
    missing_inputs: list[str] = []
    if not ZONE_SOURCE_VDA.exists():
        missing_inputs.append("P4 Zone non acquisito (HTTP 400 dal portale)")
    if not plan_output.exists():
        missing_inputs.append("stato del piano non composto per lo scope")
    inventory_complete = False
    if constraints_manifest.exists():
        try:
            inventory_complete = bool(
                _read_json(constraints_manifest).get("coverage", {}).get("inventory_complete")
            )
        except Exception:
            pass
    if not inventory_complete:
        missing_inputs.append("inventario completo dei vincoli non certificato")

    # Il fallback è esclusivamente un overview comunale dichiarato come tale:
    # non simula le zone P4 e non attribuisce edificabilità.
    processed_at = _now()
    features: list[dict[str, Any]] = []
    reason = "; ".join(missing_inputs) or "input obbligatori non verificati"
    for admin in municipalities:
        ap = admin["properties"]
        features.append({
            "type": "Feature",
            "geometry": admin["geometry"],
            "properties": {
                "codice_istat": ap["key"],
                "comune": ap["name"],
                "provincia": ap["province"],
                "regione": ap["region"],
                "geometry_granularity": "municipality_overview",
                "signal": "UNASSESSED",
                "signal_label": "Non valutabile per copertura insufficiente",
                "intervention_mode": "non_determinabile",
                "reasons": [reason],
                "blocking_constraints": [],
                "conditional_constraints": [],
                "required_checks": missing_inputs,
                "source_coverage_pct": 0.0,
                "confidence": 0.0,
                "source_uuid": "istat:confini_amministrativi:comuni",
                "source_title": "Confini amministrativi comunali",
                "source_url": None,
                "source_date": datetime.fromtimestamp(
                    (ADMIN_DIR / "admin_municipalities.geojson").stat().st_mtime,
                    timezone.utc,
                ).isoformat(timespec="seconds"),
                "processed_at": processed_at,
                "coverage_status": "incomplete",
                "disclaimer": (
                    "Screening tecnico non sostitutivo di certificato urbanistico, "
                    "titolo edilizio, pareri o autorizzazioni."
                ),
            },
        })
    sources = [
        ADMIN_DIR / "admin_municipalities.geojson",
        TARGETS_FILE,
        plan_output,
        constraints_manifest,
    ]
    if ZONE_SOURCE_VDA.exists():
        sources.append(ZONE_SOURCE_VDA)
    return _write_target(
        "SEMAFORO_EDIFICABILITA",
        scope,
        features,
        sources,
        status="partial",
        coverage={
            "complete": False,
            "detail_available": False,
            "overview_municipalities": len(features),
            "missing_inputs": missing_inputs,
        },
        diagnostics={
            "note": (
                "Pubblicato soltanto l'overview comunale UNASSESSED; "
                "nessuna zona verde, gialla o rossa è stata inferita."
            )
        },
    )


def compose_feature_layer(target: str, scope: dict[str, Any]) -> dict[str, Any]:
    """Builder GENERICO, region-agnostic, per i layer finali "a feature con classi".

    Raccoglie dal riconoscimento regionale i layer grezzi la cui classe canonica
    (`canonical_key`) appartiene alle `sources` del target, li ritaglia sui comuni
    dello scope e li emette come un unico GeoJSON con provenienza per feature.
    Funziona per ogni regione con dati (usa `_recognition_for_region` +
    `_resolve_raw` generici). I target speciali (Semaforo, inventario Vincoli,
    Stato piani) restano gestiti dai loro builder dedicati.
    """
    config = yaml.safe_load(TARGETS_FILE.read_text("utf-8"))["targets"].get(target, {})
    wanted_classes = set(config.get("sources", []) or [])
    municipalities = _scope_municipalities(scope)
    regions = {str(f["properties"]["reg_key"]) for f in municipalities}
    if len(regions) != 1:
        raise ValueError("Lo scope deve appartenere a una sola regione.")
    region = next(iter(regions))
    _rec, items = _recognition_for_region(region)
    if not items:
        return {"target": target, "status": "blocked",
                "message": "Riconoscimento regionale assente: eseguire prima Scoperta e Riconoscimento."}
    if not wanted_classes:
        return {"target": target, "status": "blocked",
                "message": f"Il target {target} non dichiara `sources` (classi canoniche)."}

    candidates: list[tuple[dict[str, Any], Path]] = []
    missing: list[str] = []
    skipped_large: list[dict[str, Any]] = []
    max_bytes = MAX_SOURCE_FILE_MB * 1_000_000
    for item in items:
        if item.get("canonical_key") not in wanted_classes:
            continue
        path = _resolve_raw(item)
        if path and path.exists() and path.suffix.lower() in {".geojson", ".shp"}:
            if not path.name.startswith("hotosm_") and path.stat().st_size > max_bytes:
                skipped_large.append({"path": str(path), "mb": path.stat().st_size // 1_000_000})
                continue
            candidates.append((item, path))
        else:
            missing.append(str(item.get("uuid") or ""))
    if not candidates:
        return {"target": target, "status": "blocked",
                "message": f"Nessun layer riconosciuto per {target} è disponibile localmente in GeoJSON."}

    admin_geometries = [_valid_geometry(f["geometry"]) for f in municipalities]
    usable = [(f, g) for f, g in zip(municipalities, admin_geometries) if g is not None]
    admin_features = [pair[0] for pair in usable]
    admin_shapes = [pair[1] for pair in usable]
    tree = STRtree(admin_shapes)
    scope_bounds = (
        min(geom.bounds[0] for geom in admin_shapes),
        min(geom.bounds[1] for geom in admin_shapes),
        max(geom.bounds[2] for geom in admin_shapes),
        max(geom.bounds[3] for geom in admin_shapes),
    )
    output: list[dict[str, Any]] = []
    invalid = 0
    source_failures: list[dict[str, str]] = []
    processed_at = _now()

    for item, path in candidates:
        canonical = str(item.get("canonical_key") or "")
        try:
            for feature in _iter_source_features(path, scope_bounds):
                geom = _valid_geometry(feature.get("geometry"))
                if geom is None:
                    invalid += 1
                    continue
                # Assegna la feature al primo comune dello scope che interseca
                # senza duplicarla sui confini amministrativi.
                admin = None
                for index in tree.query(geom):
                    shape_geom = admin_shapes[int(index)]
                    try:
                        if geom.intersects(shape_geom):
                            admin = admin_features[int(index)]
                            break
                    except Exception:
                        invalid += 1
                if admin is None:
                    continue
                ap = admin["properties"]
                sp = feature.get("properties") or {}
                poi_family, poi_value = _poi_class(sp)
                ente_key = str(item.get("ente") or "")
                lic, attr = _license_for_ente(ente_key)
                properties = {
                    "codice_istat": ap["key"],
                    "comune": ap["name"],
                    "provincia": ap["province"],
                    "regione": ap["region"],
                    "class": canonical.lower(),
                    "canonical_class": canonical,
                    "source_uuid": item.get("uuid"),
                    "source_title": item.get("title"),
                    "source_url": item.get("url"),
                    "source_ente": ente_key,
                    "license": lic,
                    "attribution": attr,
                    "processed_at": processed_at,
                    "coverage_status": "tagged",
                    "attributes": sp,
                }
                if canonical in {"POI_PUNTUALI", "USI_POI_POLIGONALI"}:
                    properties.update({
                        "class": poi_value or "non_classificato",
                        "poi_family": poi_family,
                        "poi_value": poi_value,
                        "name": sp.get("name") or sp.get("name_it"),
                        "osm_id": sp.get("osm_id"),
                        "osm_type": sp.get("osm_type"),
                        "data_role": (
                            "uso_osservato_non_prescrittivo"
                            if canonical == "USI_POI_POLIGONALI"
                            else "punto_interesse"
                        ),
                        "license": "ODbL 1.0",
                        "attribution": "© OpenStreetMap contributors; export HOTOSM",
                    })
                elif canonical == "DISTRIBUTORI_CARBURANTE":
                    properties.update({
                        "class": "distributore_carburante",
                        "poi_family": "distributore_carburante",
                        "poi_value": _norm(sp.get("Bandiera")) or "carburante",
                        "name": sp.get("Nome Impianto") or sp.get("Bandiera") or sp.get("Gestore"),
                        "gestore": sp.get("Gestore"),
                        "bandiera": sp.get("Bandiera"),
                        "tipo_impianto": sp.get("Tipo Impianto"),
                        "indirizzo": sp.get("Indirizzo"),
                        "data_role": "punto_interesse",
                        "license": "Open data MIMIT",
                        "attribution": "MIMIT — Osservatorio Prezzi Carburanti",
                    })
                output.append({
                    "type": "Feature",
                    "geometry": mapping(geom),
                    "properties": properties,
                })
        except Exception as exc:
            source_failures.append({"path": str(path), "reason": str(exc)})

    status = "partial" if missing or source_failures else "completed"
    coverage = {
        "recognized_sources_available": len(candidates),
        "recognized_sources_missing": len(missing),
        "classes": sorted(wanted_classes),
    }
    return _write_target(
        target,
        scope,
        output,
        [ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE, *[p for _, p in candidates]],
        status=status,
        coverage=coverage,
        diagnostics={
            "invalid_or_unreadable_features": invalid,
            "source_failures": source_failures,
            "missing_source_uuids": missing[:100],
            "skipped_large_files": skipped_large,
        },
    )


# --------------------------------------------------------------------------
# Builder TABELLARE nazionale: dato per-comune (senza geometria propria) unito
# alla geometria comunale ISTAT. Primo caso: DEMOGRAFIA dal censimento permanente.
# --------------------------------------------------------------------------
CENSUS_DIR = (
    RAW / "nazionale" / "n_istat_censimento_sezioni"
    / "dati_regionali_2023" / "extracted"
)
# Classi di età del tracciato ISTAT (P14=<5 … P29=>74) aggregate in fasce utili.
_CENSUS_AGE = {
    "pop_0_14": ["P14", "P15", "P16"],
    "pop_15_64": ["P17", "P18", "P19", "P20", "P21",
                  "P22", "P23", "P24", "P25", "P26"],
    "pop_65_e_oltre": ["P27", "P28", "P29"],
}


def _census_regional_file(region: str) -> Path | None:
    prefix = f"R{str(region).zfill(2)}_"
    if not CENSUS_DIR.exists():
        return None
    matches = sorted(CENSUS_DIR.rglob(f"{prefix}*.xlsx"))
    return matches[0] if matches else None


def _census_by_comune(path: Path) -> dict[str, dict[str, Any]]:
    """Aggrega le righe-sezione per comune (PROCOM) sommando le variabili di
    popolazione. Ritorna {codice_istat 6 cifre: {popolazione, età, indici}}."""
    import pandas as pd  # import pesante: solo quando serve

    value_cols = ["P1", "P2", "P3"] + [c for cols in _CENSUS_AGE.values() for c in cols]
    wanted = {"PROCOM", *value_cols}
    frame = pd.read_excel(path, usecols=lambda c: c in wanted)
    for col in value_cols:
        if col not in frame.columns:
            frame[col] = 0
    frame[value_cols] = frame[value_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
    frame = frame.dropna(subset=["PROCOM"])
    grouped = frame.groupby("PROCOM")[value_cols].sum()
    out: dict[str, dict[str, Any]] = {}
    for procom, row in grouped.iterrows():
        key = str(int(procom)).zfill(6)
        rec: dict[str, Any] = {
            "popolazione": int(row["P1"]),
            "maschi": int(row["P2"]),
            "femmine": int(row["P3"]),
        }
        for fascia, cols in _CENSUS_AGE.items():
            rec[fascia] = int(sum(int(row[c]) for c in cols))
        p0, p65, p1564 = rec["pop_0_14"], rec["pop_65_e_oltre"], rec["pop_15_64"]
        rec["indice_vecchiaia"] = round(p65 / p0 * 100, 1) if p0 else None
        rec["indice_dipendenza"] = round((p0 + p65) / p1564 * 100, 1) if p1564 else None
        out[key] = rec
    return out


def _load_irpef_tabular() -> dict[str, dict[str, Any]]:
    """Carica il CSV IRPEF comunale (se scaricato) indicizzato per codice ISTAT."""
    base = RAW / "nazionale" / "n_mef_irpef"
    if not base.exists():
        return {}
    matches = sorted(base.rglob("*.csv"))
    if not matches:
        return {}
    cfg = {
        "code_column": "Codice Istat Comune",
        "code_zfill": 6,
        "sep": ";",
        "drop_columns": [
            "Anno di imposta", "Codice catastale", "Codice Istat Comune",
            "Denominazione Comune", "Sigla Provincia", "Regione",
            "Codice Istat Regione",
        ],
    }
    try:
        return _tabular_by_comune(matches[0], cfg)
    except Exception:
        return {}


def compose_demografia(scope: dict[str, Any]) -> dict[str, Any]:
    """DEMOGRAFIA: popolazione residente e indici per comune, dal Censimento
    permanente ISTAT 2023 (dati per sezione, aggregati a comune) uniti alla
    geometria comunale. Fonte nazionale → funziona su ogni regione scaricata."""
    municipalities = _scope_municipalities(scope)
    regions = {str(f["properties"]["reg_key"]) for f in municipalities}
    if len(regions) != 1:
        raise ValueError("Lo scope deve appartenere a una sola regione.")
    region = next(iter(regions))
    path = _census_regional_file(region)
    if path is None:
        return {"target": "DEMOGRAFIA", "status": "blocked",
                "message": "Dati censimento ISTAT non presenti: eseguire il Download "
                           "della fonte n_istat_censimento_sezioni."}
    try:
        by_comune = _census_by_comune(path)
    except Exception as exc:  # noqa: BLE001
        return {"target": "DEMOGRAFIA", "status": "blocked",
                "message": f"Lettura censimento ISTAT fallita: {exc}"}

    processed_at = _now()
    output: list[dict[str, Any]] = []
    usable = 0
    matched = 0
    for feature in municipalities:
        ap = feature["properties"]
        geom = _valid_geometry(feature.get("geometry"))
        if geom is None:
            continue
        usable += 1
        rec = by_comune.get(str(ap["key"]))
        properties: dict[str, Any] = {
            "codice_istat": ap["key"],
            "comune": ap["name"],
            "provincia": ap.get("province"),
            "regione": ap.get("region"),
            "class": "demografia",
            "canonical_class": "DEMOGRAFIA",
            "source_uuid": "n_istat_censimento_sezioni:censimento_2023",
            "source_title": "ISTAT — Censimento permanente popolazione 2023 (per sezione)",
            "source_url": "https://www.istat.it/notizia/dati-per-sezioni-di-censimento/",
            "source_ente": "n_istat_censimento_sezioni",
            "license": "CC BY 4.0 · ISTAT",
            "attribution": "ISTAT — Censimento permanente 2023",
            "processed_at": processed_at,
            "coverage_status": "tagged" if rec else "senza_dato",
        }
        if rec:
            properties.update(rec)
            matched += 1
        output.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": properties,
        })

    irpef_data = _load_irpef_tabular()
    irpef_matched = 0
    if irpef_data:
        for feat in output:
            code = feat["properties"].get("codice_istat")
            irpef_rec = irpef_data.get(str(code))
            if irpef_rec:
                feat["properties"].update(irpef_rec)
                irpef_matched += 1

    all_codes = {str(f["properties"]["codice_istat"]) for f in output
                 if f["properties"].get("codice_istat")}
    cru_cens = _load_cruscotto_section("censimento", all_codes)
    cens_matched = 0
    for feat in output:
        code = str(feat["properties"].get("codice_istat", ""))
        sec = cru_cens.get(code)
        if not sec:
            continue
        kpi = sec.get("kpi_comune") or {}
        dist = sec.get("distribuzioni_comune") or {}
        if not kpi:
            continue
        cens_matched += 1
        p = feat["properties"]
        p["n_sezioni"] = kpi.get("n_sezioni", 0)
        p["famiglie_totali"] = kpi.get("famiglie_totali", 0)
        p["abitazioni_totali"] = kpi.get("abitazioni_totali", 0)
        p["abitazioni_occupate"] = kpi.get("abitazioni_occupate", 0)
        p["abitazioni_vuote"] = kpi.get("abitazioni_vuote", 0)
        p["stranieri_totali"] = kpi.get("stranieri_totali", 0)
        p["stranieri_ue"] = kpi.get("stranieri_ue", 0)
        p["stranieri_extra_ue"] = kpi.get("stranieri_extra_ue", 0)
        p["occupati_15_64"] = kpi.get("occupati_15_64", 0)
        p["occupati_maschi"] = kpi.get("occupati_maschi", 0)
        p["occupati_femmine"] = kpi.get("occupati_femmine", 0)
        p["area_kmq_censimento"] = kpi.get("area_kmq", 0)
        pop = p.get("popolazione", 0) or kpi.get("pop_totale", 0)
        area = kpi.get("area_kmq", 0)
        ab_tot = kpi.get("abitazioni_totali", 0)
        stran = kpi.get("stranieri_totali", 0)
        occ = kpi.get("occupati_15_64", 0)
        fam = kpi.get("famiglie_totali", 0)
        p1564 = p.get("pop_15_64", 0) or (dist.get("eta_per_fascia") or {}).get("15-64", 0)
        if area:
            p["densita_pop_kmq"] = round(pop / area, 1)
        if ab_tot:
            p["pct_abitazioni_vuote"] = round(kpi.get("abitazioni_vuote", 0) / ab_tot * 100, 1)
        if pop:
            p["pct_stranieri"] = round(stran / pop * 100, 1)
        if stran:
            p["pct_stranieri_extra_ue"] = round(kpi.get("stranieri_extra_ue", 0) / stran * 100, 1)
        if p1564:
            p["pct_occupati_15_64"] = round(occ / p1564 * 100, 1)
        if occ:
            p["pct_donne_occupate"] = round(kpi.get("occupati_femmine", 0) / occ * 100, 1)
        if fam:
            fam1 = int((dist.get("famiglie_componenti") or {}).get("1", 0))
            p["pct_famiglie_unipersonali"] = round(fam1 / fam * 100, 1)
        tit = dist.get("titolo_studio_9plus") or {}
        tot_tit = sum(tit.values())
        if tot_tit:
            p["pct_laureati"] = round(tit.get("terziario", 0) / tot_tit * 100, 1)

    complete = usable > 0 and matched == usable
    coverage = {
        "complete": complete,
        "comuni_totali": usable,
        "comuni_con_dato": matched,
        "fonte": "ISTAT Censimento permanente 2023",
    }
    if irpef_data:
        coverage["irpef_comuni_con_dato"] = irpef_matched
        coverage["irpef_fonte"] = "MEF — IRPEF comunale"
    if cru_cens:
        coverage["censimento_cruscotto_comuni"] = cens_matched
        coverage["censimento_fonte"] = "ISTAT Basi Territoriali 2021 + Variabili censuarie 2023"
    return _write_target(
        "DEMOGRAFIA",
        scope,
        output,
        [path, ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status="completed" if complete else "partial",
        coverage=coverage,
        diagnostics={"comuni_senza_dato": usable - matched},
    )


_cruscotto_json_cache: dict[str, dict[str, Any] | None] = {}


def _load_cruscotto_json(code: str) -> dict[str, Any] | None:
    if code in _cruscotto_json_cache:
        return _cruscotto_json_cache[code]
    fp = RAW / "nazionale" / "n_cruscotto_italia" / "_cache" / f"{code}.json"
    if not fp.exists():
        _cruscotto_json_cache[code] = None
        return None
    try:
        data = json.loads(fp.read_text("utf-8"))
    except Exception:
        _cruscotto_json_cache[code] = None
        return None
    _cruscotto_json_cache[code] = data
    return data


def _load_cruscotto_section(section: str, istat_codes: set[str]) -> dict[str, dict[str, Any]]:
    """Carica una sezione del cruscotto cache per i comuni specificati."""
    out: dict[str, dict[str, Any]] = {}
    for code in istat_codes:
        data = _load_cruscotto_json(code)
        if not data:
            continue
        sec = data.get(section)
        if sec:
            out[code] = sec
    return out


def _cruscotto_beni_kpi(istat_codes: set[str]) -> dict[str, dict[str, Any]]:
    """KPI beni_culturali dal cruscotto (ArCo + Cultural-ON unificati)."""
    raw = _load_cruscotto_section("beni_culturali", istat_codes)
    out: dict[str, dict[str, Any]] = {}
    for code, bc_sec in raw.items():
        bc = (bc_sec or {}).get("kpi")
        if not bc:
            continue
        out[code] = {
            "n_arco": bc.get("n_arco", 0),
            "n_cultural_on": bc.get("n_cultural_on", 0),
            "n_visitabili": bc.get("n_visitabili", 0),
            "n_con_coordinate": bc.get("n_con_coordinate", 0),
            "pct_con_foto": bc.get("pct_con_foto"),
            "pct_con_descrizione": bc.get("pct_con_descrizione"),
            "mix_categoria": bc.get("mix_categoria", {}),
        }
    return out


def compose_beni_culturali(scope: dict[str, Any]) -> dict[str, Any]:
    """BENI_CULTURALI: ArCo (SPARQL conteggi per tipo) arricchito con KPI
    dal cruscotto (ArCo + Cultural-ON unificati, mix categorie, foto, descrizioni)."""
    cfg = (yaml.safe_load(TARGETS_FILE.read_text("utf-8"))["targets"]
           .get("BENI_CULTURALI", {}).get("arco_source"))
    if not cfg:
        return {"target": "BENI_CULTURALI", "status": "blocked",
                "message": "Config 'arco_source' assente per BENI_CULTURALI."}
    ente = str(cfg["source_ente"])
    ds_key = str(cfg["dataset_key"])
    geojson_path = RAW / "nazionale" / ente / ds_key / f"{ds_key}.geojson"
    if not geojson_path.exists():
        return {"target": "BENI_CULTURALI", "status": "blocked",
                "message": f"Download ArCo non presente: eseguire discover+download di {ente}."}

    type_map = cfg.get("type_map", {})
    arco_data = _read_json(geojson_path)
    by_city: dict[str, dict[str, int]] = {}
    for feat in arco_data.get("features", []):
        p = feat.get("properties", {})
        city = str(p.get("city_name") or "").strip().upper()
        raw_type = str(p.get("prop_type") or "").rsplit("/", 1)[-1]
        mapped = type_map.get(raw_type, _slug(raw_type))
        count = int(float(p.get("count") or 0))
        if not city:
            continue
        entry = by_city.setdefault(city, {})
        entry[mapped] = entry.get(mapped, 0) + count

    municipalities = _scope_municipalities(scope)
    istat_codes = {str(f["properties"]["key"]) for f in municipalities}
    cruscotto_beni = _cruscotto_beni_kpi(istat_codes)
    processed_at = _now()
    norm_lookup: dict[str, dict[str, int]] = {}
    for city, vals in by_city.items():
        nk = re.sub(r"[\s\-']+", " ", city).strip()
        existing = norm_lookup.get(nk)
        if existing:
            for t, c in vals.items():
                existing[t] = existing.get(t, 0) + c
        else:
            norm_lookup[nk] = dict(vals)
    output: list[dict[str, Any]] = []
    usable = matched = 0
    for feature in municipalities:
        ap = feature["properties"]
        geom = _valid_geometry(feature.get("geometry"))
        if geom is None:
            continue
        usable += 1
        raw_name = str(ap.get("name") or "")
        norm_name = re.sub(r"[\s\-']+", " ", _norm(raw_name).upper()).strip()
        rec = norm_lookup.get(norm_name)
        if not rec:
            alt = norm_name.replace("/", " ").replace("  ", " ")
            rec = norm_lookup.get(alt)
        total = sum(rec.values()) if rec else 0
        properties: dict[str, Any] = {
            "codice_istat": ap["key"],
            "comune": ap.get("name"),
            "provincia": ap.get("province"),
            "regione": ap.get("region"),
            "class": "beni_culturali",
            "canonical_class": "BENI_CULTURALI",
            "source_uuid": cfg.get("source_uuid", f"{ente}:{ds_key}"),
            "source_title": cfg.get("source_title", ente),
            "source_url": cfg.get("source_url", ""),
            "source_ente": ente,
            "license": cfg.get("license", ""),
            "attribution": cfg.get("attribution", ""),
            "processed_at": processed_at,
            "coverage_status": "tagged" if rec else "senza_dato",
            "beni_totali": total,
        }
        if rec:
            for tipo, cnt in sorted(rec.items()):
                properties[f"beni_{tipo}"] = cnt
            matched += 1
        cru = cruscotto_beni.get(str(ap["key"]))
        if cru:
            properties["n_arco"] = cru["n_arco"]
            properties["n_cultural_on"] = cru["n_cultural_on"]
            properties["n_visitabili"] = cru["n_visitabili"]
            properties["n_con_coordinate"] = cru["n_con_coordinate"]
            if cru.get("pct_con_foto") is not None:
                properties["pct_con_foto"] = cru["pct_con_foto"]
            if cru.get("pct_con_descrizione") is not None:
                properties["pct_con_descrizione"] = cru["pct_con_descrizione"]
            mix = cru.get("mix_categoria", {})
            for cat, cnt in sorted(mix.items()):
                properties[f"cat_{cat}"] = cnt
            if not rec:
                properties["beni_totali"] = cru["n_arco"] + cru["n_cultural_on"]
                properties["coverage_status"] = "tagged"
                matched += 1
        output.append({"type": "Feature", "geometry": mapping(geom), "properties": properties})

    complete = usable > 0 and matched == usable
    coverage = {
        "complete": complete,
        "comuni_totali": usable,
        "comuni_con_dato": matched,
        "citta_arco_non_matchate": len(by_city) - matched,
        "comuni_con_cruscotto": len(cruscotto_beni),
        "fonte": "ArCo + Cultural-ON (cruscotto unificato)",
    }
    return _write_target(
        "BENI_CULTURALI", scope, output,
        [geojson_path, ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status="completed" if complete else "partial",
        coverage=coverage,
        diagnostics={"comuni_senza_dato": usable - matched},
    )


def _slug(name: str) -> str:
    import re
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip().lower()).strip("_")
    return s or "col"


def _to_num(value: Any) -> Any:
    """Converte una cella in numero (gestendo i formati italiani), altrimenti la
    lascia come stringa; vuoto → None."""
    import re
    v = str(value).strip()
    if v == "":
        return None
    t = v
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", v):   # 1.234.567,89
        t = v.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d+,\d+", v):                   # 1234,56
        t = v.replace(",", ".")
    try:
        f = float(t)
        return int(f) if f.is_integer() else round(f, 4)
    except ValueError:
        return v


def _tabular_by_comune(path: Path, cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Legge una tabella (CSV o XLSX) e la indicizza per codice comune ISTAT
    (6 cifre) → {codice: {colonna_valore: numero|stringa}}.
    Per XLSX: cfg['sheet'] indica il foglio (nome o indice, default 0)."""
    code_col = str(cfg["code_column"])
    zfill = int(cfg.get("code_zfill", 6))
    drop = set(cfg.get("drop_columns", []))
    value_columns = cfg.get("value_columns")
    out: dict[str, dict[str, Any]] = {}

    code_right = int(cfg.get("code_right", 0))

    def _index_row(row: dict[str, Any]) -> None:
        raw_code = str(row.get(code_col) or "").strip()
        if not raw_code:
            return
        if code_right:
            raw_code = raw_code[-code_right:]
        try:
            key = str(int(float(raw_code))).zfill(zfill)
        except ValueError:
            key = raw_code.zfill(zfill)
        cols = value_columns or [c for c in row if c != code_col and c not in drop]
        out[key] = {_slug(c): _to_num(row.get(c)) for c in cols}

    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        import openpyxl
        sheet_id = cfg.get("sheet", 0)
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet_id] if isinstance(sheet_id, str) else wb.worksheets[sheet_id]
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(h or "").strip() for h in next(rows_iter)]
        for vals in rows_iter:
            row = {headers[i]: (str(v).strip() if v is not None else "") for i, v in enumerate(vals) if i < len(headers)}
            _index_row(row)
        wb.close()
    else:
        import csv
        sep = str(cfg.get("sep", ";"))
        skip = int(cfg.get("skip_header_rows", 0))
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for _ in range(skip):
                fh.readline()
            reader = csv.DictReader(fh, delimiter=sep)
            for raw_row in reader:
                row = {(k or "").strip(): v for k, v in raw_row.items() if k is not None}
                _index_row(row)
    return out


def compose_tabular_join(target: str, scope: dict[str, Any]) -> dict[str, Any]:
    """Builder GENERICO: unisce una tabella nazionale (CSV con codice comune
    ISTAT) alla geometria comunale. La configurazione sta nel blocco `tabular`
    del target in composition_targets.yaml. Riusabile per ogni fonte tabellare
    per-comune (AGCOM, IRPEF, ASIA, immobili pubblici, consumo suolo, ...)."""
    cfg = (yaml.safe_load(TARGETS_FILE.read_text("utf-8"))["targets"]
           .get(target, {}).get("tabular"))
    if not cfg:
        return {"target": target, "status": "blocked",
                "message": f"Config 'tabular' assente per {target}."}
    municipalities = _scope_municipalities(scope)
    ente = str(cfg["source_ente"])
    filename = str(cfg["file"])
    base = RAW / "nazionale" / ente
    matches = sorted(base.rglob(filename)) if base.exists() else []
    if not matches:
        return {"target": target, "status": "blocked",
                "message": f"File {filename} non presente: eseguire il Download della fonte {ente}."}
    path = matches[0]
    try:
        by_comune = _tabular_by_comune(path, cfg)
    except Exception as exc:  # noqa: BLE001
        return {"target": target, "status": "blocked",
                "message": f"Lettura tabella {ente} fallita: {exc}"}

    processed_at = _now()
    canonical = str(cfg.get("class") or target.lower())
    output: list[dict[str, Any]] = []
    usable = matched = 0
    for feature in municipalities:
        ap = feature["properties"]
        geom = _valid_geometry(feature.get("geometry"))
        if geom is None:
            continue
        usable += 1
        rec = by_comune.get(str(ap["key"]))
        properties: dict[str, Any] = {
            "codice_istat": ap["key"],
            "comune": ap.get("name"),
            "provincia": ap.get("province"),
            "regione": ap.get("region"),
            "class": canonical,
            "canonical_class": target,
            "source_uuid": cfg.get("source_uuid", f"{ente}:{filename}"),
            "source_title": cfg.get("source_title", ente),
            "source_url": cfg.get("source_url", ""),
            "source_ente": ente,
            "license": cfg.get("license") or "non dichiarata",
            "attribution": cfg.get("attribution", ""),
            "processed_at": processed_at,
            "coverage_status": "tagged" if rec else "senza_dato",
        }
        if rec:
            properties.update(rec)
            matched += 1
        output.append({"type": "Feature", "geometry": mapping(geom), "properties": properties})

    complete = usable > 0 and matched == usable
    coverage = {
        "complete": complete,
        "comuni_totali": usable,
        "comuni_con_dato": matched,
        "fonte": cfg.get("source_title", ente),
    }
    return _write_target(
        target, scope, output,
        [path, ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status="completed" if complete else "partial",
        coverage=coverage,
        diagnostics={"comuni_senza_dato": usable - matched},
    )


def compose_catasto_particelle(scope: dict[str, Any]) -> dict[str, Any]:
    """CATASTO_PARTICELLE: copertura catastale INSPIRE per comune, derivata
    dai file in ITALIA/. Conta i comuni presenti negli zip regionali."""
    from . import catasto_inspire

    region_key = str(scope.get("key", ""))
    regions = catasto_inspire.regions_present()
    region_info = next((r for r in regions if r["region_istat"] == region_key), None)
    if not region_info:
        return {"target": "CATASTO_PARTICELLE", "status": "blocked",
                "message": f"Nessun dato catasto INSPIRE per regione {region_key} (TN-AA = tavolare, non disponibile)."}

    region_zip = Path(region_info["path"])
    comuni_zip = catasto_inspire.list_comuni(region_zip)
    belfiore_set: set[str] = set()
    for name in comuni_zip:
        bel = name.split("_")[0].upper() if "_" in name else name.replace(".zip", "").upper()
        if bel:
            belfiore_set.add(bel)

    mapping_path = ROOT / "registry" / "belfiore_istat.json"
    bel_to_istat: dict[str, str] = {}
    if mapping_path.exists():
        bel_to_istat = json.loads(mapping_path.read_text("utf-8"))

    catasto_istat: set[str] = set()
    for bel in belfiore_set:
        istat = bel_to_istat.get(bel)
        if istat:
            catasto_istat.add(istat)

    cfg = (yaml.safe_load(TARGETS_FILE.read_text("utf-8"))["targets"]
           .get("CATASTO_PARTICELLE", {}).get("catasto_source", {}))
    municipalities = _scope_municipalities(scope)
    processed_at = _now()
    output: list[dict[str, Any]] = []
    matched = usable = 0
    for feature in municipalities:
        ap = feature["properties"]
        geom = _valid_geometry(feature.get("geometry"))
        if geom is None:
            continue
        usable += 1
        has_catasto = str(ap["key"]) in catasto_istat
        properties: dict[str, Any] = {
            "codice_istat": ap["key"],
            "comune": ap.get("name"),
            "provincia": ap.get("province"),
            "regione": ap.get("region"),
            "class": "catasto_particella",
            "canonical_class": "CATASTO_PARTICELLE",
            "source_uuid": cfg.get("source_uuid", "catasto_inspire:fogli_particelle"),
            "source_title": cfg.get("source_title", "Agenzia delle Entrate — Cartografia catastale INSPIRE"),
            "source_url": cfg.get("source_url", ""),
            "source_ente": "catasto_inspire",
            "license": cfg.get("license", "CC BY 4.0"),
            "attribution": cfg.get("attribution", "Agenzia delle Entrate"),
            "processed_at": processed_at,
            "coverage_status": "tagged" if has_catasto else "senza_dato",
            "catasto_presente": has_catasto,
        }
        if has_catasto:
            matched += 1
        output.append({"type": "Feature", "geometry": mapping(geom), "properties": properties})

    coverage = {
        "complete": usable > 0 and matched == usable,
        "comuni_totali": usable,
        "comuni_con_dato": matched,
        "comuni_catasto_zip": len(belfiore_set),
        "comuni_matchati_istat": len(catasto_istat),
        "fonte": cfg.get("source_title", "Catasto INSPIRE"),
    }
    return _write_target(
        "CATASTO_PARTICELLE", scope, output,
        [region_zip, ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status="completed" if coverage["complete"] else "partial",
        coverage=coverage,
        diagnostics={"comuni_senza_match": len(belfiore_set) - len(catasto_istat)},
    )


def compose_trasparenza_appalti(scope: dict[str, Any]) -> dict[str, Any]:
    """TRASPARENZA_APPALTI: ANAC contratti OCDS + BDAP finanziamenti/CUP per comune."""
    municipalities = _scope_municipalities(scope)
    istat_codes = {str(f["properties"]["key"]) for f in municipalities}
    anac_data = _load_cruscotto_section("anac", istat_codes)
    bdap_data = _load_cruscotto_section("bdap_kpi", istat_codes)
    processed_at = _now()
    output: list[dict[str, Any]] = []
    usable = matched = 0
    for feature in municipalities:
        ap = feature["properties"]
        geom = _valid_geometry(feature.get("geometry"))
        if geom is None:
            continue
        usable += 1
        code = str(ap["key"])
        anac = anac_data.get(code)
        bdap = bdap_data.get(code)
        has_data = bool(anac and anac.get("count", 0) > 0) or bool(bdap)
        properties: dict[str, Any] = {
            "codice_istat": ap["key"],
            "comune": ap.get("name"),
            "provincia": ap.get("province"),
            "regione": ap.get("region"),
            "class": "appalto",
            "canonical_class": "TRASPARENZA_APPALTI",
            "source_uuid": "n_cruscotto_italia:anac_ocds+bdap",
            "source_title": "ANAC — BDNCP (OCDS) + BDAP opere pubbliche",
            "source_url": "https://dati.anticorruzione.it/opendata",
            "source_ente": "n_cruscotto_italia",
            "license": "CC BY 4.0",
            "attribution": "ANAC + BDAP — Cruscotto Italia",
            "processed_at": processed_at,
            "coverage_status": "tagged" if has_data else "senza_dato",
        }
        if anac and anac.get("count", 0) > 0:
            properties["n_contratti"] = anac["count"]
            properties["importo_totale"] = anac.get("importo_totale", 0)
            properties["n_cpv_distinti"] = anac.get("distinct_cpv", 0)
            properties["first_award"] = str(anac.get("first_award_date", ""))[:10]
            properties["last_award"] = str(anac.get("last_award_date", ""))[:10]
            for i, cpv in enumerate((anac.get("top_cpv") or anac.get("cpv") or [])[:5], 1):
                properties[f"cpv_{i}_code"] = cpv.get("code", "")
                properties[f"cpv_{i}_desc"] = cpv.get("desc", "")
                properties[f"cpv_{i}_count"] = cpv.get("count", 0)
                properties[f"cpv_{i}_importo"] = cpv.get("importo", 0)
        if bdap and isinstance(bdap, dict):
            tot = bdap.get("totale")
            if isinstance(tot, dict):
                n_prog = tot.get("count", 0)
            elif isinstance(tot, (int, float)):
                n_prog = int(tot)
            else:
                n_prog = 0
            properties["bdap_n_progetti"] = n_prog
            per_stato = bdap.get("per_stato") or {}
            for stato_key in ("ATTIVO", "CHIUSO"):
                st = per_stato.get(stato_key) or {}
                sk = stato_key.lower()
                if st:
                    properties[f"bdap_{sk}_count"] = st.get("count", 0)
                    properties[f"bdap_{sk}_costo_prev"] = st.get("costo_lavori_prev", 0)
                    properties[f"bdap_{sk}_finanz_statali"] = st.get("finanz_statali", 0)
                    properties[f"bdap_{sk}_finanz_europei"] = st.get("finanz_europei", 0)
                    properties[f"bdap_{sk}_finanz_enti_terr"] = st.get("finanz_enti_terr", 0)
                    properties[f"bdap_{sk}_finanz_privati"] = st.get("finanz_privati", 0)
            for i, sett in enumerate((bdap.get("top_settori") or [])[:3], 1):
                properties[f"bdap_settore_{i}"] = sett.get("settore", "")
                properties[f"bdap_settore_{i}_costo"] = sett.get("costo", 0)
        if has_data:
            matched += 1
        output.append({"type": "Feature", "geometry": mapping(geom), "properties": properties})
    coverage = {
        "complete": usable > 0 and matched == usable,
        "comuni_totali": usable,
        "comuni_con_dato": matched,
        "comuni_anac": sum(1 for c in anac_data.values() if c.get("count", 0) > 0),
        "comuni_bdap": len(bdap_data),
        "fonte": "ANAC OCDS + BDAP (cruscotto)",
    }
    return _write_target(
        "TRASPARENZA_APPALTI", scope, output,
        [ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status="completed" if coverage["complete"] else "partial",
        coverage=coverage,
        diagnostics={"comuni_senza_dato": usable - matched},
    )


def _compose_cruscotto_rischi(scope: dict[str, Any]) -> dict[str, Any]:
    """RISCHI_PERICOLOSITA da cruscotto ISPRA IdroGEO: indicatori per-comune di
    pericolosità alluvioni (P1/P2/P3) e frane (P1-P4). Fallback quando non ci
    sono layer GIS regionali riconosciuti."""
    municipalities = _scope_municipalities(scope)
    istat_codes = {str(f["properties"]["key"]) for f in municipalities}
    terr = _load_cruscotto_section("territorio", istat_codes)
    processed_at = _now()
    output: list[dict[str, Any]] = []
    usable = matched = 0
    for feature in municipalities:
        ap = feature["properties"]
        geom = _valid_geometry(feature.get("geometry"))
        if geom is None:
            continue
        usable += 1
        code = str(ap["key"])
        rischio = (terr.get(code) or {}).get("rischio_idrogeologico")
        properties: dict[str, Any] = {
            "codice_istat": ap["key"],
            "comune": ap.get("name"),
            "provincia": ap.get("province"),
            "regione": ap.get("region"),
            "class": "rischio_idrogeologico",
            "canonical_class": "RISCHI_PERICOLOSITA",
            "source_uuid": "n_cruscotto_italia:ispra_idrogeo_pir",
            "source_title": "ISPRA IdroGEO PIR — Mosaicatura pericolosità v5.0 (via Cruscotto Italia)",
            "source_url": "https://idrogeo.isprambiente.it/",
            "source_ente": "n_cruscotto_italia",
            "license": "CC-BY 4.0",
            "attribution": "ISPRA IdroGEO / Cruscotto Italia — dati.gov.it",
            "processed_at": processed_at,
            "coverage_status": "tagged" if rischio else "senza_dato",
        }
        if rischio:
            matched += 1
            alluv = rischio.get("alluvioni", {})
            frane = rischio.get("frane", {})
            properties.update({
                "alluvioni_ar_p3_kmq": alluv.get("ar_p3_kmq"),
                "alluvioni_ar_p2_kmq": alluv.get("ar_p2_kmq"),
                "alluvioni_ar_p1_kmq": alluv.get("ar_p1_kmq"),
                "alluvioni_pop_p3": alluv.get("pop_p3"),
                "alluvioni_pop_p2": alluv.get("pop_p2"),
                "alluvioni_pop_p1": alluv.get("pop_p1"),
                "frane_ar_p3p4_kmq": frane.get("ar_p3p4_kmq"),
                "frane_ar_p3p4_pct": frane.get("ar_p3p4_pct"),
                "frane_pop_p3p4": frane.get("pop_p3p4"),
                "frane_pop_p3p4_pct": frane.get("pop_p3p4_pct"),
                "frane_ed_p3p4": frane.get("ed_p3p4"),
            })
        output.append({"type": "Feature", "geometry": mapping(geom), "properties": properties})

    complete = usable > 0 and matched == usable
    return _write_target(
        "RISCHI_PERICOLOSITA", scope, output,
        [ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status="completed" if complete else "partial",
        coverage={"complete": complete, "comuni_totali": usable,
                  "comuni_con_dato": matched, "fonte": "ISPRA IdroGEO PIR (cruscotto)"},
        diagnostics={"comuni_senza_dato": usable - matched},
    )


def _compose_cruscotto_energia(scope: dict[str, Any]) -> dict[str, Any]:
    """ENERGIA_RETI da cruscotto PUN (GSE): colonnine di ricarica geolocalizzate."""
    municipalities = _scope_municipalities(scope)
    regions = {str(f["properties"]["reg_key"]) for f in municipalities}
    region = next(iter(regions))
    istat_codes = {str(f["properties"]["key"]) for f in municipalities}
    admin_geometries = [_valid_geometry(f["geometry"]) for f in municipalities]
    usable = [(f, g) for f, g in zip(municipalities, admin_geometries) if g is not None]
    admin_features = [pair[0] for pair in usable]
    admin_shapes = [pair[1] for pair in usable]
    tree = STRtree(admin_shapes)
    processed_at = _now()
    output: list[dict[str, Any]] = []
    total_points = 0
    for code in istat_codes:
        data = _load_cruscotto_json(code)
        if not data:
            continue
        pun = data.get("pun")
        if not pun or not pun.get("punti"):
            continue
        for pt in pun["punti"]:
            lat = pt.get("lat")
            lon = pt.get("lon")
            if not lat or not lon:
                continue
            try:
                point = shape({"type": "Point", "coordinates": [float(lon), float(lat)]})
            except Exception:
                continue
            admin = None
            for index in tree.query(point):
                try:
                    if point.intersects(admin_shapes[int(index)]):
                        admin = admin_features[int(index)]
                        break
                except Exception:
                    pass
            if admin is None:
                continue
            ap = admin["properties"]
            total_points += 1
            output.append({
                "type": "Feature",
                "geometry": mapping(point),
                "properties": {
                    "codice_istat": ap["key"],
                    "comune": ap.get("name"),
                    "provincia": ap.get("province"),
                    "regione": ap.get("region"),
                    "class": "ricarica",
                    "canonical_class": "ENERGIA_RETI",
                    "source_uuid": "n_cruscotto_italia:pun_colonnine",
                    "source_title": "GSE — Piattaforma Unica Nazionale colonnine ricarica",
                    "source_url": "https://www.piattaformaunicanazionale.it/",
                    "source_ente": "n_cruscotto_italia",
                    "license": "CC BY 4.0",
                    "attribution": "GSE — PUN (ex art. 52 c.2 D.Lgs 82/2005)",
                    "processed_at": processed_at,
                    "coverage_status": "tagged",
                    "id_evse": pt.get("id_evse"),
                    "cpo": pt.get("cpo"),
                    "stato": pt.get("stato"),
                    "indirizzo": pt.get("indirizzo"),
                },
            })
    status = "completed" if total_points > 0 else "blocked"
    return _write_target(
        "ENERGIA_RETI", scope, output,
        [ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status=status,
        coverage={"punti_ricarica": total_points, "fonte": "GSE PUN (cruscotto)"},
        diagnostics={},
    )


def compose_energia_reti(scope: dict[str, Any]) -> dict[str, Any]:
    """ENERGIA_RETI: prova prima i layer GIS regionali, poi cade sul cruscotto PUN."""
    result = compose_feature_layer("ENERGIA_RETI", scope)
    if result.get("status") != "blocked":
        return result
    return _compose_cruscotto_energia(scope)


def _compose_cruscotto_commercio(scope: dict[str, Any]) -> dict[str, Any]:
    """COMMERCIO_PRODUTTIVO da cruscotto ISTAT ASIA UL: imprese attive e addetti
    per comune, top settori ATECO. Fallback quando non ci sono dati regionali."""
    municipalities = _scope_municipalities(scope)
    istat_codes = {str(f["properties"]["key"]) for f in municipalities}
    asia_data = _load_cruscotto_section("asia", istat_codes)
    processed_at = _now()
    output: list[dict[str, Any]] = []
    usable = matched = 0
    for feature in municipalities:
        ap = feature["properties"]
        geom = _valid_geometry(feature.get("geometry"))
        if geom is None:
            continue
        usable += 1
        code = str(ap["key"])
        asia = asia_data.get(code)
        kpi = (asia or {}).get("kpi", {})
        properties: dict[str, Any] = {
            "codice_istat": ap["key"],
            "comune": ap.get("name"),
            "provincia": ap.get("province"),
            "regione": ap.get("region"),
            "class": "commercio",
            "canonical_class": "COMMERCIO_PRODUTTIVO",
            "source_uuid": "n_cruscotto_italia:istat_asia_ul",
            "source_title": "ISTAT — Archivio Statistico Imprese Attive (ASIA UL, via Cruscotto Italia)",
            "source_url": "https://esploradati.istat.it/databrowser/",
            "source_ente": "n_cruscotto_italia",
            "license": "CC BY 3.0 IT",
            "attribution": "ISTAT ASIA UL / Cruscotto Italia — dati.gov.it",
            "processed_at": processed_at,
            "coverage_status": "tagged" if kpi else "senza_dato",
        }
        if kpi:
            matched += 1
            properties.update({
                "ul_totali": kpi.get("ul_totali"),
                "addetti_totali": kpi.get("addetti_totali"),
                "addetti_per_ul": kpi.get("addetti_per_ul"),
                "ul_yoy_pct": kpi.get("ul_yoy_pct"),
            })
            top = kpi.get("top_settori_ul", [])
            for i, s in enumerate(top[:5]):
                properties[f"top{i+1}_settore"] = s.get("label")
                properties[f"top{i+1}_ul"] = s.get("ul")
        output.append({"type": "Feature", "geometry": mapping(geom), "properties": properties})

    complete = usable > 0 and matched == usable
    return _write_target(
        "COMMERCIO_PRODUTTIVO", scope, output,
        [ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status="completed" if complete else "partial",
        coverage={"complete": complete, "comuni_totali": usable,
                  "comuni_con_dato": matched, "fonte": "ISTAT ASIA UL (cruscotto)"},
        diagnostics={"comuni_senza_dato": usable - matched},
    )


def compose_commercio_produttivo(scope: dict[str, Any]) -> dict[str, Any]:
    """COMMERCIO_PRODUTTIVO: prova prima i layer GIS regionali, poi cade
    sul cruscotto ISTAT ASIA UL."""
    result = compose_feature_layer("COMMERCIO_PRODUTTIVO", scope)
    if result.get("status") != "blocked":
        return result
    return _compose_cruscotto_commercio(scope)


def compose_rischi_pericolosita(scope: dict[str, Any]) -> dict[str, Any]:
    """RISCHI_PERICOLOSITA: prova prima i layer GIS regionali (recognition),
    poi cade sul cruscotto ISPRA per le regioni senza dati spaziali."""
    result = compose_feature_layer("RISCHI_PERICOLOSITA", scope)
    if result.get("status") != "blocked":
        return result
    return _compose_cruscotto_rischi(scope)


def _compose_cruscotto_veicoli(scope: dict[str, Any]) -> dict[str, Any]:
    """MOBILITA_ACCESSIBILITA da cruscotto ACI/ISTAT: parco veicolare per-comune,
    classi euro, incidenti. Fallback quando non ci sono layer GIS regionali."""
    municipalities = _scope_municipalities(scope)
    istat_codes = {str(f["properties"]["key"]) for f in municipalities}
    veicoli_data = _load_cruscotto_section("veicoli", istat_codes)
    processed_at = _now()
    output: list[dict[str, Any]] = []
    usable = matched = 0
    for feature in municipalities:
        ap = feature["properties"]
        geom = _valid_geometry(feature.get("geometry"))
        if geom is None:
            continue
        usable += 1
        code = str(ap["key"])
        veic = veicoli_data.get(code)
        properties: dict[str, Any] = {
            "codice_istat": ap["key"],
            "comune": ap.get("name"),
            "provincia": ap.get("province"),
            "regione": ap.get("region"),
            "class": "mobilita_veicolare",
            "canonical_class": "MOBILITA_ACCESSIBILITA",
            "source_uuid": "n_cruscotto_italia:aci_istat_veicoli",
            "source_title": "ACI/ISTAT — Parco veicolare e incidentalità (via Cruscotto Italia)",
            "source_url": "https://cruscotto-italia.dati.gov.it",
            "source_ente": "n_cruscotto_italia",
            "license": "IODL 2.0",
            "attribution": "ACI / ISTAT / Cruscotto Italia — dati.gov.it",
            "processed_at": processed_at,
            "coverage_status": "tagged" if veic else "senza_dato",
        }
        if veic:
            matched += 1
            parco = veic.get("parco_veicoli", {})
            properties.update({
                "autovetture": parco.get("autovetture"),
                "autobus": parco.get("autobus"),
                "motocicli": parco.get("motocicli"),
                "autocarri": parco.get("autocarri"),
                "popolazione": veic.get("popolazione"),
            })
            euro = parco.get("euro", {})
            if euro:
                properties["euro6_pct"] = euro.get("euro6_pct")
                properties["elettrico_pct"] = euro.get("elettrico_pct")
        output.append({"type": "Feature", "geometry": mapping(geom), "properties": properties})

    complete = usable > 0 and matched == usable
    return _write_target(
        "MOBILITA_ACCESSIBILITA", scope, output,
        [ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status="completed" if complete else "partial",
        coverage={"complete": complete, "comuni_totali": usable,
                  "comuni_con_dato": matched, "fonte": "ACI/ISTAT veicoli (cruscotto)"},
        diagnostics={"comuni_senza_dato": usable - matched},
    )


def compose_mobilita_accessibilita(scope: dict[str, Any]) -> dict[str, Any]:
    """MOBILITA_ACCESSIBILITA: prova prima i layer GIS regionali, poi cade
    sul cruscotto veicoli per le regioni senza dati spaziali."""
    result = compose_feature_layer("MOBILITA_ACCESSIBILITA", scope)
    if result.get("status") != "blocked":
        return result
    return _compose_cruscotto_veicoli(scope)


def _compose_cruscotto_redditi(scope: dict[str, Any]) -> dict[str, Any]:
    """VALORI_OMI fallback da cruscotto MEF Redditi: proxy reddito IRPEF per comune."""
    municipalities = _scope_municipalities(scope)
    istat_codes = {str(f["properties"]["key"]) for f in municipalities}
    redditi_data = _load_cruscotto_section("redditi", istat_codes)
    processed_at = _now()
    output: list[dict[str, Any]] = []
    usable = matched = 0
    for feature in municipalities:
        ap = feature["properties"]
        geom = _valid_geometry(feature.get("geometry"))
        if not geom:
            continue
        istat = str(ap["key"])
        rd = redditi_data.get(istat) or {}
        anni = rd.get("anni_disponibili") or []
        props: dict[str, Any] = {
            "codice_istat": istat,
            "comune": ap["name"],
            "provincia": ap["province"],
            "regione": ap["region"],
            "geometry_granularity": "municipality_overview",
            "source_uuid": "mef:irpef:redditi",
            "source_title": "MEF — Statistiche sulle dichiarazioni IRPEF (proxy OMI)",
            "source_url": rd.get("url_fonte"),
            "processed_at": processed_at,
            "coverage_status": "proxy",
            "disclaimer": "Reddito IRPEF medio come proxy indicativo del mercato immobiliare; non sostituisce le quotazioni OMI.",
        }
        if anni:
            matched += 1
            latest = str(max(anni))
            yr = (rd.get("anni") or {}).get(latest) or {}
            rc = yr.get("reddito_complessivo") or {}
            props.update({
                "anno_redditi": int(latest),
                "contribuenti": yr.get("contribuenti"),
                "reddito_medio": rc.get("medio"),
                "reddito_medio_per_dichiarante": rc.get("medio_per_dichiarante"),
                "reddito_totale": rc.get("tot"),
                "imposta_netta_media": (yr.get("imposta_netta") or {}).get("medio"),
            })
        else:
            props.update({
                "anno_redditi": None,
                "contribuenti": None,
                "reddito_medio": None,
                "reddito_medio_per_dichiarante": None,
                "reddito_totale": None,
                "imposta_netta_media": None,
            })
        usable += 1
        output.append({"type": "Feature", "geometry": mapping(geom), "properties": props})
    return _write_target(
        "VALORI_OMI", scope, output,
        [ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status="partial",
        coverage={
            "municipalities_expected": len(municipalities),
            "municipalities_with_data": matched,
            "geometry_granularity": "municipality_overview",
            "detail": "Proxy reddito IRPEF — download OMI zone completo non ancora eseguito",
        },
    )


def compose_valori_omi(scope: dict[str, Any]) -> dict[str, Any]:
    """VALORI_OMI: prova prima i layer GIS (zone OMI scaricate), poi proxy redditi."""
    result = compose_feature_layer("VALORI_OMI", scope)
    if result.get("status") != "blocked":
        return result
    return _compose_cruscotto_redditi(scope)


# Builder DEDICATI (logica specifica). Tutti gli altri target usano il builder
# generico `compose_feature_layer` via `compose_target`.
COMPOSERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "PIANI_MATURITA": compose_plan_maturity,
    "VINCOLI_COMUNALI": compose_constraints,
    "SEMAFORO_EDIFICABILITA": compose_buildability,
    "DEMOGRAFIA": compose_demografia,
    "CONNETTIVITA_DIGITALE": lambda scope: compose_tabular_join("CONNETTIVITA_DIGITALE", scope),
    "CONSUMO_SUOLO": lambda scope: compose_tabular_join("CONSUMO_SUOLO", scope),
    "AMBIENTE_RIFIUTI": lambda scope: compose_tabular_join("AMBIENTE_RIFIUTI", scope),
    "BENI_CULTURALI": compose_beni_culturali,
    "TURISMO_RICETTIVITA": lambda scope: compose_tabular_join("TURISMO_RICETTIVITA", scope),
    "TRASPARENZA_APPALTI": compose_trasparenza_appalti,
    "CATASTO_PARTICELLE": compose_catasto_particelle,
    "TOPONOMASTICA_CIVICI": lambda scope: compose_tabular_join("TOPONOMASTICA_CIVICI", scope),
    "RISCHI_PERICOLOSITA": compose_rischi_pericolosita,
    "MOBILITA_ACCESSIBILITA": compose_mobilita_accessibilita,
    "ENERGIA_RETI": compose_energia_reti,
    "COMMERCIO_PRODUTTIVO": compose_commercio_produttivo,
    "VALORI_OMI": compose_valori_omi,
}


def compose_target(target: str, scope: dict[str, Any]) -> dict[str, Any]:
    known = yaml.safe_load(TARGETS_FILE.read_text("utf-8")).get("targets", {})
    if target not in known:
        raise ValueError(f"Target di composizione sconosciuto: {target}")
    composer = COMPOSERS.get(target)
    if composer is not None:
        return composer(scope)
    return compose_feature_layer(target, scope)
