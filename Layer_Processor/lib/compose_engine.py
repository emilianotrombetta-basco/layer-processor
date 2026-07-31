"""Motore geometrico dei prodotti finali dello stadio 04.

Il motore lavora soltanto con dati locali già acquisiti. Non colma assenze con
inferenze: se manca un input obbligatorio il target viene dichiarato bloccato,
oppure (per il Semaforo) classificato UNASSESSED.
"""
from __future__ import annotations

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
ADMIN_DIR = WORKSPACE / "Geography_Locations" / "outputs"
CURRENT_MUNICIPALITY_OVERLAYS = {
    "03": ADMIN_DIR / "admin_municipalities_lombardia_current.geojson",
    "05": ADMIN_DIR / "admin_municipalities_veneto_current.geojson",
}
LOMBARDIA_CURRENT_MUNICIPALITIES = CURRENT_MUNICIPALITY_OVERLAYS["03"]
RAW = ROOT / "raw"
WORK = ROOT / "work"
OUT = ROOT / "out"
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
    return json.loads(path.read_text("utf-8"))


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
        reader = shapefile.Reader(str(path), encoding="utf-8")
        field_names = [field[0] for field in reader.fields[1:]]
        for item in reader.iterShapeRecords():
            if not _bbox_intersects(item.shape.bbox, scope_bounds):
                continue
            yield {
                "type": "Feature",
                "geometry": item.shape.__geo_interface__,
                "properties": dict(zip(field_names, item.record)),
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


def _load_admin() -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
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
    return municipalities, provinces, regions


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


def compose_plan_maturity(scope: dict[str, Any]) -> dict[str, Any]:
    municipalities = _scope_municipalities(scope)
    region_keys = {str(f["properties"]["reg_key"]) for f in municipalities}
    if region_keys == {"03"}:
        return _compose_plan_maturity_lombardia(scope, municipalities)
    if region_keys != {"02"}:
        return {
            "target": "PIANI_MATURITA",
            "status": "blocked",
            "message": "Fonte ufficiale dello stato dei piani non ancora configurata per questo territorio.",
        }
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

    # 1) convenzioni storiche a cartelle annidate
    if parts[0] == "r_vda" and len(parts) == 3:
        matches = sorted((RAW / "regione" / "r_vda" / parts[1]).glob(f"{parts[2]}_*.geojson"))
        return matches[0] if matches else None
    if parts[0] == "r_liguria" and len(parts) == 3:
        matches = sorted((RAW / "regione" / "r_liguria").glob(f"{parts[1]}_*/{parts[2]}_*.geojson"))
        return matches[0] if matches else None

    root = _source_root(ente)
    if root is None:
        return None

    # 2) match per uuid nel manifest di download (piemonte_catalog e simili)
    results: list[dict[str, Any]] = []
    manifest = root / "_manifest.json"
    if manifest.exists():
        try:
            data = _read_json(manifest)
            results = data.get("results") or data.get("datasets") or []
        except Exception:
            results = []
        for row in results:
            if str(row.get("uuid") or "") == uuid and row.get("local_path"):
                candidate = root / str(row["local_path"])
                if candidate.exists():
                    return candidate

    # 3) ricostruzione nome file per adapter deterministici
    rest = uuid.split(":", 1)[1] if len(parts) > 1 else ""
    candidate = root / f"{_file_slug(rest)}.geojson"          # wfs_generic
    if candidate.exists():
        return candidate
    glob_matches = sorted(root.glob(f"L{parts[-1]}_*.geojson"))  # arcgis_rest
    if glob_matches:
        return glob_matches[0]

    # 4) ckan_collection: match nel manifest per dataset
    if len(parts) >= 2 and results:
        for row in results:
            if str(row.get("dataset") or "") == parts[1] and row.get("local_path"):
                candidate = root / str(row["local_path"])
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
    output: list[dict[str, Any]] = []
    invalid = 0
    source_failures: list[dict[str, str]] = []
    processed_at = _now()

    for item, path in candidates:
        try:
            data = _read_json(path)
        except Exception as exc:
            source_failures.append({"path": str(path), "reason": str(exc)})
            continue
        canonical = str(item.get("canonical_key") or "")
        severity, effect = _constraint_severity(item)
        source_date = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(
            timespec="seconds"
        )
        for source_feature in data.get("features", []):
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
        },
    )


def compose_buildability(scope: dict[str, Any]) -> dict[str, Any]:
    municipalities = _scope_municipalities(scope)
    regions = {str(f["properties"]["reg_key"]) for f in municipalities}
    if regions != {"02"}:
        return {
            "target": "SEMAFORO_EDIFICABILITA",
            "status": "blocked",
            "message": "Zonizzazione urbanistica non ancora configurata per questo territorio.",
        }
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
    for item in items:
        if item.get("canonical_key") not in wanted_classes:
            continue
        path = _resolve_raw(item)
        if path and path.exists() and path.suffix.lower() in {".geojson", ".shp"}:
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
                properties = {
                    "codice_istat": ap["key"],
                    "comune": ap["name"],
                    "provincia": ap["province"],
                    "regione": ap["region"],
                    "class": canonical,
                    "canonical_class": canonical,
                    "source_uuid": item.get("uuid"),
                    "source_title": item.get("title"),
                    "source_url": item.get("url"),
                    "source_ente": item.get("ente"),
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

    complete = usable > 0 and matched == usable
    coverage = {
        "complete": complete,
        "comuni_totali": usable,
        "comuni_con_dato": matched,
        "fonte": "ISTAT Censimento permanente 2023",
    }
    return _write_target(
        "DEMOGRAFIA",
        scope,
        output,
        [path, ADMIN_DIR / "admin_municipalities.geojson", TARGETS_FILE],
        status="completed" if complete else "partial",
        coverage=coverage,
        diagnostics={"comuni_senza_dato": usable - matched},
    )


# Builder DEDICATI (logica specifica). Tutti gli altri target usano il builder
# generico `compose_feature_layer` via `compose_target`.
COMPOSERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "PIANI_MATURITA": compose_plan_maturity,
    "VINCOLI_COMUNALI": compose_constraints,
    "SEMAFORO_EDIFICABILITA": compose_buildability,
    "DEMOGRAFIA": compose_demografia,
}


def compose_target(target: str, scope: dict[str, Any]) -> dict[str, Any]:
    known = yaml.safe_load(TARGETS_FILE.read_text("utf-8")).get("targets", {})
    if target not in known:
        raise ValueError(f"Target di composizione sconosciuto: {target}")
    composer = COMPOSERS.get(target)
    if composer is not None:
        return composer(scope)
    return compose_feature_layer(target, scope)
