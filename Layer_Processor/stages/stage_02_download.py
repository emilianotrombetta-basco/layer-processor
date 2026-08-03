"""Stadio 02 · DOWNLOAD.

Scopo: scaricare i dataset elencati nel catalogo dello stadio 01.

Input : work/catalog/<ente>.csv
Output: raw/<livello>/<ente>/<dataset>/...   + raw/<livello>/<ente>/_manifest.json
        _non_recuperati.csv per i link morti (come ../Nord/piemonte/_non_recuperati.csv)

Requisiti:
  - usare urllib (stdlib): 'requests' non è disponibile nell'ambiente;
  - gli zip Deflate64 vanno estratti con `unzip` di sistema (Python zipfile fallisce) —
    stessa lezione già appresa negli script Torino;
  - idempotenza per-dataset via hash dell'url + bytes (lib/state.py);
  - manifest per-feature-ready: ente, livello, url, topic, data, licenza, formato.

Implementato per ``vda_sct`` (ArcGIS REST) e ``liguria_geoportal`` (WFS).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from lib import (
    arcgis_rest,
    ckan_collection,
    ckan_mit,
    csv_direct,
    emilia_romagna_moka,
    http_download,
    sparql_source,
    liguria_geoportal,
    local_spatial,
    piemonte_catalog,
    socrata,
    veneto_webgis,
    vda_local,
    vda_platform,
    vda_sct,
    websit_xml,
    wfs_generic,
)


def run(
    source: dict[str, Any],
    *,
    manifest_path: Path,
    raw_dir: Path,
    service_filter: str | None = None,
    max_services: int | None = None,
    dry_run: bool = False,
    refresh: bool = False,
    progress: Callable[[int, int], None] | None = None,
    call_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if source.get("adapter") == "ckan_mit":
        return ckan_mit.download(
            source, raw_dir, refresh=refresh, max_services=max_services,
            dry_run=dry_run, progress=progress, call_event=call_event,
        )
    if source.get("adapter") == "vda_platform":
        return vda_platform.download(
            manifest_path, raw_dir, service_filter=service_filter,
            max_services=max_services, dry_run=dry_run, refresh=refresh,
            progress=progress, call_event=call_event,
        )
    if source.get("adapter") == "vda_local":
        return vda_local.download(
            manifest_path, raw_dir, dry_run=dry_run, refresh=refresh, progress=progress
        )
    if source.get("adapter") == "vda_sct":
        return vda_sct.download(
            manifest_path,
            raw_dir,
            token_env=source.get("arcgis_token_env"),
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "liguria_geoportal":
        return liguria_geoportal.download(
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "piemonte_catalog":
        return piemonte_catalog.download(
            source,
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "wfs_generic":
        return wfs_generic.download(
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "ckan_collection":
        return ckan_collection.download(
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "arcgis_rest":
        return arcgis_rest.download(
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "socrata":
        return socrata.download(
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "websit_xml":
        return websit_xml.download(
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "veneto_webgis":
        return veneto_webgis.download(
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "emilia_romagna_moka":
        return emilia_romagna_moka.download(
            source,
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "local_spatial":
        return local_spatial.download(
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "csv_direct":
        return csv_direct.download(
            manifest_path,
            raw_dir,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") in {"http_download", "html_resources", "istat_sdmx"}:
        # html_resources/istat_sdmx producono lo stesso manifest di http_download.
        return http_download.download(
            manifest_path,
            raw_dir,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    if source.get("adapter") == "sparql_source":
        return sparql_source.download(
            manifest_path,
            raw_dir,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )
    raise NotImplementedError(
        f"stage_02_download: adapter non implementato: {source.get('adapter') or source.get('kind')}"
    )
