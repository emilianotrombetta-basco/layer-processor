"""Stadio 01 · DISCOVER  [STUB — contratto definito, non implementato].

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

Nota pilota: NON serve per Torino/Piemonte (catalogo già presente in ../Nord/piemonte/_catalog.csv).
"""
from __future__ import annotations


def run(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError(
        "stage_01_discover: da implementare. Per il pilota Torino usare direttamente "
        "../Nord/piemonte/_catalog.csv."
    )
