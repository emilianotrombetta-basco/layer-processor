"""Adapter per le ``CARTE TEMATICHE`` del Geoportale Regione Liguria.

Il portale GV2 espone un catalogo JSON pubblico. Ogni voce del catalogo rimanda
alla configurazione ufficiale della mappa, che contiene layer, WMS/WFS e flag di
download. Il discovery salva sia le 350 mappe sia i singoli layer, senza
dipendere dall'interazione con la pagina grafica.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]
USER_AGENT = "LayerProcessor/1.0 (+local territorial data pipeline)"


def _request_json(url: str, *, attempts: int = 3, timeout: int = 90) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict) and payload.get("success") is False:
                raise RuntimeError(str(payload.get("message") or "risposta senza successo"))
            return payload
        except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"Impossibile leggere {url}: {last_error}")


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
        "source_service",
        "layer_key",
        "metadata_url",
        "download_mode",
        "download_url",
        "objectid",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _maps_in_category(node: dict[str, Any], category: str = "") -> list[dict[str, Any]]:
    current_category = category
    if node.get("type") == "CATEGORIA":
        current_category = str(node.get("text") or category)
    rows: list[dict[str, Any]] = []
    if node.get("type") == "MAPPA":
        rows.append(
            {
                "id": int(node["id"]),
                "name": str(node.get("text") or f"Mappa {node['id']}"),
                "category": current_category,
            }
        )
    for child in node.get("children", []):
        rows.extend(_maps_in_category(child, current_category))
    return rows


def _primary_layers(map_config: dict[str, Any], map_row: dict[str, Any]) -> list[dict[str, Any]]:
    data = map_config.get("data") or {}
    layers = []
    for layer in data.get("layers", []):
        wms = layer.get("wmsParams") or {}
        wfs = layer.get("wfsParams") or {}
        layer_id = int(layer.get("id") or 0)
        wfs_url = str(wfs.get("url") or "")
        type_name = str(wfs.get("typeName") or "")
        layers.append(
            {
                "map_id": int(map_row["id"]),
                "map_name": str(data.get("name") or map_row["name"]),
                "category": map_row["category"],
                "layer_id": layer_id,
                "layer_name": str(layer.get("title") or layer.get("name") or layer_id),
                "layer_key": str(layer.get("name") or type_name or layer_id),
                "type": str(layer.get("type") or ""),
                "geometry_type": str(layer.get("geomSubType") or layer.get("geomType") or ""),
                "queryable": bool(layer.get("queryable")),
                "downloadable": bool(layer.get("flagDownload") and wfs_url and type_name),
                "wms_url": str(wms.get("url") or ""),
                "wfs_url": wfs_url,
                "type_name": type_name,
                "map_downloadable": bool(data.get("flagDownload")),
                "metadata_url": "",
            }
        )
    return layers


def discover(
    source: dict[str, Any],
    _status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Legge le Carte tematiche e risolve in parallelo le 350 configurazioni."""
    catalog = _request_json(str(source["catalog_endpoint"]))
    root = catalog.get("data") or {}
    thematic = next(
        (
            item
            for item in root.get("children", [])
            if _norm(str(item.get("text") or "")) == _norm(str(source["catalog_section"]))
        ),
        None,
    )
    if not thematic:
        raise RuntimeError(f"Sezione non trovata: {source['catalog_section']}")

    maps = _maps_in_category(thematic)
    thematic_count = len(maps)
    # Mappe extra fuori dalla sezione CARTE TEMATICHE (es. app Piano Paesaggistico
    # Regionale) ma servite dallo stesso map_config_endpoint: le aggiungiamo al
    # discovery per id, così i loro layer WFS entrano nel catalogo come gli altri.
    known_ids = {item["id"] for item in maps}
    for extra in source.get("extra_maps") or []:
        extra_id = int(extra["id"] if isinstance(extra, dict) else extra)
        if extra_id in known_ids:
            continue
        known_ids.add(extra_id)
        maps.append(
            {
                "id": extra_id,
                "name": str(
                    (extra.get("name") if isinstance(extra, dict) else "")
                    or f"Mappa {extra_id}"
                ),
                "category": str(
                    (extra.get("category") if isinstance(extra, dict) else "")
                    or "MAPPE EXTRA"
                ),
            }
        )
    endpoint = str(source["map_config_endpoint"]).rstrip("/")
    configurations: dict[int, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    total = len(maps)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_request_json, f"{endpoint}/{item['id']}"): item
            for item in maps
        }
        for current, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                configurations[item["id"]] = future.result()
            except Exception as exc:
                failures.append(
                    {"map_id": item["id"], "map_name": item["name"], "error": str(exc)}
                )
            if progress:
                progress(current, total)

    layers: list[dict[str, Any]] = []
    map_manifest: list[dict[str, Any]] = []
    for item in maps:
        config = configurations.get(item["id"])
        item_layers = _primary_layers(config, item) if config else []
        resolved_name = str(((config or {}).get("data") or {}).get("name") or item["name"])
        layers.extend(item_layers)
        map_manifest.append(
            {
                **item,
                "name": resolved_name,
                "status": "discovered" if config else "failed",
                "layer_count": len(item_layers),
                "downloadable_layers": sum(layer["downloadable"] for layer in item_layers),
            }
        )

    rows = []
    for layer in layers:
        access_url = layer["wfs_url"] or layer["wms_url"] or source["url"]
        rows.append(
            {
                "uuid": f"r_liguria:M{layer['map_id']}:L{layer['layer_id']}",
                "title": layer["layer_name"],
                "topic": layer["category"],
                "url": access_url,
                "local_path_or_status": "discovered",
                "bytes": 0,
                "source_service": layer["map_name"],
                "layer_key": layer["layer_key"],
                "metadata_url": layer["metadata_url"],
                "download_mode": "wfs" if layer["downloadable"] else "view_only",
                "download_url": layer["wfs_url"],
                "objectid": layer["layer_id"],
            }
        )

    catalog_path = work_dir / "catalog" / "r_liguria.csv"
    manifest_path = work_dir / "catalog" / "r_liguria_services.json"
    _atomic_csv(catalog_path, rows)
    _atomic_json(
        manifest_path,
        {
            "source": "r_liguria",
            "source_page": source["url"],
            "catalog_endpoint": source["catalog_endpoint"],
            "catalog_section": source["catalog_section"],
            "maps": map_manifest,
            "layers": layers,
            "failures": failures,
        },
    )
    expected = int(source.get("expected_map_count") or 0)
    missing_maps = max(expected - thematic_count, 0) if expected else 0
    status = "completed" if not failures and not missing_maps else "partial"
    return {
        "status": status,
        "message": (
            f"Scoperta completata: {len(maps)} mappe tematiche, "
            f"{len(layers)} layer, {len(failures)} errori."
        ),
        "catalog": str(catalog_path),
        "manifest": str(manifest_path),
        "maps": len(maps),
        "layers": len(layers),
        "downloadable_layers": sum(layer["downloadable"] for layer in layers),
        "failed_maps": len(failures),
        "failures": failures,
        "missing_maps": missing_maps,
    }


