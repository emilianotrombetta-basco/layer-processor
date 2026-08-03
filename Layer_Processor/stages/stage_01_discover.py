"""Stadio 01 · DISCOVER.

Scopo: da una fonte (registry/sources.yaml) risolvere gli ENDPOINT dei singoli dataset.

Input : una voce di registry/sources.yaml
Output: work/catalog/<ente>.csv  con schema Torino → uuid,title,topic,url,local_path_or_status,bytes
        (così lo stadio 03 può leggere qualsiasi ente con lo stesso formato di ../Nord/piemonte/_catalog.csv)

Per `kind`:
  geoportal_download : segue l'indice del geoportale (pagine/JSON) e raccoglie gli zip diretti
  ckan               : GET <url>/api/3/action/package_search → risorse
  arcgis_rest        : <url>/rest/services?f=json → layer → /query o /export
  wfs                : GetCapabilities → FeatureType → GetFeature
  national_dataset   : dataset unico già noto (OpenCUP/PNRR/PUMS/AINOP), nessuna scoperta

Implementato per gli adapter ``vda_sct`` e ``liguria_geoportal``.
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
    html_resources,
    http_download,
    istat_sdmx,
    liguria_geoportal,
    sparql_source,
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
    work_dir: Path,
    status_source: dict[str, Any] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    if source.get("adapter") == "ckan_mit":
        return ckan_mit.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "vda_platform":
        return vda_platform.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "vda_local":
        return vda_local.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "vda_sct":
        return vda_sct.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "liguria_geoportal":
        return liguria_geoportal.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "piemonte_catalog":
        return piemonte_catalog.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "wfs_generic":
        return wfs_generic.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "arcgis_rest":
        return arcgis_rest.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "ckan_collection":
        return ckan_collection.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "socrata":
        return socrata.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "websit_xml":
        return websit_xml.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "veneto_webgis":
        return veneto_webgis.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "emilia_romagna_moka":
        return emilia_romagna_moka.discover(
            source, status_source, work_dir, progress
        )
    if source.get("adapter") == "local_spatial":
        return local_spatial.discover(
            source, status_source, work_dir, progress
        )
    if source.get("adapter") == "csv_direct":
        return csv_direct.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "http_download":
        return http_download.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "html_resources":
        return html_resources.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "istat_sdmx":
        return istat_sdmx.discover(source, status_source, work_dir, progress)
    if source.get("adapter") == "sparql_source":
        return sparql_source.discover(source, status_source, work_dir, progress)
    raise NotImplementedError(
        f"stage_01_discover: adapter non implementato: {source.get('adapter') or source.get('kind')}"
    )
