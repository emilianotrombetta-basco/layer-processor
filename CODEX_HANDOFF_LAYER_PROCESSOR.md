# Handoff Codex — Layer_Processor (scala nazionale dei layer)

Aggiornato al 2026-07-27. Cartella: `/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor`.

## Cos'è

Sistema che **generalizza a tutta Italia** ciò che è stato fatto a mano su Torino/Piemonte. Data una
lista di URL (opendata di comuni/province/regioni, geoportali), la catena:

1. **scopre** gli endpoint dei dataset → 2. **scarica** i layer grezzi → 3. **riconosce** cosa sono
(dizionario formulazione→classe canonica) → 4. **compone** i layer riconosciuti in layer finali più
informativi **senza perdere la tracciabilità** → 5. **carica** su Supabase (riuso pipeline esistente).

Non è un monolite: **catena di stadi `.py` idempotenti** orchestrati da `run.py`, guidati da `registry/`.
Ogni stadio rigira solo se il suo input è cambiato (hash in `state/`). Ordine territoriale **duro**:
**regione → provincia (+ area metropolitana) → comune**.

Leggere prima: `Layer_Processor/README.md` (contratto completo) e `pipeline/PIPELINE_CONTRACT.md`.

## Decisioni già prese con l'utente (NON rimetterle in discussione)

- **Orchestrazione**: orchestratore a stadi + registry (idempotenza per hash).
- **Pilota**: **golden test su Piemonte/Torino** — il processore generalizzato deve **riprodurre** i layer
  `PIE-*` già noti della demo, usando i dati già scaricati in `../Nord/piemonte/`.
- **Dizionario**: tassonomia canonica curata a mano + matcher a **proposta** (governance umana, niente
  auto-merge, come gli alias comuni). I non riconosciuti vanno in `work/proposals/` per revisione.

## Ambiente

```bash
cd "/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor"
python3 run.py recognize --catalog "../Nord/piemonte/_catalog.csv" --ente r_piemon
python3 run.py status
python3 -m py_compile run.py lib/*.py stages/*.py   # sintassi
```

- Python di sistema (stesso degli script Torino). Disponibili: `pyshp`(shapefile), `shapely`, `pyproj`,
  `openpyxl`, `pandas`, `yaml`. **`requests` NON è disponibile** → usare `urllib` (stdlib) per i download.
- PyYAML è stato installato con `pip install --break-system-packages pyyaml` (ambiente PEP 668).
- Credenziali Supabase: solo da `.env`/`.env.local`, **mai stampare, mai committare**.

---

## GIÀ FATTO in questa sessione (contesto, NON rifare)

Scaffold completo e stadio 03 funzionante. Albero:

```
Layer_Processor/
  README.md                    contratto del processore
  run.py                       orchestratore: subcomandi `recognize`, `status`; idempotenza via lib/state
  requirements.txt  .gitignore
  registry/
    canonical_taxonomy.yaml    34 classi FINALI, con macro(1..4), plan_type, geometry, topics, torino_ref (PIE-*)
    layer_dictionary.yaml      regole formulazione→canonico: any/all/not_any/topic_in/confidence/examples
    sources.yaml               fonti: key(prefisso r_/p_/c_/n_), livello, ente, kind, url, plan_types
  lib/
    normalize.py               norm_name (comuni, = NORMALIZATION_RULES.md) · norm_match (titoli) · tokens
    recognize.py               Recognizer: match(title,topic)→Match(canonical,confidence,score,reason) o proposals
    state.py                   fingerprint file → is_up_to_date / mark_done
  stages/
    stage_03_recognize.py      ATTIVO: catalog CSV → work/recognition/<ente>.json + work/proposals/<ente>.json
    stage_01_discover.py       STUB (contratto in docstring)
    stage_02_download.py       STUB
    stage_04_compose.py        STUB  ← prossimo lavoro
    stage_05_load.py           STUB
  raw/ work/ out/ state/       gitignored
```

