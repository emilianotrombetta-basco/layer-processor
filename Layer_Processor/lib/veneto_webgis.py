"""Adapter dei WebGIS ufficiali della pianificazione del Veneto.

Il portale aggiorna periodicamente i nomi fisici dei layer (per esempio la
zonizzazione contiene mese/anno nel nome). Il registry non congela quindi una
lista fragile: la Scoperta legge le configurazioni correnti dei WebGIS
urbanistico e PTRC, le incrocia con GetCapabilities WFS e produce il normale
manifest consumato da :mod:`wfs_generic`.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely.geometry import shape

from lib import wfs_generic

Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]
USER_AGENT = "LayerProcessor/1.0 (+local territorial data pipeline)"

GROUP_TOPICS = {
    "energia e ambiente": "environment",
    "mobilita": "transportation",
    "sviluppo economico produttivo": "economy",
    "territorio rurale": "farming",
    "valorizzazione del paesaggio": "environment",
    "sviluppo economico turistico": "economy",
    "citta, motore": "planningCadastre",
    "montagna": "environment",
    "crescita sociale": "society",
    "biodiversita": "biota",
    "uso del suolo - terra": "farming",
    "uso del suolo - acqua": "inlandWaters",
    "ambiti di tutela": "environment",
    "idrogeologia": "geoscientificInformation",
}


def _fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    target = f"{url}?{urlencode(params)}"
    request = Request(
        target,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": "https://idt2.regione.veneto.it/",
        },
    )
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _topic_for_group(name: str) -> str:
    normalized = wfs_generic._norm(name)
    for token, topic in GROUP_TOPICS.items():
        if wfs_generic._norm(token) in normalized:
            return topic
    return "planningCadastre"


def _layers_from_config(
    config: dict[str, Any],
    *,
    viewer_id: int,
    role: str,
    available: set[str],
) -> list[dict[str, str]]:
    result = config.get("result") or {}
    maps = result.get("maps") or []
    if not maps:
        raise RuntimeError(f"WebGIS Veneto {viewer_id}: configurazione senza mappe")
    current_map = maps[0]
    groups = {
        int(group["id"]): str(group.get("name") or "")
        for group in current_map.get("groups", [])
        if group.get("id") is not None
    }
    layers: list[dict[str, str]] = []
    for item in current_map.get("layers", []):
        name = str(item.get("name") or "")
        if not name.startswith("rv:") or name not in available:
            continue
        title = str(item.get("title") or name)
        if role == "municipal_planning":
            normalized = wfs_generic._norm(f"{name} {title}")
            if not any(
                token in normalized
                for token in ("limiti amministrativi", "perimetri auc", "zonizzazione")
            ):
                continue
        group = groups.get(int(item.get("groupId") or 0), "")
        topic = (
            "boundaries"
            if "limiti amministrativi" in wfs_generic._norm(title)
            else "planningCadastre"
            if role == "municipal_planning"
            else _topic_for_group(group)
        )
        layers.append(
            {
                "name": name,
                "title": title,
                "topic": topic,
                "group": group,
                "viewer_id": str(viewer_id),
                "viewer_role": role,
                "metadata_url": str(item.get("viewMetdataDetailUrl") or ""),
            }
        )
    return layers


def _viewer_layers(source: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    available_rows = wfs_generic._capabilities_type_names(
        str(source["wfs_url"]),
        str(source.get("wfs_version") or "2.0.0"),
    )
    available = {row["name"] for row in available_rows}
    config_url = str(source["viewer_config_url"])
    discovered: list[dict[str, str]] = []
    viewers: list[dict[str, Any]] = []
    for viewer in source.get("webgis", []):
        viewer_id = int(viewer["id"])
        role = str(viewer["role"])
        payload = _fetch_json(config_url, {"webgisId": viewer_id})
        if not payload.get("success", True):
            raise RuntimeError(
                f"WebGIS Veneto {viewer_id}: {payload.get('msg') or 'risposta non valida'}"
            )
        result = payload.get("result") or {}
        rows = _layers_from_config(
            payload,
            viewer_id=viewer_id,
            role=role,
            available=available,
        )
        discovered.extend(rows)
        viewers.append(
            {
                "id": viewer_id,
                "role": role,
                "name": (result.get("webgis") or {}).get("name"),
                "layer_occurrences_wfs": len(rows),
                "layers_wfs_unique": len({row["name"] for row in rows}),
                "url": str(viewer.get("url") or ""),
            }
        )

    # Il PTRC ripete alcuni layer in tavole diverse. Manteniamo una sola
    # acquisizione fisica, conservando il primo gruppo come provenienza.
    unique: dict[str, dict[str, str]] = {}
    for layer in discovered:
        unique.setdefault(layer["name"], layer)
    return list(unique.values()), viewers


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    layers, viewers = _viewer_layers(source)
    dynamic_source = {**source, "type_names": layers}
    summary = wfs_generic.discover(
        dynamic_source,
        status_source,
        work_dir,
        progress,
    )
    manifest_path = Path(summary["manifest"])
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest.update(
        {
            "adapter": "veneto_webgis",
            "viewers": viewers,
            "discovery_policy": (
                "configurazioni WebGIS correnti incrociate con GetCapabilities WFS; "
                "layer PTRC duplicati tra tavole deduplicati per typeName"
            ),
        }
    )
    wfs_generic._atomic_json(manifest_path, manifest)
    summary.update(
        {
            "message": (
                f"Scoperta Veneto completata: {len(viewers)} WebGIS, "
                f"{len(layers)} layer WFS unici."
            ),
            "services": len(viewers),
            "layers": len(layers),
            "downloadable_layers": len(layers),
            "viewers": viewers,
        }
    )
    return summary


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


def _update_current_municipalities(raw_dir: Path) -> dict[str, Any] | None:
    source_path = (
        raw_dir
        / "regione"
        / "r_veneto"
        / "rv_c0104011_comuni.geojson"
    )
    if not source_path.exists():
        return None
    workspace = raw_dir.parent.parent
    base_path = (
        workspace
        / "Geography_Locations"
        / "outputs"
        / "admin_municipalities.geojson"
    )
    output_path = (
        workspace
        / "Geography_Locations"
        / "outputs"
        / "admin_municipalities_veneto_current.geojson"
    )
    source = json.loads(source_path.read_text("utf-8"))
    base = json.loads(base_path.read_text("utf-8"))
    previous_names = {
        str(feature["properties"]["key"]): str(feature["properties"]["name"])
        for feature in base.get("features", [])
        if str(feature.get("properties", {}).get("reg_key")) == "05"
    }
    features: list[dict[str, Any]] = []
    codes: set[str] = set()
    for feature in source.get("features", []):
        props = feature.get("properties") or {}
        code = "".join(char for char in str(props.get("codistat") or "") if char.isdigit()).zfill(6)
        geometry = feature.get("geometry")
        geom = shape(geometry) if geometry else None
        if len(code) != 6 or not code.isdigit() or code in codes:
            raise RuntimeError(f"Codice ISTAT Veneto non valido o duplicato: {code}")
        if geom is None or geom.is_empty or not geom.is_valid:
            raise RuntimeError(f"Geometria comunale Veneto non valida: {code}")
        name = str(props.get("nomcom") or "").strip()
        if "?" in name:
            name = previous_names.get(code) or name.replace("?", "è")
        centroid = geom.centroid
        codes.add(code)
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "key": code,
                    "prov_key": code[:3],
                    "reg_key": "05",
                    "name": name,
                    "centroid": [round(centroid.x, 6), round(centroid.y, 6)],
                },
                "geometry": geometry,
            }
        )
    features.sort(key=lambda item: str(item["properties"]["key"]))
    if len(features) != 559:
        raise RuntimeError(f"Attesi 559 comuni correnti del Veneto, ottenuti {len(features)}")
    _atomic_json(
        output_path,
        {
            "type": "FeatureCollection",
            "name": "Comuni correnti del Veneto",
            "source": (
                "https://idt2-geoserver.regione.veneto.it/geoserver/ows"
                "?service=WFS&typeNames=rv:c0104011_comuni"
            ),
            "features": features,
        },
    )
    return {"output": str(output_path), "municipalities": len(features)}


def download(
    manifest_path: Path,
    raw_dir: Path,
    *,
    service_filter: str | None = None,
    max_services: int | None = None,
    dry_run: bool = False,
    refresh: bool = False,
    progress: Progress | None = None,
    call_event: CallEvent | None = None,
) -> dict[str, Any]:
    summary = wfs_generic.download(
        manifest_path,
        raw_dir,
        service_filter=service_filter,
        max_services=max_services,
        dry_run=dry_run,
        refresh=refresh,
        progress=progress,
        call_event=call_event,
    )
    if not dry_run:
        overlay = _update_current_municipalities(raw_dir)
        if overlay:
            summary["administrative_overlay"] = overlay
            manifest = json.loads(
                (raw_dir / "regione" / "r_veneto" / "_manifest.json").read_text("utf-8")
            )
            manifest["administrative_overlay"] = overlay
            wfs_generic._atomic_json(
                raw_dir / "regione" / "r_veneto" / "_manifest.json",
                manifest,
            )
    return summary
