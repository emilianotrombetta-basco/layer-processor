"""Stadio 05 · LOAD  [STUB — contratto definito, non implementato].

Scopo: caricare i layer canonici (out/) su Supabase riusando la pipeline esistente.

Input : out/<canonical_key>/<territorio>.geojson
Output: righe in staging → (dry-run) → promote atomico → refresh MV

Vincoli (da ../pipeline/PIPELINE_CONTRACT.md):
  - MAI scrivere sul DB senza un DRY-RUN approvato: le validazioni girano dentro una
    transazione con ROLLBACK e producono un report;
  - promozione ATOMICA e SCD2 (le riforme amministrative chiudono la versione, non cancellano);
  - upsert per chiave naturale (idempotente); refresh MV CONCURRENTLY fuori dalla transazione;
  - la geografia (regione/provincia/comune) è già coperta dal contratto pipeline; qui si aggiungono
    i layer tematici canonici, agganciati al territorio via codice_istat/area_id.

Credenziali Supabase: da .env locale, MAI stampate/committate.
"""
from __future__ import annotations


def run(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError(
        "stage_05_load: da implementare. Nessuna scrittura sul DB senza dry-run approvato "
        "(vedi ../pipeline/PIPELINE_CONTRACT.md)."
    )