Verifica pilota già eseguita: `recognize` su `../Nord/piemonte/_catalog.csv` = **945 dataset, ~35% riconosciuti**;
il resto è per lo più rumore fuori scope (foto aeree, DTM, collegi elettorali) + buchi dizionario in
`work/proposals/r_piemon.json`. Il matcher ha già i guard-rail: valida che ogni regola punti a una classe
esistente; filtra le stopword nelle proposte.

### Riuso dall'ecosistema (fondamentale, non reinventare)

| Serve a | File esistente |
|---|---|
| Normalizzazione nome comune → `codice_istat` | `pipeline/aliases/` (`comune_aliases.csv`, `comune_exceptions.csv`, `NORMALIZATION_RULES.md`) + `pipeline/sql/03_comune_alias.sql` (`staging.match_comune`) |
| Gerarchia + geometrie ISTAT | `Geography_Locations/outputs/admin_{regions,provinces,municipalities}.geojson` |
| Carico Supabase atomico SCD2 | `pipeline/sql/01_staging.sql`, `02_promote.sql` + `pipeline/PIPELINE_CONTRACT.md` |
| Template di composizione (CRS, dissolve, classi, popup) | `~/Library/Application Support/PiemonteBeta/app/scripts/build_piemonte_*.py` |
| Dati grezzi Torino già scaricati | `Nord/piemonte/<topic>/<dataset>__<hash>/` (topic = categoria ISO) + `Nord/piemonte/_catalog.csv` |
| Fonti operative nazionali già scaricate | `Sources/OpenCUP/`, `Sources/PNRR/`, `Sources/AINOP - MIT/`, `Sources/opencup Regionale/` |

---

## DA FARE (in ordine)

### 1) `stage_04_compose.py` — chiudere il golden test  ← PRIORITÀ

Obiettivo: da `work/recognition/r_piemon.json` produrre i layer canonici in `out/<CLASSE>/<territorio>.geojson`
e verificare che riproducano i `PIE-*` noti (colonna `torino_ref` in `canonical_taxonomy.yaml`).

Contratto:
- **Input**: `work/recognition/<ente>.json` (ogni item ha `uuid,title,topic,url,ente,livello,canonical_key,confidence`).
- **Risoluzione file locale**: mappare ogni item al file grezzo in `Nord/piemonte/<topic>/<cartella>/`.
  La cartella è `<Titolo_sanitizzato>__<hash8>`; l'hash8 è il suffisso già presente nei nomi cartella.
  Se il match titolo→cartella è ambiguo, costruire un indice una-tantum (scan di `Nord/piemonte/**`, chiave =
  `norm_match(title)`), e loggare i non risolti. (In regime, sarà `stage_02_download` a scrivere il
  `local_path` nel manifest; per il pilota serve questo resolver.)
- **Lettura geometrie**: shapefile via `pyshp`; GeoPackage via `sqlite3` + `shapely.wkb` con parsing header GPKG
  (vedi `build_piemonte_dissesto.py`/`build_piemonte_energia.py`). Zip **Deflate64** → estrarre con `unzip` di
  sistema (Python `zipfile` e `jar` falliscono).
- **CRS → WGS84 (EPSG:4326)**: rilevare per file. In Piemonte prevale 32632, ma alcuni sono **3003 (Monte Mario)**
  (es. grafo stradale) → `pyproj.Transformer` per-file, non assumere 32632.
- **Comune → `codice_istat`**: normalizzare via `norm_name` + gli alias `pipeline/aliases/`. I non abbinati non
  vanno inventati: confronto con `comune_exceptions.csv`, altrimenti si segnala.
- **Ordine territoriale + fill-down**: comporre regione, poi provincia(+area metro), poi comune. Dove esiste il
  dettaglio comunale prevale sul regionale; il livello di provenienza resta **tracciato** su ogni feature.
