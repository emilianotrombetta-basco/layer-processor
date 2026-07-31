"""Adapter generico per ArcGIS REST (Map/Feature Server interrogabili).

La fonte può dichiarare:

* un singolo ``arcgis_service`` con la relativa lista ``layers``;
* una collezione ``arcgis_services``. Ogni elemento ha ``key``, ``service`` e
  una propria lista ``layers``.

La seconda forma permette a un pulsante regionale di acquisire, in una sola run,
servizi complementari (per esempio il mosaico PGT e lo stato dei piani). Ogni
layer viene scaricato come GeoJSON via ``/query`` con paginazione a cursore OID.
"""
from __future__ import annotations

import csv
import hashlib
import json
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


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _slug(value: str) -> str:
    return _norm(value).replace(" ", "_") or "layer"


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    temporary.replace(path)


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "uuid",
        "title",
        "topic",
        "url",
        "local_path_or_status",
        "bytes",
        "service_key",
        "layer_id",
        "download_mode",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _previous_feature_counts(output_root: Path, id_key: str) -> dict[str, int]:
    """Conteggi feature per layer dall'``_manifest.json`` dell'ultima run."""
    manifest_path = output_root / "_manifest.json"
    counts: dict[str, int] = {}
    if manifest_path.exists():
        try:
            for row in json.loads(manifest_path.read_text("utf-8")).get("results", []):
                key = row.get(id_key)
                if key is not None and isinstance(row.get("features"), int):
                    counts[str(key)] = row["features"]
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return counts


def _feature_count_local(path: Path, prev_count: int | None) -> int | None:
    if prev_count is not None:
        return prev_count
    if not path.exists():
        return None
    try:
        return len(json.loads(path.read_text("utf-8")).get("features", []))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _get_json(url: str, *, attempts: int = 6, timeout: int = 300) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(min(2.0 * (attempt + 1), 15.0))  # backoff progressivo
    raise RuntimeError(f"ArcGIS REST non raggiungibile {url}: {last}")


def _source_layers(source: dict[str, Any], service: str) -> list[dict[str, Any]]:
    """Layer dichiarati in config, o tutti quelli interrogabili del servizio."""
    declared = source.get("layers") or []
    layers: list[dict[str, Any]] = []
    for item in declared:
        if isinstance(item, dict) and item.get("id") is not None:
            layers.append(
                {
                    "id": int(item["id"]),
                    "name": str(item.get("name") or f"layer_{item['id']}"),
                    **({"topic": str(item["topic"])} if item.get("topic") else {}),
                    **(
                        {"always_refresh": bool(item["always_refresh"])}
                        if item.get("always_refresh") is not None
                        else {}
                    ),
                }
            )
    if layers:
        return layers
    info = _get_json(f"{service.rstrip('/')}?f=json")
    include_ids = {
        int(layer_id)
        for layer_id in (source.get("include_layer_ids") or [])
    }
    id_range = source.get("layer_id_range") or []
    min_id = int(id_range[0]) if len(id_range) == 2 else None
    max_id = int(id_range[1]) if len(id_range) == 2 else None
    for lyr in info.get("layers", []):
        # I Group Layer/Annotation Layer compaiono nell'elenco del MapServer ma
        # non sono interrogabili come feature: il fallback deve escluderli.
        if lyr.get("type") != "Feature Layer":
            continue
        layer_id = int(lyr["id"])
        if include_ids and layer_id not in include_ids:
            continue
        if min_id is not None and not (min_id <= layer_id <= max_id):
            continue
        layers.append(
            {
                "id": layer_id,
                "name": str(lyr.get("name") or f"layer_{lyr['id']}"),
            }
        )
    return layers


