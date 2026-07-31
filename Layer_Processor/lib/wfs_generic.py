"""Adapter WFS generico per una singola endpoint con più feature type.

A differenza di ``liguria_geoportal`` (che risolve un catalogo di mappe), qui la
fonte dichiara direttamente ``wfs_url`` e la lista dei ``type_names`` da scaricare
(oppure li si legge dal GetCapabilities). Ogni feature type diventa un layer
GeoJSON scaricato via GetFeature paginato. Riusa lo stesso schema di catalogo/
manifest degli altri adapter, così gli stadi 03/04 lo leggono senza modifiche.
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
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]
USER_AGENT = "LayerProcessor/1.0 (+local territorial data pipeline)"


def _apply_proxy(url: str, proxy_template: str | None) -> str:
    """Se la fonte richiede un proxy (es. webgis dietro host intranet), avvolge
    l'URL WFS reale nel template ``...?url={url}`` (URL-encoded)."""
    if not proxy_template:
        return url
    return proxy_template.replace("{url}", quote(url, safe=""))


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


def _previous_feature_counts(output_root: Path, id_key: str) -> dict[str, int]:
    """Conteggi feature per layer dall'``_manifest.json`` dell'ultima run, così il
    controllo 'solo dati nuovi' non deve riparsare i GeoJSON già scaricati."""
    manifest_path = output_root / "_manifest.json"
    counts: dict[str, int] = {}
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text("utf-8"))
            for row in data.get("results", []):
                key = row.get(id_key)
                if key is not None and isinstance(row.get("features"), int):
                    counts[str(key)] = row["features"]
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return counts


def _feature_count_local(path: Path, prev_count: int | None) -> int | None:
    """Numero di feature nel file locale: prima dal manifest, poi (fallback)
    contando dal GeoJSON. None se il file non esiste/illeggibile."""
    if prev_count is not None:
        return prev_count
    if not path.exists():
        return None
    try:
        return len(json.loads(path.read_text("utf-8")).get("features", []))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "uuid",
        "title",
        "topic",
        "url",
        "local_path_or_status",
        "bytes",
        "type_name",
        "download_mode",
        "download_url",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _capabilities_type_names(wfs_url: str, version: str, proxy_template: str | None = None) -> list[dict[str, str]]:
    """Legge i FeatureType dal GetCapabilities (fallback se non elencati in config)."""
    params = {"service": "WFS", "version": version, "request": "GetCapabilities"}
    target = f"{wfs_url.rstrip('?')}?{urlencode(params)}"
    request = Request(_apply_proxy(target, proxy_template), headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=90) as response:
        xml = response.read().decode("utf-8", "replace")
    layers: list[dict[str, str]] = []
    for block in re.findall(r"<(?:wfs:)?FeatureType\b(.*?)</(?:wfs:)?FeatureType>", xml, re.S):
        name = re.search(r"<(?:wfs:)?Name>(.*?)</", block, re.S)
        title = re.search(r"<(?:wfs:)?Title>(.*?)</", block, re.S)
        if name:
            layers.append({"name": name.group(1).strip(), "title": (title.group(1).strip() if title else name.group(1).strip())})
    return layers


def _source_layers(source: dict[str, Any]) -> list[dict[str, str]]:
    declared = source.get("type_names") or []
    layers: list[dict[str, str]] = []
    for item in declared:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            title = str(item.get("title") or name).strip()
            layer = {
                str(key): str(value)
                for key, value in item.items()
                if value is not None
            }
            layer.update({"name": name, "title": title})
        else:
            name = str(item).strip()
            title = name
            layer = {"name": name, "title": title}
        if name:
            # Conserva gli eventuali metadati per-layer (topic, gruppo, viewer):
            # gli adapter di cataloghi dinamici possono così migliorare il
            # riconoscimento senza duplicare il downloader WFS.
            layers.append(layer)
    if not layers:
        layers = _capabilities_type_names(
            str(source["wfs_url"]),
            str(source.get("wfs_version") or "2.0.0"),
            source.get("proxy_template"),
        )
    return layers


