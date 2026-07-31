"""Adapter per il Geoportale SCT della Valle d'Aosta.

Il catalogo e gli inventari sono pubblici. I MapServer con i FeatureClass
scaricabili da SCT-Outil richiedono invece un token ArcGIS: viene letto soltanto
dall'ambiente e non viene mai scritto nei cataloghi o nei log.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]
USER_AGENT = "LayerProcessor/1.0 (+local territorial data pipeline)"


def _request_json(url: str, *, attempts: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, dict) and data.get("error"):
                error = data["error"]
                raise RuntimeError(
                    f"servizio remoto: {error.get('code')} {error.get('message')}"
                )
            return data
        except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Impossibile leggere {url}: {last_error}")


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _slug(value: str) -> str:
    return _norm(value).replace(" ", "_") or "layer"


def _service_id(url: str) -> str:
    match = re.search(r"/([^/]+)/MapServer/?$", url, re.IGNORECASE)
    return match.group(1) if match else _slug(url)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    temporary.replace(path)


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "uuid",
        "title",
        "topic",
        "url",
        "local_path_or_status",
        "bytes",
        "source_service",
        "layer_key",
        "metadata_url",
        "download_mode",
        "download_url",
        "objectid",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Scarica catalogo servizi + inventario layer e crea il catalogo r_vda."""
    portal_catalog = _request_json(str(source["catalog_endpoint"]))
    ptp_catalog = _request_json(str(source["ptp"]["catalog_endpoint"]))
    inventory = _request_json(str(source["layer_inventory_url"]))
    download_inventory = _request_json(str(source["download_inventory_url"]))

    services: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    groups = (
        ("repertorio", portal_catalog.get("catalogo", {}).get("layers", [])),
        ("ptp", ptp_catalog.get("catalogo", {}).get("layers", [])),
    )
    for group, items in groups:
        for item in items:
            url = str(item.get("mapservice") or item.get("MAPSERVICE") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            name = str(item.get("name") or item.get("NAME") or _service_id(url)).strip()
            services.append(
                {
                    "id": _service_id(url),
                    "name": name,
                    "group": group,
                    "mapservice": url,
                }
            )

    if status_source:
        url = str(status_source["mapservice"]).rstrip("/")
        services.append(
            {
                "id": "prg_status",
                "name": "Iter di adeguamento PRG al PTP",
                "group": "prg_status",
                "mapservice": url,
                "layer_ids": [int(status_source["layer_id"])],
                "source_page": status_source["url"],
                "status_codes": status_source.get("status_codes", {}),
            }
        )

    expected = {_norm(item) for item in source.get("expected_services", [])}
    actual_portal = {
        _norm(str(item.get("name") or item.get("NAME") or ""))
        for item in portal_catalog.get("catalogo", {}).get("layers", [])
    }
    missing_services = sorted(expected - actual_portal)
    unexpected_services = sorted(actual_portal - expected)

    download_by_object: dict[str, dict[str, Any]] = {}
    for item in download_inventory.get("data", []):
        key = str(item.get("objectid", ""))
        aggregate = download_by_object.setdefault(
            key,
            {
                "professional": False,
                "public": False,
                "public_url": "",
                "record_ids": [],
            },
        )
        aggregate["professional"] |= bool(item.get("download_professionisti"))
        aggregate["public"] |= bool(item.get("download_pubblico"))
        aggregate["public_url"] = aggregate["public_url"] or item.get("url_download_pubblico") or ""
        if item.get("id") is not None:
            aggregate["record_ids"].append(item["id"])

    service_by_id = {item["id"].casefold(): item for item in services}
    catalog_rows: list[dict[str, Any]] = []
    inventory_rows = inventory.get("data", [])
    total = len(inventory_rows)
    for index, item in enumerate(inventory_rows, start=1):
        objectid = str(item.get("objectid", ""))
        download = download_by_object.get(objectid, {})
        service_name = str(item.get("mxd") or "")
        service = service_by_id.get(service_name.casefold())
        metadata_url = str(item.get("metadato") or "")
        mapservice = service["mapservice"] if service else ""
        if download.get("public_url"):
            mode = "public_url"
        elif download.get("professional"):
            mode = "sct_authenticated"
        else:
            mode = "metadata_only"
        catalog_rows.append(
            {
                "uuid": f"r_vda:{objectid}",
                "title": str(item.get("denominazione") or "").strip(),
                "topic": str(item.get("categoria_fe") or item.get("categoria") or ""),
                "url": mapservice or metadata_url or source["url"],
                "local_path_or_status": "discovered",
                "bytes": 0,
                "source_service": service_name,
                "layer_key": str(item.get("chiave_layer") or ""),
                "metadata_url": metadata_url,
                "download_mode": mode,
                "download_url": str(download.get("public_url") or ""),
                "objectid": objectid,
            }
        )
        if progress and (index == total or index % 10 == 0):
            progress(index, total)

    catalog_path = work_dir / "catalog" / "r_vda.csv"
    manifest_path = work_dir / "catalog" / "r_vda_services.json"
    _atomic_csv(catalog_path, catalog_rows)
    _atomic_json(
        manifest_path,
        {
            "source": "r_vda",
            "source_page": source["url"],
            "download_portal": source["download_portal"],
            "ptp_viewer": source["ptp"]["viewer_url"],
            "arcgis_token_env": source.get("arcgis_token_env", "VDA_ARCGIS_TOKEN"),
            "services": services,
            "inventory_count": len(catalog_rows),
            "service_counts": {
                "repertorio": sum(item["group"] == "repertorio" for item in services),
                "ptp": sum(item["group"] == "ptp" for item in services),
                "prg_status": sum(item["group"] == "prg_status" for item in services),
            },
            "registry_check": {
                "missing_services": missing_services,
                "unexpected_services": unexpected_services,
            },
        },
    )
    return {
        "catalog": str(catalog_path),
        "manifest": str(manifest_path),
        "services": len(services),
        "layers": len(catalog_rows),
        "missing_services": missing_services,
        "unexpected_services": unexpected_services,
    }


def _arcgis_url(base: str, path: str = "", **params: Any) -> str:
    url = f"{base.rstrip('/')}/{path.lstrip('/')}" if path else base.rstrip("/")
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return f"{url}?{urlencode(clean)}"


def _download_layer(
    service_url: str,
    layer_id: int,
    token: str,
    output_path: Path,
    *,
    service_id: str,
    layer_name: str,
    call_event: CallEvent | None = None,
) -> dict[str, Any]:
    layer_url = f"{service_url.rstrip('/')}/{layer_id}"
    info = _request_json(_arcgis_url(layer_url, f="json", token=token))
    if "Query" not in str(info.get("capabilities", "")):
        return {"status": "unsupported", "reason": "layer senza capability Query"}

    ids = _request_json(
        _arcgis_url(
            layer_url,
            "query",
            where="1=1",
            returnIdsOnly="true",
            f="json",
            token=token,
        )
    ).get("objectIds", [])
    batch_size = max(1, int(info.get("maxRecordCount") or 1000))
    features: list[dict[str, Any]] = []
    for start in range(0, len(ids), batch_size):
        batch = ids[start : start + batch_size]
        call_id = f"{service_id}:{layer_id}:{start // batch_size + 1}"
        if call_event:
            call_event(
                {
                    "id": call_id,
                    "label": f"{layer_name} · batch {start // batch_size + 1}",
                    "status": "running",
                    "current": start,
                    "total": len(ids),
                }
            )
        try:
            response = _request_json(
                _arcgis_url(
                    layer_url,
                    "query",
                    objectIds=",".join(map(str, batch)),
                    outFields="*",
                    returnGeometry="true",
                    outSR=4326,
                    f="geojson",
                    token=token,
                )
            )
        except Exception as exc:
            if call_event:
                call_event(
                    {
                        "id": call_id,
                        "label": f"{layer_name} · batch {start // batch_size + 1}",
                        "status": "failed",
                        "error": str(exc),
                    }
                )
            raise
        features.extend(response.get("features", []))
        if call_event:
            call_event(
                {
                    "id": call_id,
                    "label": f"{layer_name} · batch {start // batch_size + 1}",
                    "status": "completed",
                    "items": len(batch),
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(
        output_path,
        {
            "type": "FeatureCollection",
            "name": info.get("name"),
            "features": features,
        },
    )
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return {
        "status": "downloaded",
        "features": len(features),
        "bytes": output_path.stat().st_size,
        "sha256": digest,
    }


def download(
    manifest_path: Path,
    raw_dir: Path,
    *,
    token_env: str | None = None,
    service_filter: str | None = None,
    max_services: int | None = None,
    dry_run: bool = False,
    refresh: bool = False,
    progress: Progress | None = None,
    call_event: CallEvent | None = None,
) -> dict[str, Any]:
    """Esporta in GeoJSON tutti i layer interrogabili dei servizi SCT."""
    manifest = json.loads(manifest_path.read_text("utf-8"))
    env_name = token_env or manifest.get("arcgis_token_env") or "VDA_ARCGIS_TOKEN"
    token = os.environ.get(env_name, "")
    services = list(manifest.get("services", []))
    if service_filter:
        query = _norm(service_filter)
        services = [
            item
            for item in services
            if query in _norm(item["name"]) or query in _norm(item["id"])
        ]
    if max_services is not None:
        services = services[: max(0, max_services)]

    if dry_run:
        return {
            "status": "dry_run",
            "services": len(services),
            "token_available": bool(token),
        }

    output_root = raw_dir / "regione" / "r_vda"
    output_root.mkdir(parents=True, exist_ok=True)
    if not token:
        blocked = {
            "status": "authentication_required",
            "token_env": env_name,
            "download_portal": manifest.get("download_portal"),
            "services": [{"id": item["id"], "name": item["name"]} for item in services],
        }
        _atomic_json(output_root / "_auth_required.json", blocked)
        return {
            "status": "authentication_required",
            "services": len(services),
            "token_env": env_name,
            "manifest": str(output_root / "_auth_required.json"),
        }

    results: list[dict[str, Any]] = []
    total = len(services)
    for index, service in enumerate(services, start=1):
        service_url = service["mapservice"]
        try:
            service_info = _request_json(_arcgis_url(service_url, f="json", token=token))
            allowed_ids = set(service.get("layer_ids", []))
            layers = []
            for layer in service_info.get("layers", []):
                layer_id = int(layer["id"])
                if allowed_ids and layer_id not in allowed_ids:
                    continue
                if layer.get("subLayerIds"):
                    continue
                layers.append(layer)
            for layer in layers:
                layer_id = int(layer["id"])
                relative = Path(_slug(service["id"])) / f"{layer_id:03d}_{_slug(layer['name'])}.geojson"
                out_path = output_root / relative
                if not refresh and out_path.exists() and out_path.stat().st_size:
                    results.append({
                        "service": service["name"], "service_id": service["id"],
                        "layer_id": layer_id, "layer_name": layer["name"],
                        "local_path": str(relative), "status": "skipped",
                        "reason": "file già presente",
                    })
                    continue
                result = _download_layer(
                    service_url,
                    layer_id,
                    token,
                    output_root / relative,
                    service_id=service["id"],
                    layer_name=str(layer["name"]),
                    call_event=call_event,
                )
                results.append(
                    {
                        "service": service["name"],
                        "service_id": service["id"],
                        "service_url": service_url,
                        "layer_id": layer_id,
                        "layer_name": layer["name"],
                        "local_path": str(relative) if result["status"] == "downloaded" else "",
                        **result,
                    }
                )
        except Exception as exc:  # conserva gli altri servizi e rende visibile il fallimento
            results.append(
                {
                    "service": service["name"],
                    "service_id": service["id"],
                    "service_url": service_url,
                    "status": "failed",
                    "reason": str(exc),
                }
            )
        if progress:
            progress(index, total)

    summary = {
        "status": "completed",
        "services": total,
        "layers_downloaded": sum(item["status"] == "downloaded" for item in results),
        "layers_failed": sum(item["status"] == "failed" for item in results),
        "layers_unsupported": sum(item["status"] == "unsupported" for item in results),
        "results": results,
    }
    _atomic_json(output_root / "_manifest.json", summary)
    return summary