def _wfs_url(
    layer: dict[str, Any],
    *,
    start_index: int = 0,
    count: int = 2000,
    result_type: str | None = None,
) -> str:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "srsName": "EPSG:4326",
        "outputFormat": "application/json",
        "typeNames": layer["type_name"],
        "startIndex": start_index,
        "count": count,
    }
    if result_type:
        params["resultType"] = result_type
        params.pop("outputFormat", None)
        params.pop("startIndex", None)
        params.pop("count", None)
    return f"{str(layer['wfs_url']).rstrip('?')}?{urlencode(params)}"


def _wfs_count(layer: dict[str, Any]) -> int | None:
    request = Request(_wfs_url(layer, result_type="hits"), headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=90) as response:
            root = ElementTree.fromstring(response.read())
        value = root.attrib.get("numberMatched") or root.attrib.get("numberOfFeatures")
        return int(value) if value and value.isdigit() else None
    except Exception:
        return None


def _download_wfs(
    layer: dict[str, Any],
    output_path: Path,
    *,
    batch_size: int = 2000,
    call_event: CallEvent | None = None,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".geojson.tmp")
    expected = _wfs_count(layer)
    feature_count = 0
    page = 0
    try:
        with temporary.open("w", encoding="utf-8") as target:
            target.write('{"type":"FeatureCollection","features":[')
            first = True
            while True:
                start = page * batch_size
                call_id = f"M{layer['map_id']}:L{layer['layer_id']}:P{page + 1}"
                label = f"{layer['layer_name']} · batch {page + 1}"
                if call_event:
                    call_event(
                        {
                            "id": call_id,
                            "label": label,
                            "status": "running",
                            "current": start,
                            "total": expected,
                        }
                    )
                request = Request(
                    _wfs_url(layer, start_index=start, count=batch_size),
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/geo+json,application/json",
                    },
                )
                try:
                    with urlopen(request, timeout=300) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                except Exception as exc:
                    if call_event:
                        call_event(
                            {
                                "id": call_id,
                                "label": label,
                                "status": "failed",
                                "error": str(exc),
                            }
                        )
                    raise
                if payload.get("type") != "FeatureCollection":
                    raise RuntimeError("la risposta WFS non è una FeatureCollection")
                features = payload.get("features", [])
                for feature in features:
                    if not first:
                        target.write(",")
                    json.dump(feature, target, ensure_ascii=False, separators=(",", ":"))
                    first = False
                feature_count += len(features)
                if call_event:
                    call_event(
                        {
                            "id": call_id,
                            "label": label,
                            "status": "completed",
                            "items": len(features),
                            "current": feature_count,
                            "total": expected,
                        }
                    )
                page += 1
                if len(features) < batch_size or (expected is not None and feature_count >= expected):
                    break
                if page > 100_000:
                    raise RuntimeError("limite di sicurezza paginazione WFS superato")
            target.write("]}")
        temporary.replace(output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "status": "downloaded",
        "features": feature_count,
        "batches": page,
        "bytes": output_path.stat().st_size,
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
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
    """Scarica via WFS i layer per cui il catalogo dichiara il download."""
    del token_env
    manifest = json.loads(manifest_path.read_text("utf-8"))
    layers = [item for item in manifest.get("layers", []) if item.get("downloadable")]
    if service_filter:
        query = _norm(service_filter)
        layers = [
            item
            for item in layers
            if query
            in _norm(
                " ".join(
                    [
                        str(item.get("map_name") or ""),
                        str(item.get("layer_name") or ""),
                        str(item.get("category") or ""),
                        str(item.get("layer_key") or ""),
                    ]
                )
            )
        ]
    output_root = raw_dir / "regione" / "r_liguria"

    def relative_path(layer: dict[str, Any]) -> Path:
        return (
            Path(f"M{layer['map_id']}_{_slug(layer['map_name'])}")
            / f"L{layer['layer_id']}_{_slug(layer['layer_name'])}.geojson"
        )

    all_layers = layers
    # Conteggi feature dell'ultima run (dal manifest), per il controllo "solo dati nuovi".
    prev_counts: dict[str, int] = {}
    prev_manifest = output_root / "_manifest.json"
    if prev_manifest.exists():
        try:
            for row in json.loads(prev_manifest.read_text("utf-8")).get("results", []):
                if row.get("map_id") is not None and isinstance(row.get("features"), int):
                    prev_counts[f"M{row['map_id']}:L{row['layer_id']}"] = row["features"]
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    def _local_count(layer: dict[str, Any]) -> int | None:
        prev = prev_counts.get(f"M{layer['map_id']}:L{layer['layer_id']}")
        if prev is not None:
            return prev
        path = output_root / relative_path(layer)
        if not path.exists():
            return None
        try:
            return len(json.loads(path.read_text("utf-8")).get("features", []))
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def _needs_download(layer: dict[str, Any]) -> bool:
        # "Solo dati nuovi": non basta la presenza del file. Si confronta il numero
        # di feature locale con quello del server (WFS hits); se il layer è cresciuto
        # o è cambiato (o manca il file) si riscarica. Alcuni layer si aggiornano più
        # spesso di altri: così non si perdono gli aggiornamenti.
        path = output_root / relative_path(layer)
        if not (path.exists() and path.stat().st_size):
            return True
        server = _wfs_count(layer)
        if server is None:
            return False
        return server != _local_count(layer)

    # default: solo i pendenti/aggiornati → "solo dati nuovi" / ripresa.
    # refresh: mantiene tutti i layer, riscaricandoli.
    if not refresh:
        layers = [layer for layer in all_layers if _needs_download(layer)]
    # max_services = quanti per esecuzione. Omesso o 0 = tutti i pendenti (in chunk).
    if max_services is not None and max_services > 0:
        layers = layers[: max_services]
    if dry_run:
        return {
            "status": "dry_run",
            "message": (
                f"Download simulato: {len(layers)} layer nel prossimo batch, "
                f"{len(all_layers)} complessivi."
            ),
            "layers": len(layers),
            "layers_total": len(all_layers),
        }

    results: list[dict[str, Any]] = []
    total = len(layers)

    def available_total() -> int:
        return sum(
            (output_root / relative_path(layer)).exists()
            and (output_root / relative_path(layer)).stat().st_size > 0
            for layer in all_layers
        )

    def checkpoint(status: str) -> None:
        failed = sum(item["status"] == "failed" for item in results)
        downloaded = available_total()
        _atomic_json(
            output_root / "_manifest.json",
            {
                "status": status,
                "message": (
                    f"Download {status}: {downloaded}/{len(all_layers)} layer disponibili, "
                    f"{failed} errori."
                ),
                "layers": len(all_layers),
                "batch_layers": total,
                "layers_downloaded": downloaded,
                "layers_failed": failed,
                "results": results,
            },
        )

    for current, layer in enumerate(layers, start=1):
        relative = relative_path(layer)
        output_path = output_root / relative
        if True:
            try:
                result = _download_wfs(
                    layer,
                    output_path,
                    batch_size=2000,
                    call_event=call_event,
                )
            except Exception as exc:
                result = {"status": "failed", "reason": str(exc)}
        results.append(
            {
                "map_id": layer["map_id"],
                "map_name": layer["map_name"],
                "layer_id": layer["layer_id"],
                "layer_name": layer["layer_name"],
                "source_url": layer["wfs_url"],
                "local_path": (
                    str(relative)
                    if result["status"] in {"downloaded", "skipped"}
                    else ""
                ),
                **result,
            }
        )
        checkpoint("running")
        if progress:
            progress(current, total)

    failed = sum(item["status"] == "failed" for item in results)
    downloaded = available_total()
    if failed:
        status = "partial"
    elif downloaded >= len(all_layers):
        status = "completed"
    else:
        status = "batch_completed"
    summary = {
        "status": status,
        "message": (
            f"Batch terminato: {len(results)} layer elaborati; "
            f"{downloaded}/{len(all_layers)} disponibili, {failed} errori."
        ),
        "layers": len(all_layers),
        "batch_layers": total,
        "layers_downloaded": downloaded,
        "layers_failed": failed,
        "results": results,
    }
    _atomic_json(output_root / "_manifest.json", summary)
    return summary