def _source_services(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalizza fonte singola e collezione nello stesso schema interno."""
    declared = source.get("arcgis_services") or []
    if declared:
        services: list[dict[str, Any]] = []
        for index, item in enumerate(declared, start=1):
            if not isinstance(item, dict):
                continue
            service = str(item.get("service") or item.get("url") or "").rstrip("/")
            if not service:
                continue
            service_key = str(item.get("key") or f"service_{index}")
            services.append(
                {
                    "key": service_key,
                    "service": service,
                    "topic": str(item.get("topic") or source.get("topic") or "geoscientificInformation"),
                    "out_sr": int(item.get("out_sr") or source.get("out_sr") or 4326),
                    "page_size": int(item.get("page_size") or source.get("page_size") or 500),
                    "geometry_precision": int(
                        item.get("geometry_precision")
                        or source.get("geometry_precision")
                        or 8
                    ),
                    "layers": _source_layers(item, service),
                }
            )
        if not services:
            raise ValueError("arcgis_services non contiene servizi validi")
        return services

    service = str(source["arcgis_service"]).rstrip("/")
    return [
        {
            "key": "",
            "service": service,
            "topic": str(source.get("topic") or "geoscientificInformation"),
            "out_sr": int(source.get("out_sr") or 4326),
            "page_size": int(source.get("page_size") or 500),
            "geometry_precision": int(source.get("geometry_precision") or 8),
            "layers": _source_layers(source, service),
        }
    ]


def discover(source: dict[str, Any], _status_source: dict[str, Any] | None,
             work_dir: Path, progress: Progress | None = None) -> dict[str, Any]:
    key = str(source["key"])
    services = _source_services(source)
    collection = bool(source.get("arcgis_services"))
    failures: list[dict[str, Any]] = []
    for service_info in services:
        try:
            remote = _get_json(f"{service_info['service']}?f=json", attempts=2, timeout=90)
            if remote.get("error"):
                raise RuntimeError(str(remote["error"]))
            # Il listing radice del MapServer NON riporta il campo ``type`` per
            # ogni layer (compare solo interrogando /MapServer/<id>): filtrare per
            # ``type == "Feature Layer"`` qui svuoterebbe l'insieme e marcherebbe
            # ogni layer configurato come "non interrogabile". Un layer è una
            # foglia interrogabile quando NON è un gruppo (i gruppi hanno
            # ``subLayerIds``); accettiamo sia ``type`` assente sia "Feature Layer".
            remote_ids = {
                int(layer["id"])
                for layer in remote.get("layers", [])
                if layer.get("id") is not None
                and layer.get("type") in (None, "Feature Layer")
                and not layer.get("subLayerIds")
            }
            for layer in service_info["layers"]:
                if layer["id"] not in remote_ids:
                    failures.append(
                        {
                            "service": service_info["key"] or service_info["service"],
                            "layer_id": layer["id"],
                            "reason": "layer configurato non presente o non interrogabile",
                        }
                    )
        except Exception as exc:
            failures.append(
                {
                    "service": service_info["key"] or service_info["service"],
                    "reason": str(exc),
                }
            )
    layers: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for service_info in services:
        for layer in service_info["layers"]:
            item = {
                **layer,
                "service_key": service_info["key"],
                "service": service_info["service"],
                "topic": str(layer.get("topic") or service_info["topic"]),
                "out_sr": service_info["out_sr"],
                "page_size": service_info["page_size"],
                "geometry_precision": service_info["geometry_precision"],
                "downloadable": True,
            }
            item["layer_key"] = (
                f"{service_info['key']}:{layer['id']}"
                if service_info["key"]
                else str(layer["id"])
            )
            layers.append(item)
            rows.append(
                {
                    "uuid": (
                        f"{key}:{item['layer_key']}"
                        if collection
                        else f"{key}:{layer['id']}"
                    ),
                    "title": layer["name"],
                    "topic": item["topic"],
                    "url": f"{service_info['service']}/{layer['id']}",
                    "local_path_or_status": "discovered",
                    "bytes": 0,
                    "service_key": service_info["key"],
                    "layer_id": layer["id"],
                    "download_mode": "arcgis_query",
                }
            )
            if progress:
                progress(len(rows), sum(len(entry["layers"]) for entry in services))

    catalog_path = work_dir / "catalog" / f"{key}.csv"
    manifest_path = work_dir / "catalog" / f"{key}_services.json"
    _atomic_csv(catalog_path, rows)
    manifest = {
        "source": key,
        "livello": str(source.get("livello") or "regione"),
        "collection": collection,
        "services_count": len(services),
        "downloadable_count": len(layers),
        "failures": failures,
        "layers": layers,
    }
    # Manteniamo i campi legacy per manifest di fonti a servizio singolo.
    if not collection:
        manifest["arcgis_service"] = services[0]["service"]
        manifest["out_sr"] = services[0]["out_sr"]
    _atomic_json(manifest_path, manifest)
    return {
        "status": "partial" if failures else "completed",
        "message": (
            f"Scoperta ArcGIS completata: {len(services)} servizi, {len(layers)} layer"
            + (f", {len(failures)} anomalie." if failures else ".")
        ),
        "catalog": str(catalog_path), "manifest": str(manifest_path),
        "services": len(services), "layers": len(layers),
        "downloadable_layers": len(layers), "view_only_layers": 0,
        "missing_services": [], "failures": failures,
    }


def _ring_area(ring: list[list[float]]) -> float:
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _esri_to_geojson_geometry(geom: dict[str, Any] | None) -> dict[str, Any] | None:
    """Converte una geometria Esri JSON in GeoJSON. Serve quando il server ArcGIS
    ha ``f=geojson`` difettoso (ritorna vuoto oltre una soglia) e si usa ``f=json``."""
    if not geom:
        return None
    if "x" in geom and "y" in geom:
        return {"type": "Point", "coordinates": [geom["x"], geom["y"]]}
    if geom.get("paths") is not None:
        paths = geom["paths"]
        if len(paths) == 1:
            return {"type": "LineString", "coordinates": paths[0]}
        return {"type": "MultiLineString", "coordinates": paths}
    if geom.get("rings") is not None:
        # Esri: l'anello esterno è clockwise (area orientata negativa), i fori
        # sono counter-clockwise (area positiva). Raggruppo i fori sotto
        # l'ultimo esterno; più esterni → MultiPolygon.
        polygons: list[list[list[list[float]]]] = []
        for ring in geom["rings"]:
            if _ring_area(ring) < 0:
                polygons.append([ring])
            elif polygons:
                polygons[-1].append(ring)
            else:
                polygons.append([ring])
        if len(polygons) == 1:
            return {"type": "Polygon", "coordinates": polygons[0]}
        return {"type": "MultiPolygon", "coordinates": polygons}
    return None


def _layer_meta(service: str, layer_id: int) -> tuple[str, int | None]:
    """Ritorna (objectIdField, count). ``resultOffset`` è inaffidabile su alcuni
    server (si blocca a offset alti), quindi si pagina per cursore OBJECTID."""
    oid_field = "OBJECTID"
    try:
        info = _get_json(f"{service}/{layer_id}?f=json")
        oid_field = str(info.get("objectIdField") or "")
        if not oid_field:
            # Alcuni MapServer regionali hanno metadati anomali: objectIdField è
            # null e il vero OID va ricavato dal tipo del campo (es. stato PGT
            # Lombardia espone SHAPE come OID).
            oid_field = next(
                (
                    str(field["name"])
                    for field in info.get("fields", [])
                    if field.get("type") == "esriFieldTypeOID" and field.get("name")
                ),
                "OBJECTID",
            )
    except Exception:
        pass
    count = None
    try:
        q = urlencode({"where": "1=1", "returnCountOnly": "true", "f": "json"})
        count = int(_get_json(f"{service}/{layer_id}/query?{q}").get("count"))
    except Exception:
        pass
    return oid_field, count


def _download_layer(service: str, layer: dict[str, Any], out_sr: int, output_path: Path,
                    *, page_size: int = 500, geometry_precision: int = 8,
                    call_event: CallEvent | None = None) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".geojson.tmp")
    oid_field, expected = _layer_meta(service, layer["id"])
    feature_count = 0
    page = 0
    last_oid = 0
    try:
        with temporary.open("w", encoding="utf-8") as target:
            target.write('{"type":"FeatureCollection","features":[')
            first = True
            while True:
                prefix = f"{layer.get('service_key')}:" if layer.get("service_key") else ""
                call_id = f"{prefix}L{layer['id']}:P{page + 1}"
                if call_event:
                    call_event({"id": call_id, "label": f"{layer['name']} · batch {page + 1}",
                                "status": "running", "current": feature_count, "total": expected})
                # Cursore per OBJECTID crescente (bypassa i limiti di resultOffset)
                # e f=json: il f=geojson di questo server è difettoso oltre una
                # soglia (ritorna vuoto), quindi si converte l'Esri JSON in locale.
                q = urlencode({
                    "where": f"{oid_field}>{last_oid}", "outFields": "*", "f": "json",
                    "outSR": out_sr, "orderByFields": f"{oid_field} ASC",
                    "resultRecordCount": page_size,
                    "geometryPrecision": geometry_precision,
                })
                try:
                    payload = _get_json(f"{service}/{layer['id']}/query?{q}", timeout=300)
                except Exception as exc:
                    if call_event:
                        call_event({"id": call_id, "label": layer["name"], "status": "failed", "error": str(exc)})
                    raise
                features = payload.get("features", [])
                if not features:
                    break
                for feature in features:
                    attrs = feature.get("attributes") or {}
                    gj = {
                        "type": "Feature",
                        "geometry": _esri_to_geojson_geometry(feature.get("geometry")),
                        "properties": attrs,
                    }
                    if not first:
                        target.write(",")
                    json.dump(gj, target, ensure_ascii=False, separators=(",", ":"))
                    first = False
                    oid = attrs.get(oid_field)
                    if isinstance(oid, (int, float)) and oid > last_oid:
                        last_oid = int(oid)
                feature_count += len(features)
                if call_event:
                    call_event({"id": call_id, "label": layer["name"], "status": "completed",
                                "items": len(features), "current": feature_count, "total": expected})
                page += 1
                if len(features) < page_size:
                    break
                if page > 500_000:
                    raise RuntimeError("limite di sicurezza paginazione ArcGIS superato")
            target.write("]}")
        temporary.replace(output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "status": "downloaded", "features": feature_count, "batches": page,
        "bytes": output_path.stat().st_size,
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }


def download(manifest_path: Path, raw_dir: Path, *, token_env: str | None = None,
             service_filter: str | None = None, max_services: int | None = None,
             dry_run: bool = False, refresh: bool = False,
             progress: Progress | None = None, call_event: CallEvent | None = None) -> dict[str, Any]:
    del token_env
    manifest = json.loads(manifest_path.read_text("utf-8"))
    legacy_service = str(manifest.get("arcgis_service") or "").rstrip("/")
    legacy_out_sr = int(manifest.get("out_sr") or 4326)
    livello = str(manifest.get("livello") or "regione")
    key = str(manifest.get("source") or manifest_path.stem.replace("_services", ""))
    manifest_layers = [
        layer for layer in manifest.get("layers", []) if layer.get("downloadable", True)
    ]
    all_layers = list(manifest_layers)

    if service_filter:
        query = _norm(service_filter)
        service_keys = {
            _norm(str(layer.get("service_key") or ""))
            for layer in all_layers
            if layer.get("service_key")
        }
        if query in service_keys:
            all_layers = [
                layer
                for layer in all_layers
                if _norm(str(layer.get("service_key") or "")) == query
            ]
        else:
            all_layers = [
                layer
                for layer in all_layers
                if query
                in _norm(
                    f"{layer.get('service_key', '')} {layer.get('id', '')} {layer.get('name', '')}"
                )
            ]

    output_root = raw_dir / livello / key

    def relative_path(layer: dict[str, Any]) -> Path:
        filename = f"L{layer['id']}_{_slug(layer['name'])}.geojson"
        return Path(_slug(str(layer["service_key"]))) / filename if layer.get("service_key") else Path(filename)

    # Conteggi dell'ultima run per il controllo "solo dati nuovi".
    prev_counts = _previous_feature_counts(output_root, "layer_key")
    legacy_counts = _previous_feature_counts(output_root, "layer_id")

    def layer_service(layer: dict[str, Any]) -> str:
        return str(layer.get("service") or legacy_service).rstrip("/")

    def layer_key(layer: dict[str, Any]) -> str:
        return str(
            layer.get("layer_key")
            or (
                f"{layer.get('service_key')}:{layer['id']}"
                if layer.get("service_key")
                else layer["id"]
            )
        )

    def _needs_download(layer: dict[str, Any]) -> bool:
        # Modalità "solo dati nuovi": confronta il conteggio locale con quello del
        # server (returnCountOnly). Se il layer è cresciuto/cambiato (o manca il
        # file) lo si riscarica — utile per i layer che si aggiornano spesso.
        # Per layer di stato/configurazione il conteggio può restare invariato
        # mentre cambiano gli attributi: ``always_refresh`` evita falsi "già
        # aggiornato" senza imporre il refresh a tutti i layer geometrici pesanti.
        if layer.get("always_refresh"):
            return True
        path = output_root / relative_path(layer)
        if not (path.exists() and path.stat().st_size):
            return True
        _oid, server = _layer_meta(layer_service(layer), layer["id"])
        if server is None:
            return False
        previous = prev_counts.get(layer_key(layer))
        if previous is None and not layer.get("service_key"):
            previous = legacy_counts.get(str(layer["id"]))
        local = _feature_count_local(path, previous)
        return server != local

    if refresh:
        layers = all_layers
    else:
        layers = [l for l in all_layers if _needs_download(l)]
    if max_services is not None and max_services > 0:
        layers = layers[:max_services]

    if dry_run:
        return {"status": "dry_run",
                "message": (
                    f"Download simulato: {len(layers)} layer da (ri)scaricare, "
                    f"{len(all_layers)} nella selezione, {len(manifest_layers)} complessivi."
                ),
                "layers": len(layers), "selected_layers": len(all_layers),
                "layers_total": len(manifest_layers)}

    results: list[dict[str, Any]] = []
    total = len(layers)
    previous_summary: dict[str, Any] = {}
    previous_manifest_path = output_root / "_manifest.json"
    if previous_manifest_path.exists():
        try:
            previous_summary = json.loads(previous_manifest_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_summary = {}

    def available_total() -> int:
        return sum((output_root / relative_path(l)).exists()
                   and (output_root / relative_path(l)).stat().st_size > 0
                   for l in manifest_layers)

    for current, layer in enumerate(layers, start=1):
        output_path = output_root / relative_path(layer)
        service = layer_service(layer)
        out_sr = int(layer.get("out_sr") or legacy_out_sr)
        page_size = int(layer.get("page_size") or 500)
        geometry_precision = int(layer.get("geometry_precision") or 8)
        try:
            result = _download_layer(
                service,
                layer,
                out_sr,
                output_path,
                page_size=page_size,
                geometry_precision=geometry_precision,
                call_event=call_event,
            )
        except Exception as exc:
            result = {"status": "failed", "reason": str(exc)}
        results.append(
            {
                "layer_key": layer_key(layer),
                "service_key": layer.get("service_key") or "",
                "layer_id": layer["id"],
                "name": layer.get("name"),
                "source_url": f"{service}/{layer['id']}",
                "local_path": (
                    str(relative_path(layer))
                    if result["status"] in {"downloaded", "skipped"}
                    else ""
                ),
                **result,
            }
        )
        if progress:
            progress(current, total)

    # Il manifest è cumulativo: un batch o filtro mirato non deve cancellare i
    # risultati già conclusi, altrimenti la dashboard e la ripresa perdono lo
    # stato degli altri servizi.
    merged_results: dict[str, dict[str, Any]] = {}
    for item in previous_summary.get("results", []):
        previous_key = str(
            item.get("layer_key")
            or (
                f"{item.get('service_key')}:{item.get('layer_id')}"
                if item.get("service_key")
                else item.get("layer_id")
            )
        )
        merged_results[previous_key] = item
    for item in results:
        merged_results[str(item["layer_key"])] = item

    failed = sum(item["status"] == "failed" for item in results)
    downloaded = available_total()
    status = (
        "partial"
        if failed
        else (
            "completed"
            if downloaded >= len(manifest_layers)
            else "batch_completed"
        )
    )
    summary = {"status": status,
               "message": f"Batch ArcGIS terminato: {len(results)} layer; {downloaded}/{len(manifest_layers)} disponibili, {failed} errori.",
               "layers": len(manifest_layers), "selected_layers": len(all_layers),
               "batch_layers": total, "layers_downloaded": downloaded,
               "layers_failed": failed, "results": list(merged_results.values())}
    _atomic_json(output_root / "_manifest.json", summary)
    return summary
