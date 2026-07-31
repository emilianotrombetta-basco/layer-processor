"""Stadio 04 · COMPOSE  [contratto dei prodotti finali].

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

I tre obiettivi correnti e le relative regole sono in
``registry/composition_targets.yaml``. Il file include anche il gate di
copertura che impedisce di classificare come verde un territorio non
completamente verificato.
"""
from __future__ import annotations

from typing import Any, Callable

from lib import compose_engine


def run(
    targets: list[str] | None = None,
    scope: dict[str, Any] | None = None,
    progress: Callable[[int, int], None] | None = None,
    call_event: Callable[[dict[str, Any]], None] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Compone i target selezionati per il territorio dello scope.

    Ogni target viene eseguito separatamente: un input mancante blocca soltanto
    quel prodotto e resta visibile nel riepilogo della run.
    """
    selected = list(targets or [])
    territory = dict(scope or {})
    if not selected:
        raise ValueError("Selezionare almeno un target di composizione.")
    results: list[dict[str, Any]] = []
    total = len(selected)
    for index, target in enumerate(selected, start=1):
        if call_event:
            call_event({
                "id": f"compose:{target}:{territory.get('key', '')}",
                "label": target,
                "status": "running",
                "current": index - 1,
                "total": total,
            })
        try:
            result = compose_engine.compose_target(target, territory)
        except Exception as exc:
            result = {"target": target, "status": "failed", "message": str(exc)}
        results.append(result)
        if call_event:
            call_event({
                "id": f"compose:{target}:{territory.get('key', '')}",
                "label": target,
                "status": result.get("status", "completed"),
                "current": index,
                "total": total,
                "message": result.get("message", ""),
            })
        if progress:
            progress(index, total)
    failed = [r for r in results if r.get("status") in {"failed", "blocked"}]
    partial = [r for r in results if r.get("status") == "partial"]
    status = "completed"
    if len(failed) == len(results):
        status = "failed"
    elif failed or partial:
        status = "partial"
    return {
        "status": status,
        "message": f"Composizione terminata: {len(results) - len(failed)}/{len(results)} target prodotti.",
        "targets": selected,
        "scope": territory,
        "results": results,
    }