def discover(
    source: dict[str, Any],
    _status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Elenca i feature type WFS (da config o da GetCapabilities) nel catalogo."""
    key = str(source["key"])
    layers = _source_layers(source)
    rows = []
    for index, layer in enumerate(layers, start=1):
        rows.append(
            {
                "uuid": f"{key}:{layer['name']}",
                "title": layer["title"],
                "topic": str(
                    layer["topic"]
                    if "topic" in layer
                    else source.get("topic") or "planningCadastre"
                ),
                "url": str(source["wfs_url"]),
                "local_path_or_status": "discovered",
                "bytes": 0,
                "type_name": layer["name"],
                "download_mode": "wfs",
                "download_url": str(source["wfs_url"]),
            }
        )
        if progress:
            progress(index, len(layers))

    catalog_path = work_dir / "catalog" / f"{key}.csv"
    manifest_path = work_dir / "catalog" / f"{key}_services.json"
    _atomic_csv(catalog_path, rows)
    _atomic_json(
        manifest_path,
        {
            "source": key,
            "wfs_url": str(source["wfs_url"]),
            "wfs_version": str(source.get("wfs_version") or "2.0.0"),
            "output_format": str(source.get("output_format") or "application/json"),
            "srs": str(source.get("srs") or "EPSG:4326"),
            "feature_batch_size": int(source.get("feature_batch_size") or 2000),
            "proxy_template": source.get("proxy_template"),
            "livello": str(source.get("livello") or "regione"),
            "layers": [{**layer, "downloadable": True} for layer in layers],
        },
    )
    return {
        "status": "completed",
        "message": f"Scoperta WFS completata: {len(layers)} feature type.",
        "catalog": str(catalog_path),
        "manifest": str(manifest_path),
        "services": len(layers),
        "layers": len(layers),
        "downloadable_layers": len(layers),
        "view_only_layers": 0,
        "missing_services": [],
        "failures": [],
    }


def _get_feature_url(
    wfs_url: str,
    version: str,
    type_name: str,
    output_format: str,
    srs: str,
    *,
    start_index: int | None = 0,
    count: int = 2000,
    hits: bool = False,
) -> str:
    params: dict[str, Any] = {
        "service": "WFS",
        "version": version,
        "request": "GetFeature",
        "typeNames": type_name,
        "srsName": srs,
    }
    if hits:
        params["resultType"] = "hits"
    else:
        params["outputFormat"] = output_format
        # `startIndex` va OMESSO quando non serve paginare: su GeoServer, se la
        # tabella non ha primary key, `startIndex` forza l'"ordine naturale" che
        # non esiste → HTTP 400 ("Cannot do natural order without a primary key").
        # Passando start_index=None (pagina unica) si evita del tutto il problema.
        if start_index is not None:
            params["startIndex"] = start_index
        params["count"] = count
    # `safe=":/,"` lascia grezzi i due-punti/slash nei valori (typeNames, EPSG:4326,
    # application/json): così, quando l'URL viene poi avvolto in un proxy e
    # ri-codificato, non si ha doppia codifica che alcuni server (es. GeoServer
    # PAT dietro ogcproxy) rifiutano con HTTP 500.
    return f"{wfs_url.rstrip('?')}?{urlencode(params, safe=':/,')}"


def _feature_count(wfs_url: str, version: str, type_name: str, srs: str,
                   proxy_template: str | None = None) -> int | None:
    url = _get_feature_url(wfs_url, version, type_name, "", srs, hits=True)
    request = Request(_apply_proxy(url, proxy_template), headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=90) as response:
            root = ElementTree.fromstring(response.read())
        value = root.attrib.get("numberMatched") or root.attrib.get("numberOfFeatures")
        return int(value) if value and value.isdigit() else None
    except Exception:
        return None


def _download_layer(
    wfs_url: str,
    version: str,
    output_format: str,
    srs: str,
    layer: dict[str, str],
    output_path: Path,
    *,
    batch_size: int = 2000,
    proxy_template: str | None = None,
    call_event: CallEvent | None = None,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".geojson.tmp")
    expected = _feature_count(wfs_url, version, layer["name"], srs, proxy_template)
    feature_count = 0
    page = 0
    # Pagina unica quando tutte le feature entrano nel batch: in tal caso NON si
    # invia startIndex (evita l'errore GeoServer sulle tabelle senza primary key).
    single_page = expected is not None and expected <= batch_size
    try:
        with temporary.open("w", encoding="utf-8") as target:
            target.write('{"type":"FeatureCollection","features":[')
            first = True
            while True:
                start = page * batch_size
                call_id = f"{layer['name']}:P{page + 1}"
                if call_event:
                    call_event({"id": call_id, "label": f"{layer['title']} · batch {page + 1}",
                                "status": "running", "current": start, "total": expected})
                start_index = None if (single_page and page == 0) else start
                url = _get_feature_url(wfs_url, version, layer["name"], output_format, srs,
                                       start_index=start_index, count=batch_size)
                request = Request(_apply_proxy(url, proxy_template),
                                  headers={"User-Agent": USER_AGENT,
                                           "Accept": "application/geo+json,application/json"})
                try:
                    with urlopen(request, timeout=300) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                except Exception as exc:
                    if call_event:
                        call_event({"id": call_id, "label": layer["title"], "status": "failed", "error": str(exc)})
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
                    call_event({"id": call_id, "label": layer["title"], "status": "completed",
                                "items": len(features), "current": feature_count, "total": expected})
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
    """Scarica ogni feature type WFS come GeoJSON (GetFeature paginato)."""
    del token_env
    manifest = json.loads(manifest_path.read_text("utf-8"))
    wfs_url = str(manifest["wfs_url"])
    version = str(manifest.get("wfs_version") or "2.0.0")
    output_format = str(manifest.get("output_format") or "application/json")
    srs = str(manifest.get("srs") or "EPSG:4326")
    feature_batch_size = int(manifest.get("feature_batch_size") or 2000)
    proxy_template = manifest.get("proxy_template")
    livello = str(manifest.get("livello") or "provincia")
    key = str(manifest.get("source") or manifest_path.stem.replace("_services", ""))
    manifest_layers = [
        layer for layer in manifest.get("layers", []) if layer.get("downloadable", True)
    ]
    all_layers = manifest_layers

    if service_filter:
        query = _norm(service_filter)
        all_layers = [
            layer for layer in all_layers
            if query in _norm(f"{layer.get('name', '')} {layer.get('title', '')}")
        ]

    output_root = raw_dir / livello / key

    def relative_path(layer: dict[str, str]) -> Path:
        return Path(f"{_slug(layer['name'])}.geojson")

    # Conteggi feature dell'ultima run (per il controllo "solo dati nuovi").
    prev_counts = _previous_feature_counts(output_root, "type_name")

    def _local_count(layer: dict[str, str]) -> int | None:
        return _feature_count_local(output_root / relative_path(layer), prev_counts.get(layer["name"]))

    def _needs_download(layer: dict[str, str]) -> bool:
        # Modalità "solo dati nuovi": non basta che il file esista. Si confronta il
        # numero di feature locale con quello sul server (WFS hits); se il layer è
        # cresciuto/cambiato (o manca il file) lo si riscarica. Alcuni layer si
        # aggiornano più spesso di altri: così non li si perde.
        path = output_root / relative_path(layer)
        if not (path.exists() and path.stat().st_size):
            return True
        server = _feature_count(wfs_url, version, layer["name"], srs, proxy_template)
        if server is None:
            return False  # conteggio non determinabile: si mantiene il file esistente
        return server != _local_count(layer)

    if dry_run:
        pending = [layer for layer in all_layers if refresh or _needs_download(layer)]
        if max_services is not None and max_services > 0:
            pending = pending[:max_services]
        return {
            "status": "dry_run",
            "message": (
                f"Download simulato: {len(pending)} feature type da (ri)scaricare, "
                f"{len(manifest_layers)} complessivi"
                + (
                    f"; {len(all_layers)} corrispondono al filtro."
                    if service_filter
                    else "."
                )
            ),
            "layers": len(pending),
            "layers_total": len(manifest_layers),
            "filter_matched": len(all_layers),
        }

    def available_total() -> int:
        return sum(
            (output_root / relative_path(layer)).exists()
            and (output_root / relative_path(layer)).stat().st_size > 0
            for layer in manifest_layers
        )

    # Passaggio UNICO su tutti i layer, con progress per-layer. In modalità
    # "solo dati nuovi" (refresh=False) la verifica `_needs_download` (una WFS
    # 'hits' per layer) è la parte lenta: emettere progress qui fa avanzare la
    # barra durante il controllo, non solo durante il download. Così, anche
    # quando non c'è nulla di nuovo, la barra arriva a 100% (tutti verificati)
    # invece di restare a 0/0.
    results: list[dict[str, Any]] = []
    scan_total = len(all_layers)
    max_new = max_services if (max_services is not None and max_services > 0) else None

    for current, layer in enumerate(all_layers, start=1):
        wants = refresh or _needs_download(layer)
        capped = max_new is not None and len(results) >= max_new
        if wants and not capped:
            output_path = output_root / relative_path(layer)
            try:
                result = _download_layer(wfs_url, version, output_format, srs, layer, output_path,
                                         batch_size=feature_batch_size,
                                         proxy_template=proxy_template, call_event=call_event)
            except Exception as exc:
                result = {"status": "failed", "reason": str(exc)}
            results.append({
                "type_name": layer["name"],
                "title": layer.get("title"),
                "source_url": wfs_url,
                "local_path": str(relative_path(layer)) if result["status"] in {"downloaded", "skipped"} else "",
                **result,
            })
        if progress:
            progress(current, scan_total)

    total = len(results)
    failed = sum(item["status"] == "failed" for item in results)
    downloaded = available_total()
    if failed:
        status = "partial"
    elif downloaded >= len(manifest_layers):
        status = "completed"
    else:
        status = "batch_completed"
    summary = {
        "status": status,
        "message": f"Batch WFS terminato: {len(results)} feature type elaborati; "
                   f"{downloaded}/{len(manifest_layers)} disponibili, {failed} errori.",
        "layers": len(manifest_layers),
        "filter_matched": len(all_layers),
        "batch_layers": total,
        "layers_downloaded": downloaded,
        "layers_failed": failed,
        "results": results,
    }
    _atomic_json(output_root / "_manifest.json", summary)
    return summary
