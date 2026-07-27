"""Stadio 04 · COMPOSE  [STUB — contratto definito, non implementato].

Scopo: accorpare i layer riconosciuti nella STESSA classe canonica in un layer finale
più informativo, per territorio, SENZA perdere la tracciabilità dell'origine.

Input : work/recognition/<ente>.json  (+ dati grezzi in raw/ o ../Nord/<regione>/)
Output: out/<canonical_key>/<territorio>.geojson  + out/<canonical_key>/_manifest.json

Regole:
  - riproiezione a WGS84 (EPSG:4326); i sorgenti sono spesso 32632 o 3003 (Monte Mario)
    → rilevare il CRS per file (lezione dal grafo stradale Torino);
  - normalizzare il comune via gli alias esistenti (pipeline/aliases/) → codice_istat;
  - ORDINE territoriale e fill-down: regione → provincia(+area metro) → comune; dove esiste
    il dettaglio comunale, prevale sul regionale, ma il livello resta tracciato;
  - TRACCIABILITÀ obbligatoria: ogni feature porta
    source_uuid, source_title, ente, livello, url, topic, canonical_key, match_confidence;
  - classificazione semantica interna (le "classi da accendere/spegnere") come nella demo Torino,
    guidata da canonical_taxonomy.yaml.

Riferimento concettuale: gli script build_piemonte_*.py dell'app Torino.
"""
from __future__ import annotations


def run(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError("stage_04_compose: da implementare (prossimo passo del pilota).")