- **Tracciabilità (obbligatoria)**: ogni feature del layer canonico porta almeno
  `source_uuid, source_title, ente, livello, url, topic, canonical_key, match_confidence`.
- **Classi semantiche interne** (le classi accendibili/spegnibili della demo) guidate da `canonical_taxonomy.yaml`;
  riusare la logica di `classification()` degli script Torino come riferimento.
- **Output**: `out/<CLASSE>/<territorio>.geojson` + `out/<CLASSE>/_manifest.json` (fonti aggregate, conteggi).
- **Idempotenza**: `lib/state.py`, chiave per (classe, territorio), dipendenze = recognition + file grezzi + registry.
- **Accettazione golden test**: per una classe pilota (consiglio `RISCHIO_IDRAULICO` o `AREE_PROTETTE`), il numero
  di feature e la copertura devono essere coerenti coi `PIE-*` corrispondenti della demo. Loggare un confronto.

Aggiungere il subcomando `compose` a `run.py` (stessa forma di `recognize`).

### 2) Estendere il dizionario dai proposals

Rivedere `work/proposals/r_piemon.json` e promuovere le regole ovvie in `registry/layer_dictionary.yaml`.
Cluster più grande: famiglia **PPR** (tavole P2/P4/P5/P6, ~150 dataset) — attenzione a separare paesaggistico
(`VINCOLI_PAESAGGISTICI`) da ecologico (`RETE_ECOLOGICA`) e acque (`ACQUE`). Regola: aggiungere keyword
**specifiche**, mai `ppr` nudo (sovra-cattura). Ogni aggiunta con `examples` reali. Nessun alias ambiguo
(una formulazione → una sola classe). Ri-verificare con `run.py recognize --force`.

### 3) `stage_05_load.py` — carico Supabase

Seguire `pipeline/PIPELINE_CONTRACT.md`: staging → **dry-run con ROLLBACK** (report, nessuna scrittura) →
`promote` atomico SCD2 → `REFRESH MATERIALIZED VIEW CONCURRENTLY`. **Mai** scrivere sul DB senza dry-run
approvato dall'utente. Upsert per chiave naturale (idempotente). Agganciare i layer tematici al territorio via
`codice_istat`/`area_id`. `psycopg2-binary` da aggiungere quando si implementa.

### 4) `stage_01_discover.py` + `stage_02_download.py` — per territori nuovi

Solo quando si esce dal pilota Torino. `discover` per `kind`: `ckan` (`/api/3/action/package_search`),
`arcgis_rest` (`/rest/services?f=json` → `/query`), `wfs` (GetCapabilities→GetFeature), `geoportal_download`
(indice geoportale). `download` in `raw/<livello>/<ente>/…` + `_manifest.json` + `_non_recuperati.csv`
(come `Nord/piemonte/_non_recuperati.csv`). Output di `discover` = CSV **schema Torino**
(`uuid,title,topic,url,local_path_or_status,bytes`) così `recognize` funziona identico su ogni ente.

## Gotcha (dagli script Torino)

- **Deflate64**: `unzip` di sistema, non `zipfile`/`jar`.
- **CRS**: rilevare per file; 3003 (Monte Mario) oltre a 32632; output sempre 4326.
- **Encoding shapefile**: alcuni richiedono `shapefile.Reader(..., encoding="latin-1")`.
- **Layer enormi**: non caricare geometrie complete pesanti; per UI servono overview (regola della demo).
- **`requests` assente** → `urllib`. **PyYAML** installato con `--break-system-packages`.
- **Credenziali**: mai stampare/committare `.env*`.

## Definizione di "fatto" per il pilota

`run.py compose` produce `out/<CLASSE>/…` per almeno le classi di Macro 2 (ambiente/tutele/rischi) con
tracciabilità per-feature, e il confronto con i `PIE-*` noti (`torino_ref`) è coerente. Poi si valuta il `load`.
