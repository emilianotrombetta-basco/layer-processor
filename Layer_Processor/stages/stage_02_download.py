"""Stadio 02 · DOWNLOAD  [STUB — contratto definito, non implementato].

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

Nota pilota: NON serve per Torino/Piemonte (dati già in ../Nord/piemonte/).
"""
from __future__ import annotations


def run(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError(
        "stage_02_download: da implementare. Per il pilota Torino i dati sono già in "
        "../Nord/piemonte/."
    )
