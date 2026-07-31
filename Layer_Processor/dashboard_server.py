#!/usr/bin/env python3
"""Controller HTTP locale per la dashboard del Layer Processor.

Espone una allowlist di processi, una vista territoriale derivata dai GeoJSON
ISTAT locali e lo stato dei job. Ascolta esclusivamente su loopback.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from lib import composition_state  # noqa: E402
WORKSPACE = ROOT.parent
CATALOG = (ROOT / "../Nord/piemonte/_catalog.csv").resolve()
RECOGNITION_DIR = ROOT / "work/recognition"
PROPOSALS_DIR = ROOT / "work/proposals"
SCOPED_CATALOG_DIR = ROOT / "work/catalog_scopes"
JOB_HISTORY_DIR = ROOT / "work/jobs"
TAXONOMY = ROOT / "registry/canonical_taxonomy.yaml"
DICTIONARY = ROOT / "registry/layer_dictionary.yaml"
COMPOSITION_TARGETS = ROOT / "registry/composition_targets.yaml"
SOURCES = ROOT / "registry/sources.yaml"
OUT = ROOT / "out"
ADMIN_DIR = WORKSPACE / "Geography_Locations/outputs"
ADMIN_FILES = {
    "region": ADMIN_DIR / "admin_regions.geojson",
    "province": ADMIN_DIR / "admin_provinces.geojson",
    "municipality": ADMIN_DIR / "admin_municipalities.geojson",
}
CURRENT_MUNICIPALITY_OVERLAYS = {
    "03": ADMIN_DIR / "admin_municipalities_lombardia_current.geojson",
    "05": ADMIN_DIR / "admin_municipalities_veneto_current.geojson",
}

STAGE_DEFINITIONS = [
    {
        "id": "discover",
        "number": "01",
        "name": "Scoperta fonti",
        "description": "Trova gli endpoint dei dataset per il territorio scelto.",
        "available": False,
        "status": "catalogo_mancante",
        "output": "Catalogo delle fonti",
    },
    {
        "id": "download",
        "number": "02",
        "name": "Download",
        "description": "Scarica i dati grezzi e registra i file disponibili.",
        "available": False,
        "status": "catalogo_mancante",
        "output": "File grezzi e manifest",
    },
    {
        "id": "recognize",
        "number": "03",
        "name": "Riconoscimento",
        "description": "Associa ogni dataset a una classe canonica.",
        "available": True,
        "status": "pronto",
        "output": "Layer riconosciuti e proposte",
    },
    {
        "id": "compose",
        "number": "04",
        "name": "Composizione",
        "description": "Produce i layer cartografici finali con fonti e motivazioni.",
        "available": False,
        "status": "obiettivo_definito",
        "output": "",
    },
    {
        "id": "load",
        "number": "05",
        "name": "Caricamento",
        "description": "Esegue dry-run e promozione controllata su Supabase.",
        "available": False,
        "status": "richiede_approvazione",
        "output": "Dati pubblicati",
    },
]

# I cataloghi disponibili oggi. I prefissi sono una compatibilità esplicita con
# il catalogo pilota, nel quale Torino usa ancora c_l219 e la Città
# Metropolitana usa cmto.
SCOPE_RUNNERS: dict[tuple[str, str], dict[str, Any]] = {
    ("region", "01"): {
        "ente": "r_piemon",
        "label": "Piemonte",
        "prefixes": None,
        "catalog": ROOT / "work" / "catalog" / "r_piemon.csv",
    },
    ("region", "02"): {
        "ente": "r_vda",
        "label": "Valle d'Aosta",
        "prefixes": None,
        "catalog": ROOT / "work" / "catalog" / "r_vda.csv",
        # Nessun `compose_targets`: dopo l'introduzione del builder generico
        # (compose_engine.compose_feature_layer) TUTTI i layer finali sono
        # componibili in modo uniforme, non solo i 3 con builder dedicato.
    },
    ("region", "03"): {
        "ente": "r_lombar",
        "label": "Lombardia",
        "prefixes": None,
        "catalog": ROOT / "work" / "catalog" / "r_lombar.csv",
        "compose_available": True,
        "compose_targets": ["PIANI_MATURITA"],
    },
    ("region", "04"): {
        "ente": "r_tn_pup",
        "label": "Trentino-Alto Adige",
        "prefixes": None,
        "catalog": ROOT / "work" / "catalog" / "r_tn_pup.csv",
        # Regione multi-entità (Trento PUP/pericolosità/POI + Bolzano
        # piani/geologia/idrologia/pericoli). r_tn_prguso è escluso: solo-WMS,
        # non scaricabile (richiesta PRGUSO alla PAT ancora pendente).
        # Nessun `compose_targets`: builder generico → tutti i layer finali.
    },
    ("region", "05"): {
        "ente": "r_veneto",
        "label": "Veneto",
        "prefixes": None,
        "catalog": ROOT / "work" / "catalog" / "r_veneto.csv",
    },
    ("region", "06"): {
        "ente": "r_fvg_ppr",
        "label": "Friuli-Venezia Giulia",
        "prefixes": None,
        "catalog": ROOT / "work" / "catalog" / "r_fvg_ppr.csv",
        # Regione multi-entità (IRDAT: PPR + siti protetti + zone vincolate).
        # Statuto speciale senza province. PRGC comunali (Eagle-FVG) e PAI
        # (Autorità di Bacino Alpi Orientali) = onboarding separati, da aggiungere.
    },
    ("region", "07"): {
        "ente": "r_liguria",
        "label": "Liguria",
        "prefixes": None,
        "catalog": ROOT / "work" / "catalog" / "r_liguria.csv",
    },
    ("region", "08"): {
        "ente": "r_emilia_romagna_pug",
        "label": "Emilia-Romagna",
        "prefixes": None,
        "catalog": ROOT / "work" / "catalog" / "r_emilia_romagna_pug.csv",
    },
    ("province", "001"): {
        "ente": "p_to",
        "label": "Torino",
        "prefixes": None,
        "catalog": ROOT / "work" / "catalog" / "p_to.csv",
    },
    ("province", "096"): {
        "ente": "p_bi",
        "label": "Biella",
        "prefixes": ("p_bi:",),
    },
    ("municipality", "001272"): {
        "ente": "c_001272",
        "label": "Torino",
        "prefixes": None,
        "catalog": ROOT / "work" / "catalog" / "c_001272.csv",
    },
}

SCOPE_PIPELINES = {
    ("region", "01"): {"source": "r_piemon", "label": "Piemonte"},
    ("region", "02"): {"source": "r_vda", "label": "Valle d'Aosta"},
    ("region", "03"): {
        "source": "r_lombar",
        "sources": ["r_lombar", "r_lombar_pgtweb", "r_lombar_ptm"],
        "label": "Lombardia",
    },
    ("region", "04"): {
        "source": "r_tn_pup",
        "sources": [
            "r_tn_pup", "r_tn_pericolosita", "r_tn_servizi_valli",
            "r_bz_piani", "r_bz_piani_gvcc", "r_bz_pericoli",
            "r_bz_geologia", "r_bz_idrologia",
        ],
        "label": "Trentino-Alto Adige",
    },
    ("region", "05"): {"source": "r_veneto", "label": "Veneto"},
    ("region", "06"): {
        "source": "r_fvg_ppr",
        "sources": ["r_fvg_ppr", "r_fvg_siti_prot", "r_fvg_zone_vinc"],
        "label": "Friuli-Venezia Giulia",
    },
    ("region", "07"): {"source": "r_liguria", "label": "Liguria"},
    ("region", "08"): {
        "source": "r_emilia_romagna_pug",
        "sources": [
            "r_emilia_romagna_pug",
            "r_emilia_romagna_psc",
            "p_bo_ptcp_tutele",
            "p_fe_ptcp_tutele",
            "p_fc_ptcp_tutele",
            "p_mo_ptcp_tutele",
            "p_pr_ptcp_tutele",
            "p_pc_ptcp_tutele",
            "p_ra_ptcp_tutele",
            "p_re_ptcp_tutele",
        ],
        "label": "Emilia-Romagna",
    },
    ("province", "001"): {"source": "p_to", "label": "Città metropolitana di Torino"},
    ("municipality", "001272"): {"source": "c_001272", "label": "Comune di Torino"},
}

REGION_PIPELINES = {
    key: value
    for (level, key), value in SCOPE_PIPELINES.items()
    if level == "region"
}

_ADMIN_CACHE: dict[str, dict[str, Any]] = {}


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def modified_at(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()


@lru_cache(maxsize=1)
def sources_config() -> dict[str, Any]:
    return yaml.safe_load(SOURCES.read_text("utf-8")) if SOURCES.exists() else {}


def _source_by_key(key: str) -> dict[str, Any]:
    for source in sources_config().get("sources", []):
        if source.get("key") == key:
            return source
    raise RuntimeError(f"Fonte non configurata: {key}")


def _raw_manifest_path(source_key: str) -> Path:
    source = _source_by_key(source_key)
    return ROOT / "raw" / str(source.get("livello") or "regione") / source_key / "_manifest.json"


def admin_geojson(level: str) -> dict[str, Any]:
    paths = [ADMIN_FILES[level]]
    if level == "municipality":
        paths.extend(path for path in CURRENT_MUNICIPALITY_OVERLAYS.values() if path.exists())
    signature = tuple((str(path), path.stat().st_mtime_ns) for path in paths if path.exists())
    cached = _ADMIN_CACHE.get(level)
    if not cached or cached.get("_signature") != signature:
        data = read_json(ADMIN_FILES[level], {"type": "FeatureCollection", "features": []})
        if level == "municipality":
            for region_key, overlay_path in CURRENT_MUNICIPALITY_OVERLAYS.items():
                if not overlay_path.exists():
                    continue
                current = read_json(
                    overlay_path,
                    {"type": "FeatureCollection", "features": []},
                )
                data["features"] = [
                    feature
                    for feature in data.get("features", [])
                    if str(feature.get("properties", {}).get("reg_key")) != region_key
                ] + list(current.get("features", []))
        # Le mappe di regione e provincia vengono semplificate soltanto per la
        # visualizzazione; i GeoJSON sorgente non sono modificati.
        if level in {"region", "province"}:
            tolerance = 0.005 if level == "region" else 0.0035
            try:
                from shapely.geometry import mapping, shape

                for feature in data.get("features", []):
                    feature["geometry"] = mapping(
                        shape(feature["geometry"]).simplify(
                            tolerance, preserve_topology=True
                        )
                    )
            except ImportError:
                pass
        _ADMIN_CACHE[level] = {"_signature": signature, "data": data}
    return _ADMIN_CACHE[level]["data"]


@lru_cache(maxsize=1)
def source_index() -> dict[str, Any]:
    config = sources_config()
    rows = config.get("sources", [])
    by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_province: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_municipality: dict[str, list[dict[str, Any]]] = defaultdict(list)
    national = []
    for row in rows:
        if row.get("livello") == "nazionale":
            national.append(row)
            continue
        region_key = str(row.get("region_istat") or "")
        province_key = str(row.get("province_istat") or "")
        municipality_key = str(row.get("comune_istat") or "")
        if region_key:
            by_region[region_key].append(row)
        if province_key:
            by_province[province_key].append(row)
        if municipality_key:
            by_municipality[municipality_key].append(row)
    return {
        "config": config,
        "by_region": by_region,
        "by_province": by_province,
        "by_municipality": by_municipality,
        "national": national,
    }


@lru_cache(maxsize=1)
def territory_counts() -> dict[str, Any]:
    provinces = admin_geojson("province").get("features", [])
    municipalities = admin_geojson("municipality").get("features", [])
    provinces_by_region: dict[str, int] = defaultdict(int)
    municipalities_by_region: dict[str, int] = defaultdict(int)
    municipalities_by_province: dict[str, int] = defaultdict(int)
    for feature in provinces:
        provinces_by_region[str(feature["properties"]["reg_key"])] += 1
    for feature in municipalities:
        props = feature["properties"]
        municipalities_by_region[str(props["reg_key"])] += 1
        municipalities_by_province[str(props["prov_key"])] += 1
    return {
        "provinces_by_region": provinces_by_region,
        "municipalities_by_region": municipalities_by_region,
        "municipalities_by_province": municipalities_by_province,
    }


def compact_source(row: dict[str, Any]) -> dict[str, Any]:
    source_key = str(row.get("key") or "")
    adapter = str(row.get("adapter") or "")
    catalog_manifest = read_json(
        ROOT / "work" / "catalog" / f"{source_key}_services.json",
        {},
    )
    raw_manifest = read_json(_raw_manifest_path(source_key), {}) if source_key else {}
    expected = int(
        catalog_manifest.get("downloadable_count")
        or catalog_manifest.get("inventory_count")
        or row.get("expected_map_count")
        or row.get("expected_service_count")
        or row.get("expected_dataset_count")
        or len(catalog_manifest.get("layers", []))
        or len(catalog_manifest.get("datasets", []))
        or 0
    )
    downloaded = int(raw_manifest.get("layers_downloaded", 0) or 0)
    formats = {
        "arcgis_rest": "GeoJSON",
        "socrata": "JSON",
        "websit_xml": "Shapefile ZIP",
        "wfs_generic": "GeoJSON",
        "ckan_collection": "GeoJSON",
        "ckan_mit": "risorsa originale",
        "piemonte_catalog": "risorsa originale",
        "vda_platform": "GeoJSON",
        "vda_local": "GeoJSON",
        "vda_sct": "GeoJSON",
        "liguria_geoportal": "GeoJSON / ZIP",
        "veneto_webgis": "GeoJSON",
        "emilia_romagna_moka": "GeoJSON",
        "local_spatial": "GeoJSON / Shapefile locale",
        "csv_direct": "CSV",
        "http_download": "file (zip/csv/xlsx)",
        "html_resources": "CSV/ZIP da pagina",
        "istat_sdmx": "SDMX-CSV",
    }
    executable_adapters = set(formats)
    is_executable = adapter in executable_adapters and row.get("status") == "active"
    level = str(row.get("livello") or "regione")
    return {
        "key": source_key,
        "name": row.get("ente"),
        "url": row.get("url"),
        "data_url": row.get("data_url"),
        "level": level,
        "status": row.get("status"),
        "kind": row.get("kind"),
        "adapter": adapter,
        "data_format": row.get("data_format") or formats.get(adapter) or "da verificare",
        "expected_datasets": expected,
        "downloaded_datasets": downloaded,
        "download_status": raw_manifest.get("status"),
        "batch_size": int(row.get("dashboard_batch_size") or 0),
        "download_available": is_executable,
        "resumable": is_executable,
        "raw_path": f"raw/{level}/{source_key}/" if source_key else None,
        "discover_command": (
            f"python3 run.py discover --source {source_key} --progress"
            if is_executable
            else None
        ),
        "download_command": (
            "python3 run.py download "
            f"--source {source_key}"
            + (
                f" --max-services {int(row.get('dashboard_batch_size') or 0)}"
                if int(row.get("dashboard_batch_size") or 0)
                else ""
            )
            + " --progress"
            if is_executable
            else None
        ),
        "plan_types": row.get("plan_types", []),
        "planning_instruments": row.get("planning_instruments", []),
        "notes": row.get("notes"),
        "links": row.get("links", []),
    }


def _territory_properties(level: str, key: str) -> dict[str, Any]:
    for feature in admin_geojson(level).get("features", []):
        props = feature.get("properties") or {}
        if str(props.get("key")) == key:
            return props
    raise ValueError("Territorio non trovato.")


def _check_url(url: str, timeout: int = 7) -> dict[str, Any]:
    """Verifica un singolo link: 2xx/3xx = ok. HEAD, con fallback a GET se bloccato.
    Usa un contesto TLS permissivo: diversi server gov.it rifiutano l'handshake
    di default di Python e darebbero falsi 'offline'."""
    import ssl
    import urllib.error
    import urllib.request

    ctx = ssl.create_default_context()
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass

    def _try(method: str) -> dict[str, Any]:
        req = urllib.request.Request(url, method=method,
                                     headers={"User-Agent": "Mozilla/5.0 (LayerProcessor-health)"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return {"http": r.status, "ok": True}

    try:
        return _try("HEAD")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 405, 406, 501):  # HEAD non ammesso → riprova GET
            try:
                return _try("GET")
            except Exception as exc2:  # noqa: BLE001
                return {"http": getattr(exc2, "code", None), "ok": False, "error": str(exc2)[:120]}
        return {"http": exc.code, "ok": exc.code < 400, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"http": None, "ok": False, "error": type(exc).__name__}


def _source_check_urls(s: dict[str, Any]) -> list[tuple[str, str]]:
    """Link da verificare per una fonte: portale + endpoint dati (quando noto)."""
    urls: list[tuple[str, str]] = []
    if s.get("url"):
        urls.append(("portale", str(s["url"])))
    if s.get("kind") == "ckan" and s.get("ckan_api") and s.get("ckan_dataset"):
        urls.append(("dati", f"{s['ckan_api']}/package_show?id={s['ckan_dataset']}"))
    elif s.get("key") == "n_omi" and s.get("api_base"):
        urls.append(("dati", f"{s['api_base']}zoneomi.php?richiesta=1"))
    elif s.get("adapter") == "vda_platform" and s.get("public_services"):
        urls.append(("dati", f"{s.get('proxy', '')}{s['public_services']}?f=json"))
    elif s.get("adapter") == "csv_direct" and s.get("csv_datasets"):
        urls.append(("dati", str(s["csv_datasets"][0].get("url") or "")))
    elif s.get("adapter") == "http_download" and s.get("download_items"):
        urls.append(("dati", str(s["download_items"][0].get("url") or "")))
    elif s.get("adapter") == "html_resources" and s.get("html_resources"):
        urls.append(("dati", str(s["html_resources"][0].get("page") or "")))
    elif s.get("adapter") == "arcgis_rest":
        for service in s.get("arcgis_services", []):
            if service.get("service"):
                urls.append(
                    (
                        str(service.get("key") or "dati"),
                        f"{str(service['service']).rstrip('/')}?f=json",
                    )
                )
    elif s.get("adapter") == "socrata" and s.get("socrata_endpoint"):
        urls.append(
            (
                "api_socrata",
                f"{s['socrata_endpoint']}?$select=count(*)",
            )
        )
    elif s.get("adapter") == "websit_xml" and s.get("catalog_xml"):
        urls.append(("catalogo_xml", str(s["catalog_xml"])))
    elif s.get("adapter") == "veneto_webgis" and s.get("wfs_url"):
        urls.append(
            (
                "wfs",
                f"{str(s['wfs_url']).rstrip('?')}?service=WFS&version=2.0.0&request=GetCapabilities",
            )
        )
        if s.get("viewer_config_url"):
            for viewer in s.get("webgis", []):
                urls.append(
                    (
                        f"webgis_{viewer.get('id')}",
                        f"{s['viewer_config_url']}?webgisId={viewer.get('id')}",
                    )
                )
    return urls


def sources_health() -> dict[str, Any]:
    """Health check di tutti i link delle fonti (portale + endpoint dati)."""
    import concurrent.futures

    srcs = sources_config().get("sources", [])

    def check_one(s: dict[str, Any]) -> dict[str, Any]:
        checks = [{"label": lbl, "url": u, **_check_url(u)} for lbl, u in _source_check_urls(s)]
        if not checks:
            status = "senza_link"
        elif all(c["ok"] for c in checks):
            status = "ok"
        elif any(c["ok"] for c in checks):
            status = "degradato"  # portale ok ma un endpoint dati non risponde (o viceversa)
        else:
            status = "errore"
        return {"key": s.get("key"), "ente": s.get("ente"), "status": status, "checks": checks}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check_one, srcs))
    return {
        "checked_at": datetime.now().astimezone().isoformat(),
        "total": len(results),
        "ok": sum(r["status"] == "ok" for r in results),
        "degradato": sum(r["status"] == "degradato" for r in results),
        "errore": sum(r["status"] == "errore" for r in results),
        "sources": results,
    }


def _source_key_from_path(path: str) -> str | None:
    """Ricava la chiave fonte dal percorso del file grezzo (raw/<livello>/<key>/…)."""
    p = str(path).replace("\\", "/")
    if "/raw/" in p:
        parts = p.split("/raw/", 1)[1].split("/")
        if len(parts) >= 2:
            return parts[1]
    if "Geography_Locations" in p or "Geography_Amministrativi" in p:
        return "geografia_istat"
    return None


def layer_provenance(target: str, scope: dict[str, str]) -> dict[str, Any]:
    """Provenienza di un layer finale: risale ai dati ORIGINALI (file grezzi + fonte
    nel registry + layer per-feature). Interno, disponibile su richiesta."""
    terr = str(scope.get("key") or "")
    manifest = OUT / target / f"{terr}.manifest.json"
    geojson = OUT / target / f"{terr}.geojson"
    if not manifest.exists() and not geojson.exists():
        return {"target": target, "territory": terr, "available": False,
                "message": "Layer non ancora composto per questo territorio."}
    m = read_json(manifest, {})
    raw_sources = []
    for s in m.get("sources", []):
        if "/registry/" in str(s.get("path", "")).replace("\\", "/"):
            continue  # file di configurazione, non dati originali
        key = _source_key_from_path(s.get("path", ""))
        src = None
        if key and key != "geografia_istat":
            try:
                src = _source_by_key(key)
            except RuntimeError:
                src = None
        raw_sources.append({
            "path": s.get("path"),
            "fingerprint": s.get("fingerprint"),
            "source_key": key,
            "ente": (src or {}).get("ente")
                    or ("Geografia amministrativa ISTAT" if key == "geografia_istat" else None),
            "portale": (src or {}).get("url") if src else None,
        })
    # layer per-feature (source_uuid distinti) dal GeoJSON prodotto
    layer_sources: dict[str, Any] = {}
    g = read_json(geojson, {})
    for f in (g.get("features") or [])[:50000]:
        p = f.get("properties", {}) or {}
        uid = p.get("source_uuid")
        if uid and uid not in layer_sources:
            layer_sources[uid] = {
                "source_uuid": uid,
                "source_title": p.get("source_title"),
                "source_url": p.get("source_url"),
                "source_date": p.get("source_date"),
            }
    return {
        "target": target, "territory": terr, "available": True,
        "composed_at": m.get("composed_at"), "features": m.get("features"),
        "coverage": m.get("coverage"),
        "raw_sources": raw_sources,
        "layer_sources": list(layer_sources.values()),
    }


def sources_payload(scope: dict[str, str]) -> dict[str, Any]:
    level = scope.get("level", "region")
    key = str(scope.get("key") or "")
    if level not in ADMIN_FILES:
        raise ValueError("Livello territoriale non valido.")

    props = _territory_properties(level, key)
    region_key = key if level == "region" else str(props.get("reg_key") or "")
    province_key = key if level == "province" else str(props.get("prov_key") or "")
    index = source_index()
    selected: list[tuple[dict[str, Any], str]] = []

    level_rank = {"nazionale": 0, "regione": 1, "provincia": 2, "comune": 3}
    scope_rank = {"region": 1, "province": 2, "municipality": 3}[level]

    def relationship(row: dict[str, Any]) -> str:
        row_level = str(row.get("livello") or "")
        if row_level == "nazionale":
            return "nazionale"
        row_rank = level_rank.get(row_level, scope_rank)
        if row_rank == scope_rank:
            return "diretta"
        return "sovraordinata" if row_rank < scope_rank else "locale"

    selected.extend((row, relationship(row)) for row in index["national"])
    region_rows = index["by_region"].get(region_key, [])
    if level != "region":
        region_rows = [row for row in region_rows if row.get("livello") == "regione"]
    selected.extend((row, relationship(row)) for row in region_rows)
    if province_key:
        province_rows = index["by_province"].get(province_key, [])
        if level == "municipality":
            province_rows = [
                row for row in province_rows if row.get("livello") == "provincia"
            ]
        selected.extend((row, relationship(row)) for row in province_rows)
    if level == "municipality":
        selected.extend(
            (row, relationship(row)) for row in index["by_municipality"].get(key, [])
        )

    sources = []
    seen: set[str] = set()
    for row, relationship in selected:
        source_key = str(row.get("key") or "")
        if not source_key or source_key in seen:
            continue
        seen.add(source_key)
        sources.append({**compact_source(row), "relationship": relationship})

    status_counts = defaultdict(int)
    for source in sources:
        status_counts[str(source.get("status") or "unknown")] += 1
    return {
        "scope": scope,
        "total": len(sources),
        "active": status_counts["active"],
        "status_counts": dict(status_counts),
        "sources": sources,
    }


def final_layer_count(level: str, key: str) -> int:
    return len(final_layer_paths(level, key))


def final_layer_paths(level: str, key: str) -> list[Path]:
    if not OUT.exists():
        return []
    candidates = {
        key,
        f"r_{key}",
        f"p_{key}",
        f"c_{key}",
        f"region_{key}",
        f"province_{key}",
        f"municipality_{key}",
    }
    runner = SCOPE_RUNNERS.get((level, key))
    if runner:
        candidates.add(str(runner["ente"]))
    paths = []
    for path in OUT.glob("*/*.geojson"):
        if path.stem in candidates:
            paths.append(path)
    return sorted(paths)


def _csv_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except OSError:
        return 0


_PUBLISHER_ALIASES = {
    "mim": "MIUR", "miur": "MIUR", "mit": "MIT", "istat": "ISTAT",
    "ispra": "ISPRA", "mef": "MEF", "mic": "MIC — Cultura",
    "iccd-mic": "MIC — Cultura", "agcom": "AGCOM", "anac": "ANAC",
    "aci": "ACI", "mimit": "MIMIT",
    "ministero della salute": "Ministero della Salute",
    "agenzia delle entrate": "Agenzia delle Entrate",
    "ministero del lavoro e delle politiche sociali": "Ministero del Lavoro",
    "ministero del lavoro": "Ministero del Lavoro",
    "piattaforma unica nazionale": "PUN — Ricarica elettrica",
    "humanitarian openstreetmap team": "OpenStreetMap / HOTOSM",
}


def _publisher(source: dict[str, Any]) -> str:
    """Ente editore di una fonte, ricavato da `ente` (testo prima del trattino
    lungo). I portali .gov generici senza editore chiaro → 'OpenData Governo'."""
    ente = str(source.get("ente") or "").strip()
    head = re.split(r"\s[—–]\s", ente, maxsplit=1)[0].strip()
    head = re.split(r"\s*\(", head, maxsplit=1)[0].strip()        # via "(MIUR)"
    head = re.split(r"\s*[/+]\s*", head, maxsplit=1)[0].strip()   # "AE + ISTAT" → AE
    low = head.lower()
    if low in _PUBLISHER_ALIASES:
        return _PUBLISHER_ALIASES[low]
    if low.startswith("istat"):          # "ISTAT Demografia" → ISTAT
        return "ISTAT"
    if not head or low.startswith("database") or "dati.gov.it" in ente.lower():
        return "OpenData Governo"
    return head


def sources_catalog() -> dict[str, Any]:
    """Tutte le fonti raggruppate per ENTE EDITORE (categoria): molte voci sono
    dataset dello stesso ente (MIT, ISTAT, ISPRA…). Ogni categoria è collassabile
    e contiene i dataset con i rispettivi link. Alimenta la sezione 'Fonti'."""
    srcs = sources_config().get("sources", [])
    groups: dict[str, dict[str, Any]] = {}
    for row in srcs:
        compact = compact_source(row)
        publisher = _publisher(row)
        key = re.sub(r"[^a-z0-9]+", "-", publisher.lower()).strip("-") or "altro"
        livello = str(row.get("livello") or "regione")
        group = groups.setdefault(key, {
            "key": key, "name": publisher, "livelli": set(),
            "icon_url": None, "sources": [],
        })
        group["livelli"].add(livello)
        if not group["icon_url"] and row.get("url"):
            group["icon_url"] = row.get("url")
        group["sources"].append({
            **compact,
            "region": row.get("region"),
            "region_istat": row.get("region_istat"),
            "livello": livello,
            "feeds_target": row.get("feeds_target"),
            "managed_by": row.get("managed_by"),
            "proposed_adapter": row.get("proposed_adapter"),
        })

    for group in groups.values():
        group["sources"].sort(key=lambda s: (
            0 if s.get("download_available") else 1, str(s.get("key")),
        ))
        group["total"] = len(group["sources"])
        group["downloadable"] = sum(
            1 for s in group["sources"] if s.get("download_available")
        )
        group["livello"] = "nazionale" if "nazionale" in group["livelli"] else "regione"
        group.pop("livelli", None)

    def _sort(group: dict[str, Any]) -> tuple[int, int, str]:
        # Nazionali prima, poi per numero di dataset (i "ripetuti" in alto), poi nome.
        return (
            0 if group["livello"] == "nazionale" else 1,
            -group["total"],
            group["name"].lower(),
        )

    ordered = sorted(groups.values(), key=_sort)
    return {
        "groups": ordered,
        "total_sources": sum(group["total"] for group in ordered),
        "downloadable_sources": sum(group["downloadable"] for group in ordered),
        "categories": len(ordered),
    }


def source_check(key: str) -> dict[str, Any]:
    """Controllo disponibilità di UNA fonte (portale + endpoint dati)."""
    source = _source_by_key(key)
    checks = [
        {"label": lbl, "url": url, **_check_url(url)}
        for lbl, url in _source_check_urls(source)
    ]
    if not checks:
        status = "senza_link"
    elif all(c["ok"] for c in checks):
        status = "ok"
    elif any(c["ok"] for c in checks):
        status = "degradato"
    else:
        status = "errore"
    return {"key": key, "status": status, "checks": checks,
            "checked_at": datetime.now().astimezone().isoformat()}


def _manifest_errors(data: dict[str, Any]) -> list[str]:
    """Estrae messaggi leggibili dai diversi manifest degli adapter."""
    errors: list[str] = []
    for key in ("failures", "missing_services", "missing_maps"):
        for item in data.get(key, []) or []:
            if isinstance(item, dict):
                label = (
                    item.get("layer_name")
                    or item.get("title")
                    or item.get("service")
                    or item.get("map")
                    or item.get("id")
                    or key
                )
                reason = (
                    item.get("error")
                    or item.get("reason")
                    or item.get("message")
                    or "errore non specificato"
                )
                errors.append(f"{label}: {reason}")
            else:
                errors.append(str(item))
    for item in data.get("results", []) or []:
        if not isinstance(item, dict) or item.get("status") != "failed":
            continue
        label = item.get("layer_name") or item.get("title") or item.get("uuid") or "layer"
        reason = item.get("error") or item.get("reason") or "errore non specificato"
        errors.append(f"{label}: {reason}")
    return errors


def region_pipeline_progress(region_key: str) -> dict[str, Any]:
    """Percentuale rigorosa dei cinque stadi per una regione.

    Ogni stadio vale 20 punti e diventa completo soltanto quando il suo
    artefatto conclusivo prova che tutto lo scope regionale è stato elaborato.
    """
    runner = SCOPE_RUNNERS.get(("region", region_key))
    if not runner:
        steps = [
            {"id": item["id"], "number": item["number"], "name": item["name"],
             "complete": False, "detail": "Regione non ancora configurata"}
            for item in STAGE_DEFINITIONS
        ]
        return {"percentage": 0, "completed_steps": 0, "total_steps": 5, "steps": steps}

    source_key = str(runner["ente"])
    pipeline = SCOPE_PIPELINES.get(("region", region_key)) or {}
    source_keys = list(pipeline.get("sources") or [source_key])
    catalogs = [
        Path(runner.get("catalog"))
        if key == source_key and runner.get("catalog")
        else ROOT / "work" / "catalog" / f"{key}.csv"
        for key in source_keys
    ]
    discovery_manifests = [
        ROOT / "work" / "catalog" / f"{key}_services.json"
        for key in source_keys
    ]
    discoveries = [read_json(path, {}) for path in discovery_manifests]
    raw_manifests = [_raw_manifest_path(key) for key in source_keys]

    catalog_total = sum(_csv_row_count(path) for path in catalogs)
    discovery_failures = sum(
        len(discovery.get("failures", []) or [])
        + len(discovery.get("missing_services", []) or [])
        for discovery in discoveries
    )
    discover_complete = bool(
        catalog_total
        and all(path.exists() for path in discovery_manifests)
        and not discovery_failures
        and all(discovery.get("auth_required") is not True for discovery in discoveries)
    )

    downloads = [read_json(path, {}) for path in raw_manifests]
    downloaded = sum(int(item.get("layers_downloaded", 0) or 0) for item in downloads)
    download_failed = sum(int(item.get("layers_failed", 0) or 0) for item in downloads)
    expected_downloads = sum(
        int(
            discovery.get("downloadable_count")
            or discovery.get("downloadable_layers")
            or _csv_row_count(catalog)
        )
        for discovery, catalog in zip(discoveries, catalogs)
    )
    download_complete = bool(
        expected_downloads
        and all(path.exists() for path in raw_manifests)
        and downloaded >= expected_downloads
        and not download_failed
        and all(
            item.get("status") in {"completed", "batch_completed"}
            for item in downloads
        )
    )

    recognition_paths = [RECOGNITION_DIR / f"{key}.json" for key in source_keys]
    proposal_paths = [PROPOSALS_DIR / f"{key}.json" for key in source_keys]
    processed = sum(
        int(read_json(recognition, {}).get("count", 0) or 0)
        + int(read_json(proposal, {}).get("count", 0) or 0)
        for recognition, proposal in zip(recognition_paths, proposal_paths)
    )
    recognize_complete = bool(
        catalog_total
        and all(path.exists() for path in recognition_paths)
        and processed >= catalog_total
    )

    target_config = (
        yaml.safe_load(COMPOSITION_TARGETS.read_text("utf-8"))
        if COMPOSITION_TARGETS.exists()
        else {}
    )
    # I target `planned: true` sono destinazioni dichiarate ma non ancora
    # alimentate (adapter fonte da costruire): non concorrono alla completezza
    # della composizione, altrimenti nessuna regione risulterebbe mai "completa".
    target_keys = [
        name
        for name, spec in (target_config.get("targets") or {}).items()
        if not (spec or {}).get("planned")
    ]
    compose_manifests = [
        read_json(OUT / target / f"{region_key}.manifest.json", {})
        for target in target_keys
    ]
    compose_complete = bool(
        target_keys
        and len(compose_manifests) == len(target_keys)
        and all(
            manifest.get("status") == "completed"
            and int(manifest.get("features", 0) or 0) > 0
            and (
                (manifest.get("coverage") or {}).get("complete") is True
                or (manifest.get("coverage") or {}).get("inventory_complete") is True
            )
            for manifest in compose_manifests
        )
    )
    composed_count = sum(
        bool(manifest) and int(manifest.get("features", 0) or 0) > 0
        for manifest in compose_manifests
    )

    # Ricevuta prevista dal contratto dello stadio 05. Finché il load è uno
    # stub, nessuna regione può essere dichiarata caricata.
    load_receipts = [
        ROOT / "work" / "load" / f"{source_key}.manifest.json",
        ROOT / "state" / f"load_{source_key}.json",
    ]
    load_data = next(
        (read_json(path, {}) for path in load_receipts if path.exists()),
        {},
    )
    load_complete = bool(
        load_data.get("status") == "completed"
        and load_data.get("promoted") is True
    )

    steps = [
        {
            "id": "discover", "number": "01", "name": "Scoperta fonti",
            "complete": discover_complete,
            "detail": (
                f"{catalog_total} dataset censiti"
                if discover_complete else "Catalogo completo non disponibile"
            ),
        },
        {
            "id": "download", "number": "02", "name": "Download",
            "complete": download_complete,
            "detail": f"{downloaded}/{expected_downloads} layer scaricati"
            + (f" · {download_failed} errori" if download_failed else ""),
        },
        {
            "id": "recognize", "number": "03", "name": "Riconoscimento",
            "complete": recognize_complete,
            "detail": f"{min(processed, catalog_total)}/{catalog_total} dataset elaborati",
        },
        {
            "id": "compose", "number": "04", "name": "Composizione",
            "complete": compose_complete,
            "detail": f"{composed_count}/{len(target_keys)} layer finali creati",
        },
        {
            "id": "load", "number": "05", "name": "Caricamento",
            "complete": load_complete,
            "detail": "Dati caricati e promossi" if load_complete else "Caricamento non completato",
        },
    ]
    completed = sum(step["complete"] for step in steps)
    return {
        "percentage": completed * 20,
        "completed_steps": completed,
        "total_steps": 5,
        "steps": steps,
    }


def final_layers_payload(scope: dict[str, Any]) -> dict[str, Any]:
    level = str(scope.get("level") or "")
    key = str(scope.get("key") or "")
    features: list[dict[str, Any]] = []
    layers = []
    truncated = False
    for path in final_layer_paths(level, key):
        data = read_json(path, {})
        source_features = data.get("features", [])
        available = max(0, 5000 - len(features))
        selected = source_features[:available]
        target = path.parent.name
        for feature in selected:
            properties = dict(feature.get("properties") or {})
            properties["_final_target"] = target
            features.append({**feature, "properties": properties})
        if len(selected) < len(source_features):
            truncated = True
        layers.append(
            {
                "key": target,
                "name": target.replace("_", " ").title(),
                "features": len(source_features),
                "path": str(path),
            }
        )
        if len(features) >= 5000:
            truncated = True
            break
    return {
        "type": "FeatureCollection",
        "features": features,
        "layers": layers,
        "truncated": truncated,
        "scope": scope,
    }


def territory_metrics(level: str, props: dict[str, Any]) -> dict[str, Any]:
    index = source_index()
    counts = territory_counts()
    key = str(props["key"])
    region_key = key if level == "region" else str(props.get("reg_key", ""))
    province_key = key if level == "province" else str(props.get("prov_key", ""))

    if level == "region":
        sources = index["by_region"].get(key, [])
        municipality_total = counts["municipalities_by_region"].get(key, 0)
        municipality_sources = [
            row
            for rows in index["by_municipality"].values()
            for row in rows
            if str(row.get("region_istat")) == key
            and row.get("status") == "active"
            and "regolatore" in row.get("plan_types", [])
        ]
        child_count = counts["provinces_by_region"].get(key, 0)
    elif level == "province":
        sources = index["by_province"].get(key, [])
        municipality_total = counts["municipalities_by_province"].get(key, 0)
        municipality_sources = [
            row
            for rows in index["by_municipality"].values()
            for row in rows
            if str(row.get("province_istat")) == key
            and row.get("status") == "active"
            and "regolatore" in row.get("plan_types", [])
        ]
        child_count = municipality_total
    else:
        sources = index["by_municipality"].get(key, [])
        municipality_total = 1
        municipality_sources = [
            row
            for row in sources
            if row.get("status") == "active"
            and "regolatore" in row.get("plan_types", [])
        ]
        child_count = 0

    active_sources = [row for row in sources if row.get("status") == "active"]
    pipeline_progress = region_pipeline_progress(region_key)
    regional_coverage = max(
        (
            int(row.get("municipality_coverage_count") or 0)
            for row in index["by_region"].get(region_key, [])
            if row.get("status") == "active"
            and "regolatore" in row.get("plan_types", [])
        ),
        default=0,
    )
    covered_municipalities = max(len(municipality_sources), regional_coverage)
    regulatory_coverage = (
        round(min(covered_municipalities, municipality_total) / municipality_total * 100, 1)
        if municipality_total
        else 0
    )
    return {
        "source_count": len(sources),
        "active_source_count": len(active_sources),
        "final_layers": final_layer_count(level, key),
        "regulatory_coverage": regulatory_coverage,
        "pipeline_completion_pct": pipeline_progress["percentage"],
        "pipeline_completed_steps": pipeline_progress["completed_steps"],
        "pipeline_total_steps": pipeline_progress["total_steps"],
        "pipeline_steps": pipeline_progress["steps"],
        "child_count": child_count,
        "municipality_count": municipality_total,
        "process_available": (level, key) in SCOPE_RUNNERS,
        "sources": [compact_source(row) for row in sources],
        "region_key": region_key,
        "province_key": province_key,
    }


def territories_payload(
    level: str, region: str | None, province: str | None, query: str
) -> dict[str, Any]:
    if level not in ADMIN_FILES:
        raise ValueError("Livello territoriale non valido.")
    features = admin_geojson(level).get("features", [])
    query_norm = query.casefold().strip()
    result = []
    for feature in features:
        props = feature["properties"]
        if region and str(props.get("reg_key", props.get("key"))) != region:
            continue
        if province and str(props.get("prov_key", props.get("key"))) != province:
            continue
        if query_norm and query_norm not in str(props.get("name", "")).casefold():
            continue
        enriched = {
            **props,
            "metrics": territory_metrics(level, props),
            "level": level,
        }
        item = {
            "type": "Feature",
            "properties": enriched,
            "geometry": feature.get("geometry") if level != "municipality" else None,
        }
        result.append(item)
        # Il filtro regione → comune deve includere per intero anche Lombardia
        # e Veneto; 2.000 copre ogni regione senza caricare tutti i comuni
        # italiani quando manca ancora un filtro territoriale.
        if level == "municipality" and len(result) >= 2000:
            break

    config = sources_config().get("territorial_registry", {})
    observed = config.get("hierarchy", {}).get("observed_counts", {})
    return {
        "type": "FeatureCollection",
        "level": level,
        "features": result,
        "registry": {
            "regions": observed.get("regions", 20),
            "provinces": observed.get("provinces", 110),
            "municipalities_raw": observed.get("municipality_rows_raw", 8092),
            "geometry_provinces": len(admin_geojson("province").get("features", [])),
            "geometry_municipalities": len(
                admin_geojson("municipality").get("features", [])
            ),
        },
    }


def scope_runner(scope: dict[str, Any]) -> dict[str, Any]:
    level = str(scope.get("level") or "")
    key = str(scope.get("key") or "")
    runner = SCOPE_RUNNERS.get((level, key))
    if not runner:
        raise RuntimeError(
            "Per questo territorio non è ancora configurato un catalogo eseguibile."
        )
    return {"level": level, "key": key, **runner}


def scoped_catalog(scope: dict[str, Any]) -> tuple[Path, int]:
    runner = scope_runner(scope)
    base_catalog = Path(runner.get("catalog") or CATALOG)
    if not base_catalog.exists():
        raise RuntimeError("Il catalogo territoriale non esiste: eseguire prima Scoperta fonti.")
    prefixes = runner["prefixes"]
    if prefixes is None:
        with base_catalog.open(encoding="utf-8", newline="") as handle:
            return base_catalog, sum(1 for _ in csv.DictReader(handle))

    SCOPED_CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    path = SCOPED_CATALOG_DIR / f"{runner['level']}_{runner['key']}.csv"
    with base_catalog.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = [
            row
            for row in reader
            if (row.get("uuid") or "").startswith(tuple(prefixes))
        ]
        fieldnames = reader.fieldnames or []
    if not rows:
        raise RuntimeError("Il catalogo territoriale è vuoto.")
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path, len(rows)


def scope_summary(scope: dict[str, Any]) -> dict[str, Any]:
    try:
        runner = scope_runner(scope)
    except RuntimeError:
        return {
            "available": False,
            "recognized": 0,
            "unrecognized": 0,
            "total": 0,
            "coverage": 0,
            "last_run": None,
        }
    pipeline = SCOPE_PIPELINES.get((runner["level"], runner["key"])) or {}
    source_keys = list(pipeline.get("sources") or [runner["ente"]])
    recognition_paths = [RECOGNITION_DIR / f"{key}.json" for key in source_keys]
    proposal_paths = [PROPOSALS_DIR / f"{key}.json" for key in source_keys]
    recognized = sum(
        int(read_json(path, {}).get("count", 0))
        for path in recognition_paths
    )
    unrecognized = sum(
        int(read_json(path, {}).get("count", 0))
        for path in proposal_paths
    )
    total = recognized + unrecognized
    last_runs = [
        value for value in (modified_at(path) for path in recognition_paths) if value
    ]
    return {
        "available": True,
        "recognized": recognized,
        "unrecognized": unrecognized,
        "total": total,
        "coverage": round(recognized / total * 100, 1) if total else 0,
        "last_run": max(last_runs) if last_runs else None,
    }


class JobManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.current: dict[str, Any] | None = None
        self.process: subprocess.Popen[str] | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=50)
        self.call_states: dict[str, dict[str, dict[str, Any]]] = {}
        if JOB_HISTORY_DIR.exists():
            paths = sorted(
                JOB_HISTORY_DIR.glob("*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for path in reversed(paths[:50]):
                value = read_json(path, None)
                if isinstance(value, dict):
                    self.history.appendleft(value)

    def _record_call(self, job_id: str, event: dict[str, Any]) -> None:
        states = self.call_states.setdefault(job_id, {})
        call_id = str(event.get("id") or uuid.uuid4())
        previous = states.get(call_id, {})
        states[call_id] = {**previous, **event, "id": call_id}
        if not self.current or self.current.get("id") != job_id:
            return
        recent = list(states.values())
        counts: dict[str, int] = defaultdict(int)
        for item in states.values():
            counts[str(item.get("status") or "unknown")] += 1
        self.current["calls"] = recent
        self.current["call_counts"] = dict(counts)
        self.current["calls_total"] = len(states)
        self.current["calls_truncated"] = False

    def _store_finished(self, finished: dict[str, Any]) -> None:
        JOB_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        path = JOB_HISTORY_DIR / f"{finished['id']}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(finished, ensure_ascii=False, indent=2), "utf-8")
        temporary.replace(path)

    def _fail_before_process(self, job_id: str, exc: Exception) -> None:
        """Evita job fantasma se il sottoprocesso non riesce nemmeno a partire."""
        with self.lock:
            if not self.current or self.current.get("id") != job_id:
                return
            self.current["status"] = "failed"
            self.current["exit_code"] = -1
            self.current["finished_at"] = datetime.now().astimezone().isoformat()
            self.current["result"] = {
                "status": "failed",
                "message": f"Avvio del processo fallito: {exc}",
                "error": str(exc),
            }
            self.current["logs"].append(str(exc))
            finished = {
                key: value
                for key, value in self.current.items()
                if key != "started_at_epoch"
            }
            self.history.appendleft(finished)
            self._store_finished(finished)
            self.process = None

    def snapshot(self) -> dict[str, Any] | None:
        with self.lock:
            if not self.current:
                return None
            result = dict(self.current)
            result["logs"] = list(self.current.get("logs", []))
            if result.get("status") == "running":
                result["elapsed_seconds"] = round(
                    time.time() - result["started_at_epoch"], 1
                )
            return result

    def start_recognize(self, force: bool, requested_scope: dict[str, Any]) -> dict[str, Any]:
        runner = scope_runner(requested_scope)
        catalog, expected_total = scoped_catalog(requested_scope)
        pipeline = SCOPE_PIPELINES.get((runner["level"], runner["key"])) or {}
        source_keys = list(pipeline.get("sources") or [runner["ente"]])
        if len(source_keys) > 1:
            catalogs = [
                ROOT / "work" / "catalog" / f"{source_key}.csv"
                for source_key in source_keys
            ]
            missing = [path for path in catalogs if not path.exists()]
            if missing:
                raise RuntimeError(
                    "Cataloghi mancanti: eseguire prima Scoperta fonti."
                )
            expected_total = sum(_csv_row_count(path) for path in catalogs)
            runner["source_keys"] = source_keys
        with self.lock:
            if self.current and self.current.get("status") == "running":
                raise RuntimeError("Un processo è già in esecuzione.")
            job = {
                "id": str(uuid.uuid4()),
                "stage": "recognize",
                "label": f"Riconoscimento · {runner['label']}",
                "scope": {
                    "level": runner["level"],
                    "key": runner["key"],
                    "name": runner["label"],
                },
                "status": "running",
                "progress": 0,
                "current": 0,
                "total": expected_total,
                "force": force,
                "resume_options": {"force": False},
                "started_at": datetime.now().astimezone().isoformat(),
                "started_at_epoch": time.time(),
                "finished_at": None,
                "exit_code": None,
                "logs": [f"Avvio su {runner['label']} · {expected_total} dataset"],
                "calls": [],
                "call_counts": {},
                "calls_total": 0,
            }
            self.current = job
            self.call_states[job["id"]] = {}

        thread = threading.Thread(
            target=self._run_recognize,
            args=(job["id"], force, runner, catalog),
            daemon=True,
        )
        thread.start()
        return self.snapshot() or job

    def start_region_stage(
        self,
        stage: str,
        requested_scope: dict[str, Any],
        requested_batch_size: int | None = None,
        requested_only_new: bool = True,
    ) -> dict[str, Any]:
        if stage not in {"discover", "download"}:
            raise RuntimeError("Stadio non autorizzato.")
        level = str(requested_scope.get("level") or "")
        key = str(requested_scope.get("key") or "")
        pipeline = SCOPE_PIPELINES.get((level, key))
        if not pipeline:
            raise RuntimeError(
                "Scoperta e Download non sono ancora configurati per questo territorio."
            )
        source = _source_by_key(pipeline["source"])
        pipeline_sources = list(pipeline.get("sources") or [pipeline["source"]])
        # batch_size = quanti layer per esecuzione. 0 = TUTTI i pendenti (in chunk, ripresa).
        batch_size = 0
        if stage == "download":
            configured_batch_size = int(source.get("dashboard_batch_size") or 0)
            selected_batch_size = (
                requested_batch_size
                if requested_batch_size is not None
                else configured_batch_size
            )
            batch_size = max(0, min(int(selected_batch_size or 0), 100))
        label = "Scoperta fonti" if stage == "discover" else "Download"
        expected_total = int(
            source.get("expected_map_count")
            or source.get("expected_service_count")
            or source.get("expected_dataset_count")
            or 0
        )
        if len(pipeline_sources) > 1:
            expected_total = sum(
                int(
                    _source_by_key(source_key).get("expected_map_count")
                    or _source_by_key(source_key).get("expected_service_count")
                    or _source_by_key(source_key).get("expected_dataset_count")
                    or 0
                )
                for source_key in pipeline_sources
            )
        if stage == "download":
            manifest = read_json(
                ROOT / "work" / "catalog" / f"{pipeline['source']}_services.json", {}
            )
            if pipeline["source"] == "r_liguria":
                expected_total = sum(
                    bool(item.get("downloadable")) for item in manifest.get("layers", [])
                )
            elif manifest:
                expected_total = int(
                    manifest.get("downloadable_count")
                    or len(manifest.get("services", []))
                )
            if batch_size:
                expected_total = min(
                    expected_total, batch_size
                )
        with self.lock:
            if self.current and self.current.get("status") == "running":
                raise RuntimeError("Un processo è già in esecuzione.")
            job = {
                "id": str(uuid.uuid4()),
                "stage": stage,
                "label": f"{label} · {pipeline['label']}",
                "scope": {"level": level, "key": key, "name": pipeline["label"]},
                "status": "running",
                "progress": 0,
                "current": 0,
                "total": expected_total,
                "force": False,
                "resume_options": {
                    "batch_size": batch_size,
                    "only_new": True,
                },
                "started_at": datetime.now().astimezone().isoformat(),
                "started_at_epoch": time.time(),
                "finished_at": None,
                "exit_code": None,
                "logs": [f"Avvio {label.lower()} per {pipeline['label']}"],
                "result": None,
                "calls": [],
                "call_counts": {},
                "calls_total": 0,
            }
            self.current = job
            self.call_states[job["id"]] = {}

        command = (
            [
                sys.executable,
                "-u",
                "tools/run_sources.py",
                stage,
                "--sources",
                ",".join(pipeline_sources),
            ]
            if len(pipeline_sources) > 1
            else [
                sys.executable,
                "-u",
                "run.py",
                stage,
                "--source",
                pipeline["source"],
                "--progress",
            ]
        )
        if stage == "download" and batch_size:
            command.extend(["--max-services", str(batch_size)])
        if stage == "download" and not requested_only_new:
            command.append("--refresh")
        thread = threading.Thread(
            target=self._run_command,
            args=(job["id"], command),
            daemon=True,
        )
        thread.start()
        return self.snapshot() or job

    def start_source_stage(
        self,
        stage: str,
        source_key: str,
        requested_only_new: bool = True,
        requested_batch_size: int | None = None,
    ) -> dict[str, Any]:
        """Scoperta/Download di UNA singola fonte, indipendente dal territorio
        (sezione 'Per fonte'). Riusa `run.py <stage> --source <key> --progress`."""
        if stage not in {"discover", "download"}:
            raise RuntimeError("Stadio non autorizzato.")
        source = _source_by_key(source_key)  # RuntimeError se la fonte non esiste
        compact = compact_source(source)
        if not compact.get("download_available"):
            raise RuntimeError(
                "Questa fonte non è ancora eseguibile: manca un adapter attivo "
                "(status 'todo' o adapter da implementare)."
            )
        label = "Scoperta fonti" if stage == "discover" else "Download"
        ente = str(source.get("ente") or source_key)
        batch_size = 0
        if stage == "download":
            configured_batch_size = int(source.get("dashboard_batch_size") or 0)
            selected_batch_size = (
                requested_batch_size
                if requested_batch_size is not None
                else configured_batch_size
            )
            batch_size = max(0, min(int(selected_batch_size or 0), 100))
        expected_total = int(compact.get("expected_datasets") or 0)
        if batch_size:
            expected_total = min(expected_total or batch_size, batch_size)
        with self.lock:
            if self.current and self.current.get("status") == "running":
                raise RuntimeError("Un processo è già in esecuzione.")
            job = {
                "id": str(uuid.uuid4()),
                "stage": stage,
                "label": f"{label} · {ente}",
                "scope": {"level": "source", "key": source_key, "name": ente},
                "status": "running",
                "progress": 0,
                "current": 0,
                "total": expected_total,
                "force": False,
                "resume_options": {
                    "batch_size": batch_size,
                    "only_new": bool(requested_only_new),
                },
                "started_at": datetime.now().astimezone().isoformat(),
                "started_at_epoch": time.time(),
                "finished_at": None,
                "exit_code": None,
                "logs": [f"Avvio {label.lower()} per fonte {ente}"],
                "result": None,
                "calls": [],
                "call_counts": {},
                "calls_total": 0,
            }
            self.current = job
            self.call_states[job["id"]] = {}

        command = [
            sys.executable, "-u", "run.py", stage,
            "--source", source_key, "--progress",
        ]
        if stage == "download" and batch_size:
            command.extend(["--max-services", str(batch_size)])
        if stage == "download" and not requested_only_new:
            command.append("--refresh")
        thread = threading.Thread(
            target=self._run_command,
            args=(job["id"], command),
            daemon=True,
        )
        thread.start()
        return self.snapshot() or job

    def start_sources_batch(
        self,
        stage: str,
        source_keys: list[str],
        requested_only_new: bool = True,
    ) -> dict[str, Any]:
        """Scoperta/Download di PIÙ fonti in un solo job (gruppo o tutte), via
        tools/run_sources.py. Filtra le fonti non eseguibili."""
        if stage not in {"discover", "download"}:
            raise RuntimeError("Stadio non autorizzato.")
        runnable: list[str] = []
        for key in source_keys:
            if not key:
                continue
            try:
                source = _source_by_key(key)
            except RuntimeError:
                continue
            if compact_source(source).get("download_available"):
                runnable.append(key)
        if not runnable:
            raise RuntimeError("Nessuna fonte eseguibile nella selezione.")
        label = "Scoperta fonti" if stage == "discover" else "Download"
        with self.lock:
            if self.current and self.current.get("status") == "running":
                raise RuntimeError("Un processo è già in esecuzione.")
            job = {
                "id": str(uuid.uuid4()),
                "stage": stage,
                "label": f"{label} · {len(runnable)} fonti",
                "scope": {"level": "sources", "key": ",".join(runnable),
                          "name": f"{len(runnable)} fonti"},
                "status": "running",
                "progress": 0,
                "current": 0,
                "total": len(runnable),
                "force": False,
                "resume_options": {"batch_size": 0, "only_new": bool(requested_only_new)},
                "started_at": datetime.now().astimezone().isoformat(),
                "started_at_epoch": time.time(),
                "finished_at": None,
                "exit_code": None,
                "logs": [f"Avvio {label.lower()} per {len(runnable)} fonti"],
                "result": None,
                "calls": [],
                "call_counts": {},
                "calls_total": 0,
            }
            self.current = job
            self.call_states[job["id"]] = {}

        command = [
            sys.executable, "-u", "tools/run_sources.py", stage,
            "--sources", ",".join(runnable),
        ]
        if stage == "download" and not requested_only_new:
            command.append("--refresh")
        thread = threading.Thread(
            target=self._run_command, args=(job["id"], command), daemon=True,
        )
        thread.start()
        return self.snapshot() or job

    def start_compose(
        self, requested_scope: dict[str, Any], targets: list[str]
    ) -> dict[str, Any]:
        targets = [str(t).strip() for t in (targets or []) if str(t).strip()]
        if not targets:
            raise RuntimeError("Seleziona almeno un layer da comporre.")
        level = str(requested_scope.get("level") or "")
        key = str(requested_scope.get("key") or "")
        name = str(requested_scope.get("name") or key)
        runner = SCOPE_RUNNERS.get((level, key))
        if not runner or not runner.get("compose_available", True):
            raise RuntimeError(
                "Composizione non ancora disponibile per questo territorio."
            )
        allowed_targets = set(runner.get("compose_targets") or targets)
        unsupported = sorted(set(targets) - allowed_targets)
        if unsupported:
            raise RuntimeError(
                "Target non ancora disponibili per questo territorio: "
                + ", ".join(unsupported)
            )
        with self.lock:
            if self.current and self.current.get("status") == "running":
                raise RuntimeError("Un processo è già in esecuzione.")
            job = {
                "id": str(uuid.uuid4()),
                "stage": "compose",
                "label": f"Composizione · {name}",
                "scope": {"level": level, "key": key, "name": name},
                "status": "running",
                "progress": 0,
                "current": 0,
                "total": len(targets),
                "force": False,
                "targets": targets,
                "resume_options": {"targets": targets},
                "started_at": datetime.now().astimezone().isoformat(),
                "started_at_epoch": time.time(),
                "finished_at": None,
                "exit_code": None,
                "logs": [f"Composizione di {len(targets)} target: {', '.join(targets)}"],
                "result": None,
                "calls": [],
                "call_counts": {},
                "calls_total": 0,
            }
            self.current = job
            self.call_states[job["id"]] = {}
        command = [
            sys.executable, "-u", "run.py", "compose",
            "--targets", ",".join(targets),
            "--scope-level", level, "--scope-key", key, "--scope-name", name,
            "--progress",
        ]
        thread = threading.Thread(
            target=self._run_command, args=(job["id"], command), daemon=True
        )
        thread.start()
        return self.snapshot() or job

    def resume(self, job_id: str) -> dict[str, Any]:
        """Rilancia un job concluso conservando scope e opzioni riprendibili."""
        with self.lock:
            if self.current and self.current.get("status") == "running":
                raise RuntimeError("Un processo è già in esecuzione.")
            candidates = [self.current, *list(self.history)]
            previous = next(
                (dict(item) for item in candidates if item and item.get("id") == job_id),
                None,
            )
        if not previous:
            raise RuntimeError("Esecuzione da riprendere non trovata.")
        if previous.get("status") not in {"failed", "cancelled"}:
            raise RuntimeError("Si possono riprendere soltanto processi interrotti o falliti.")

        stage = str(previous.get("stage") or "")
        scope = previous.get("scope") or {}
        options = previous.get("resume_options") or {}
        if stage == "recognize":
            return self.start_recognize(False, scope)
        if stage in {"discover", "download"}:
            return self.start_region_stage(
                stage,
                scope,
                int(options.get("batch_size") or 0) or None,
                True,
            )
        if stage == "compose":
            targets = (
                options.get("targets")
                or previous.get("targets")
                or (previous.get("result") or {}).get("targets")
                or []
            )
            if not targets:
                raise RuntimeError(
                    "I target della vecchia composizione non sono disponibili: selezionali e riavvia."
                )
            return self.start_compose(scope, list(targets))
        raise RuntimeError("Questo stadio non supporta ancora la ripresa.")

    def _run_command(self, job_id: str, command: list[str]) -> None:
        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            self._fail_before_process(job_id, exc)
            return
        with self.lock:
            if self.current and self.current["id"] == job_id:
                self.process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            with self.lock:
                if not self.current or self.current["id"] != job_id:
                    continue
                if line.startswith("PROGRESS "):
                    _, current, total = line.split()
                    current_n, total_n = int(current), int(total)
                    self.current["current"] = current_n
                    self.current["total"] = total_n
                    self.current["progress"] = (
                        round(current_n / total_n * 100, 1) if total_n else 0
                    )
                elif line.startswith("RESULT_JSON "):
                    try:
                        self.current["result"] = json.loads(line.removeprefix("RESULT_JSON "))
                    except json.JSONDecodeError:
                        self.current["logs"].append("Riepilogo finale non leggibile.")
                elif line.startswith("CALL_JSON "):
                    try:
                        self._record_call(
                            job_id, json.loads(line.removeprefix("CALL_JSON "))
                        )
                    except json.JSONDecodeError:
                        self.current["logs"].append("Evento chiamata non leggibile.")
                elif line:
                    self.current["logs"].append(line)
                    self.current["logs"] = self.current["logs"][-80:]
        exit_code = process.wait()
        with self.lock:
            if not self.current or self.current["id"] != job_id:
                return
            if self.current.get("status") != "cancelled":
                self.current["status"] = "completed" if exit_code == 0 else "failed"
            self.current["exit_code"] = exit_code
            self.current["finished_at"] = datetime.now().astimezone().isoformat()
            if exit_code == 0:
                self.current["progress"] = 100
            finished = {k: v for k, v in self.current.items() if k != "started_at_epoch"}
            self.history.appendleft(finished)
            self._store_finished(finished)
            self.process = None

    def _run_recognize(
        self, job_id: str, force: bool, runner: dict[str, Any], catalog: Path
    ) -> None:
        source_keys = list(runner.get("source_keys") or [])
        command = (
            [
                sys.executable,
                "-u",
                "tools/run_recognize_sources.py",
                "--sources",
                ",".join(source_keys),
            ]
            if len(source_keys) > 1
            else [
                sys.executable,
                "-u",
                "run.py",
                "recognize",
                "--catalog",
                str(catalog),
                "--ente",
                runner["ente"],
                "--progress",
            ]
        )
        if force:
            command.append("--force")
        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            self._fail_before_process(job_id, exc)
            return
        with self.lock:
            if self.current and self.current["id"] == job_id:
                self.process = process

        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            with self.lock:
                if not self.current or self.current["id"] != job_id:
                    continue
                if line.startswith("PROGRESS "):
                    _, current, total = line.split()
                    current_n, total_n = int(current), int(total)
                    self.current["current"] = current_n
                    self.current["total"] = total_n
                    self.current["progress"] = (
                        round(current_n / total_n * 100, 1) if total_n else 0
                    )
                elif line:
                    self.current["logs"].append(line)
                    self.current["logs"] = self.current["logs"][-80:]

        exit_code = process.wait()
        with self.lock:
            if not self.current or self.current["id"] != job_id:
                return
            if self.current.get("status") != "cancelled":
                self.current["status"] = "completed" if exit_code == 0 else "failed"
            self.current["exit_code"] = exit_code
            self.current["finished_at"] = datetime.now().astimezone().isoformat()
            if exit_code == 0:
                self.current["progress"] = 100
            finished = {k: v for k, v in self.current.items() if k != "started_at_epoch"}
            self.history.appendleft(finished)
            self._store_finished(finished)
            self.process = None

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if not self.current or self.current.get("status") != "running":
                raise RuntimeError("Nessun processo attivo da interrompere.")
            process = self.process
            self.current["status"] = "cancelled"
            self.current["logs"].append("Interruzione richiesta dall’utente.")
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        return self.snapshot() or {}


JOBS = JobManager()


def dashboard_payload(scope: dict[str, Any]) -> dict[str, Any]:
    taxonomy = yaml.safe_load(TAXONOMY.read_text("utf-8")) if TAXONOMY.exists() else {}
    dictionary = (
        yaml.safe_load(DICTIONARY.read_text("utf-8")) if DICTIONARY.exists() else {}
    )
    current = JOBS.snapshot()
    stages = []
    scope_available = (str(scope.get("level")), str(scope.get("key"))) in SCOPE_RUNNERS
    scope_level = str(scope.get("level"))
    scope_key = str(scope.get("key"))
    pipeline = SCOPE_PIPELINES.get((scope_level, scope_key))
    for definition in STAGE_DEFINITIONS:
        stage = dict(definition)
        if definition["id"] in {"discover", "download"}:
            stage["available"] = bool(pipeline)
            source_key = pipeline["source"] if pipeline else ""
            source_keys = list(
                pipeline.get("sources") or [source_key]
            ) if pipeline else []
            if definition["id"] == "download" and source_key:
                stage["recommended_batch_size"] = int(
                    _source_by_key(source_key).get("dashboard_batch_size") or 0
                )
            catalogs = [
                ROOT / "work" / "catalog" / f"{key}.csv"
                for key in source_keys
            ]
            catalog_manifest_paths = [
                ROOT / "work" / "catalog" / f"{key}_services.json"
                for key in source_keys
            ]
            outputs = (
                catalogs
                if definition["id"] == "discover"
                else [_raw_manifest_path(key) for key in source_keys]
            )
            output_exists = bool(outputs and all(path.exists() for path in outputs))
            auth_markers = [
                ROOT
                / "raw"
                / str(_source_by_key(key).get("livello") or "regione")
                / key
                / "_auth_required.json"
                for key in source_keys
            ]
            current_matches = bool(
                current
                and current["stage"] == definition["id"]
                and current.get("scope", {}).get("level") == scope.get("level")
                and str(current.get("scope", {}).get("key")) == scope_key
            )
            result_status = (
                (current.get("result") or {}).get("status") if current_matches else None
            )
            if current_matches and current["status"] == "running":
                stage["status"] = "in_esecuzione"
            elif result_status == "authentication_required" or (
                definition["id"] == "download"
                and any(path.exists() for path in auth_markers)
                and not output_exists
            ):
                stage["status"] = "autenticazione_richiesta"
            elif current_matches and current["status"] in {"failed", "cancelled"}:
                stage["status"] = "fallito"
            elif output_exists:
                if definition["id"] == "discover":
                    manifest_data = [
                        read_json(path, {}) for path in catalog_manifest_paths
                    ]
                    stage["errors"] = [
                        error
                        for data in manifest_data
                        for error in _manifest_errors(data)
                    ]
                    if source_key == "r_liguria" and len(manifest_data) == 1:
                        data = manifest_data[0]
                        map_count = len(data.get("maps", []))
                        layer_count = len(data.get("layers", []))
                        failures = len(data.get("failures", []))
                        stage["detail"] = (
                            f"{map_count} mappe · {layer_count} layer · {failures} errori"
                        )
                        stage["status"] = "completato" if not failures else "parziale"
                    else:
                        # Il catalogo CSV è la verità autoritativa (una riga per
                        # item scaricabile, incluse le risorse CKAN che non
                        # compaiono come ``layers`` nel manifest); i conteggi del
                        # manifest restano solo come fallback se il CSV manca.
                        layer_count = sum(
                            _csv_row_count(catalog)
                            or int(
                                data.get("inventory_count")
                                or data.get("downloadable_count")
                                or len(data.get("layers", []) or [])
                                or len(data.get("resources", []) or [])
                            )
                            for data, catalog in zip(manifest_data, catalogs)
                        )
                        service_count = sum(
                            int(
                                data.get("services_count")
                                or len(data.get("services", []))
                            )
                            for data in manifest_data
                        )
                        failures = sum(
                            len(data.get("failures", []) or [])
                            for data in manifest_data
                        )
                        stage["detail"] = (
                            f"{layer_count} layer · {service_count} servizi"
                            + (f" · {failures} errori" if failures else "")
                        )
                        stage["status"] = "completato" if not failures else "parziale"
                else:
                    download_data = [read_json(path, {}) for path in outputs]
                    stage["errors"] = [
                        error
                        for data in download_data
                        for error in _manifest_errors(data)
                    ]
                    downloaded = sum(
                        int(data.get("layers_downloaded", 0))
                        for data in download_data
                    )
                    failed = sum(
                        int(data.get("layers_failed", 0))
                        for data in download_data
                    )
                    if failed and not stage["errors"]:
                        stage["errors"] = [
                            str(
                                data.get("error")
                                or data.get("message")
                                or data.get("note")
                                or "Il manifest segnala un errore senza dettaglio; consultare il log del processo."
                            )
                            for data in download_data
                            if int(data.get("layers_failed", 0) or 0)
                        ]
                    catalog_data = [
                        read_json(path, {}) for path in catalog_manifest_paths
                    ]
                    if source_key == "r_liguria" and len(catalog_data) == 1:
                        expected = sum(
                            bool(item.get("downloadable"))
                            for item in catalog_data[0].get("layers", [])
                        )
                    else:
                        # Denominatore = righe del catalogo CSV (verità
                        # autoritativa, comprende le risorse CKAN); i conteggi del
                        # manifest sono solo fallback. Evita il caso "205/198" in
                        # cui una fonte-collezione conta 0 nel denominatore ma N
                        # negli scaricati.
                        expected = sum(
                            _csv_row_count(catalog)
                            or int(
                                data.get("downloadable_count")
                                or len(data.get("services", []) or [])
                                or len(data.get("layers", []) or [])
                                or len(data.get("resources", []) or [])
                            )
                            for data, catalog in zip(catalog_data, catalogs)
                        )
                    stage["detail"] = (
                        f"{downloaded}/{expected} layer scaricati"
                        + (f" · {failed} errori" if failed else "")
                    )
                    stage["status"] = (
                        "completato"
                        if expected and downloaded >= expected and not failed
                        else "parziale"
                    )
            elif definition["id"] == "download" and catalogs and all(
                path.exists() for path in catalogs
            ):
                stage["status"] = "pronto"
            elif not pipeline:
                stage["status"] = "catalogo_mancante"
            else:
                stage["status"] = "da_avviare"
        if definition["id"] == "recognize":
            stage["available"] = scope_available
            if (
                current
                and current["status"] == "running"
                and current["stage"] == "recognize"
            ):
                stage["status"] = "in_esecuzione"
            elif scope_summary(scope)["last_run"]:
                stage["status"] = "completato"
            elif not scope_available:
                stage["status"] = "catalogo_mancante"
        if definition["id"] == "compose":
            runner = SCOPE_RUNNERS.get((scope_level, scope_key))
            compose_available = bool(
                runner and runner.get("compose_available", True)
            )
            stage["available"] = compose_available
            # ogni target con stato per il territorio: assente / presente / da_aggiornare
            stage["targets"] = composition_state.targets_for_scope(scope)
            if runner and runner.get("compose_targets"):
                allowed_targets = set(runner["compose_targets"])
                stage["targets"] = [
                    item
                    for item in stage["targets"]
                    if item.get("key") in allowed_targets
                ]
            counts = defaultdict(int)
            for item in stage["targets"]:
                counts[item.get("state", "assente")] += 1
            stage["target_counts"] = dict(counts)
            stage["detail"] = (
                f"{counts.get('presente', 0)} presenti · "
                f"{counts.get('parziale', 0)} parziali · "
                f"{counts.get('da_aggiornare', 0)} da aggiornare · "
                f"{counts.get('assente', 0)} da comporre"
            )
            paths = final_layer_paths(str(scope.get("level")), str(scope.get("key")))
            stage["final_layers"] = len(paths)
            stage["viewer_available"] = bool(paths)
            if counts.get("da_aggiornare"):
                stage["status"] = "da_aggiornare"
            elif counts.get("parziale"):
                stage["status"] = "parziale"
            elif paths and not counts.get("assente"):
                stage["status"] = "completato"
            elif not compose_available:
                stage["status"] = "da_implementare"
        stages.append(stage)
    scoped_history = [
        item
        for item in JOBS.history
        if item.get("scope", {}).get("level") == scope.get("level")
        and str(item.get("scope", {}).get("key")) == str(scope.get("key"))
    ]
    current_matches_scope = bool(
        current
        and current.get("scope", {}).get("level") == scope.get("level")
        and str(current.get("scope", {}).get("key")) == str(scope.get("key"))
    )
    job_for_scope = current if current_matches_scope else (scoped_history[0] if scoped_history else None)
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "system": {
            "name": "Layer Processor",
            "mode": "Locale",
            # Il vecchio Nord/piemonte/_catalog.csv è solo un golden test.
            # La dashboard deve risultare operativa anche in un'installazione
            # vuota appena popolata dallo stadio Scoperta.
            "catalog_exists": any((ROOT / "work" / "catalog").glob("*.csv")),
        },
        "scope": scope,
        "scope_summary": scope_summary(scope),
        "metrics": {
            "canonical_classes": len(taxonomy.get("classes", {})),
            "dictionary_rules": len(dictionary.get("rules", [])),
        },
        "stages": stages,
        "job": job_for_scope,
        "active_job": (
            current
            if current and current.get("status") == "running"
            else None
        ),
        "history": scoped_history,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "LayerProcessorDashboard/2.0"

    def _headers(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, payload: Any, status: int = 200) -> None:
        self._headers(status)
        try:
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        except BrokenPipeError:
            pass

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length > 16_384:
            raise ValueError("Richiesta troppo grande.")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._headers(204)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/dashboard":
                scope = {
                    "level": query.get("level", ["region"])[0],
                    "key": query.get("key", ["01"])[0],
                    "name": query.get("name", ["Piemonte"])[0],
                }
                self._json(dashboard_payload(scope))
            elif path == "/api/territories":
                self._json(
                    territories_payload(
                        level=query.get("level", ["region"])[0],
                        region=query.get("region", [None])[0],
                        province=query.get("province", [None])[0],
                        query=query.get("q", [""])[0],
                    )
                )
            elif path == "/api/sources":
                scope = {
                    "level": query.get("level", ["region"])[0],
                    "key": query.get("key", ["01"])[0],
                    "name": query.get("name", ["Piemonte"])[0],
                }
                self._json(sources_payload(scope))
            elif path == "/api/sources/health":
                self._json(sources_health())
            elif path == "/api/sources/catalog":
                self._json(sources_catalog())
            elif path == "/api/sources/check":
                self._json(source_check(query.get("key", [""])[0]))
            elif path == "/api/provenance":
                self._json(layer_provenance(
                    query.get("target", [""])[0],
                    {"level": query.get("level", ["region"])[0],
                     "key": query.get("key", [""])[0]},
                ))
            elif path == "/api/health":
                self._json({"ok": True, "local": True, "version": 2})
            elif path == "/api/final-layers":
                scope = {
                    "level": query.get("level", ["region"])[0],
                    "key": query.get("key", [""])[0],
                    "name": query.get("name", [""])[0],
                }
                self._json(final_layers_payload(scope))
            else:
                self._json({"error": "Endpoint non trovato."}, 404)
        except (ValueError, KeyError) as exc:
            self._json({"error": str(exc)}, 400)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/jobs/resume":
                body = self._body()
                self._json({"job": JOBS.resume(str(body.get("job_id") or ""))}, 202)
                return
            if path != "/api/jobs":
                self._json({"error": "Endpoint non trovato."}, 404)
                return
            body = self._body()
            stage = body.get("stage")
            if stage not in {"discover", "download", "recognize", "compose"}:
                self._json(
                    {"error": "Questo stadio non è ancora implementato o autorizzato."},
                    409,
                )
                return
            if body.get("sources") and stage in {"discover", "download"}:
                # Download/scoperta di un gruppo di fonti o di tutte.
                job = JOBS.start_sources_batch(
                    stage,
                    list(body.get("sources") or []),
                    bool(body.get("only_new", True)),
                )
                self._json({"job": job}, 202)
                return
            if body.get("source") and stage in {"discover", "download"}:
                # Sezione "Per fonte": download/scoperta di una singola fonte.
                job = JOBS.start_source_stage(
                    stage,
                    str(body.get("source")),
                    bool(body.get("only_new", True)),
                    int(body["batch_size"]) if body.get("batch_size") else None,
                )
                self._json({"job": job}, 202)
                return
            if stage == "recognize":
                job = JOBS.start_recognize(
                    bool(body.get("force", False)), body.get("scope") or {}
                )
            elif stage == "compose":
                job = JOBS.start_compose(
                    body.get("scope") or {}, body.get("targets") or []
                )
            else:
                job = JOBS.start_region_stage(
                    stage,
                    body.get("scope") or {},
                    int(body["batch_size"]) if body.get("batch_size") else None,
                    bool(body.get("only_new", True)),
                )
            self._json({"job": job}, 202)
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            active = JOBS.snapshot()
            self._json({
                "error": str(exc),
                "active_job": (
                    active
                    if active and active.get("status") == "running"
                    else None
                ),
            }, 409)

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path != "/api/jobs/current":
                self._json({"error": "Endpoint non trovato."}, 404)
                return
            self._json({"job": JOBS.stop()})
        except RuntimeError as exc:
            self._json({"error": str(exc)}, 409)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="API locale della dashboard")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Controller locale attivo su http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
