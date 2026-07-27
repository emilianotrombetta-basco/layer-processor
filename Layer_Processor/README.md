# Layer_Processor — contratto del processore di layer

Scopo: **scalare a livello nazionale** ciò che è stato fatto a mano su Torino/Piemonte.
Dato un insieme di fonti (pagine opendata di comuni/province/regioni, geoportali), il processore:

1. **scopre** gli endpoint dei dataset,
2. **scarica** i layer grezzi,
3. **riconosce** quali layer sono (dizionario formulazione → classe canonica),
4. **compone** i layer riconosciuti in layer finali più informativi, **senza perdere la tracciabilità** dell'origine,
5. **carica** i layer canonici su Supabase (riuso della pipeline esistente).

Non è un monolite: è una **catena di stadi idempotenti** (script `.py`) orchestrati da `run.py`,
guidati dal `registry/`. Ogni stadio rigira solo se il suo input è cambiato (hash in `state/`).

---

## 0. Principi (ereditati dall'ecosistema esistente)

Riusiamo pattern già collaudati in questo repository, non li reinventiamo:

| Principio | Dove è già applicato | Come lo riusiamo |
|---|---|---|
| Dizionario formulazione → canonico, con tracciabilità e governance | `pipeline/aliases/` (nomi comune → `codice_istat`) | Stesso schema per i **layer**: `registry/layer_dictionary.yaml` |
| Normalizzazione deterministica `norm()` | `pipeline/aliases/NORMALIZATION_RULES.md` | `lib/normalize.py` (identica per i nomi; estesa ai titoli layer) |
| Gerarchia territoriale ISTAT + geometrie | `Geography_Locations/outputs/admin_*.geojson` | `lib/admin.py` (lookup regione/provincia/comune) |
| Staging → dry-run → promote atomico SCD2 → refresh MV | `pipeline/sql/`, `pipeline/PIPELINE_CONTRACT.md` | Stadio `05_load` (non tocca il DB senza OK) |
| Catalogo di download per ente/topic | `Nord/piemonte/_catalog.csv` | Schema del `registry/sources.yaml` |

---

## 1. Ordine territoriale (regola dura)

L'analisi incrocia piani a tre livelli. Il registry e la composizione li processano **in quest'ordine**:

```
1. REGIONE            (piani regionali: PPR, PTR, PAI/PGRA regionale, rete ecologica…)
2. PROVINCIA          (provincia + area metropolitana: PTCP/PTC2, viabilità provinciale…)
3. COMUNE             (dettaglio: PRG/PRGC, PUC, catasto, servizi comunali…)
```

- Il livello e l'ente sono codificati nella chiave sorgente (come in Torino: `r_piemon`=regione,
  `p_bi`=provincia Biella, `c_<istat>`=comune).
- In `04_compose` vale il **fill-down con override**: dove esiste il dettaglio comunale, questo
  **prevale** sul regionale; dove manca, si eredita il livello superiore. Ogni feature conserva il
  livello di provenienza.

## 2. Due nature di piano (che si alimentano a vicenda)

- **Regolatore** — leggi/norme che descrivono il territorio: zone inedificabili, terreni agricoli,
  pericoli, vincoli, peculiarità. (In taxonomy: `plan_type: regolatore`.)
- **Operativo** — innovazioni, nuove costruzioni, progetti finanziati (OpenCUP, PNRR, PUMS…).
  (`plan_type: operativo`.)

I regolatori spesso **abilitano** gli operativi (accesso ai fondi): la composizione mantiene i CUP
e i riferimenti ai piani regolatori collegati, così la traccia regolatore↔operativo non si perde.

## 3. Struttura delle cartelle

```
Layer_Processor/
  README.md                     ← questo contratto
  run.py                        ← orchestratore: risolve dipendenze, rigira solo il cambiato
  requirements.txt
  registry/                     ← verità curata a mano (versionata)
    sources.yaml                ← fonti: url, livello, ente, tipo piano, formato
    canonical_taxonomy.yaml     ← i layer FINALI target (le classi canoniche)
    layer_dictionary.yaml       ← formulazione layer → classe canonica (+ match + confidence)
  lib/                          ← utilità condivise
    normalize.py                ← norm() + tokenizzazione titoli
    recognize.py                ← matcher: (title, topic, fields) → canonico + confidence + motivo
    state.py                    ← hashing input/output per idempotenza
    admin.py                    ← lookup ISTAT regione/provincia/comune (TODO)
  stages/                       ← uno script per stadio (idempotenti)
    stage_01_discover.py        ← url → endpoint dataset (CKAN, ArcGIS REST, WFS)   [stub]
    stage_02_download.py        ← endpoint → raw/ + manifest                         [stub]
    stage_03_recognize.py       ← raw/catalog → riconoscimento + proposte           [attivo]
    stage_04_compose.py         ← layer riconosciuti → layer canonico + tracciabilità [stub]
    stage_05_load.py            ← canonici → staging Supabase → promote              [stub]
  raw/    work/    out/    state/   ← grezzi / intermedi / canonici pronti / stato (gitignored)
```

## 4. Contratto dei dati fra stadi

Ogni stadio legge da una cartella e scrive in un'altra, con un `_manifest.json` per la tracciabilità.

| Stadio | Input | Output | Idempotenza |
|---|---|---|---|
| 01 discover | `registry/sources.yaml` | `work/catalog/<ente>.csv` (schema Torino: uuid,title,topic,url,…) | per fonte, se la fonte è cambiata |
| 02 download | `work/catalog/*.csv` | `raw/<livello>/<ente>/<dataset>/…` + `_manifest.json` | per dataset, se url/hash cambia |
| 03 recognize | `raw/**` o un `_catalog.csv` | `work/recognition/<ente>.json` (match) + `work/proposals/<ente>.json` (non riconosciuti) | per catalogo, se dizionario o input cambia |
| 04 compose | `work/recognition/*` + `raw/**` | `out/<canonical_key>/<territorio>.geojson` + provenienza per-feature | per classe+territorio |
| 05 load | `out/**` | staging Supabase → dry-run → promote | atomico, SCD2 |

**Tracciabilità (requisito):** ogni feature del layer canonico porta almeno
`source_uuid`, `source_title`, `ente`, `livello`, `url`, `topic`, `canonical_key`, `match_confidence`.

## 5. Il dizionario dei layer (cuore del sistema)

Governance identica agli alias comuni (`pipeline/aliases/NORMALIZATION_RULES.md`):

- `registry/canonical_taxonomy.yaml` definisce **a mano** le classi canoniche finali (riuso dei temi Torino).
- `registry/layer_dictionary.yaml` mappa formulazioni note → classe canonica con regole di match e `confidence`.
- Il matcher (`lib/recognize.py`) **propone**; non fa auto-merge cieco. I layer non riconosciuti finiscono
  in `work/proposals/` per revisione umana → poi si estende il dizionario. Nessun alias ambiguo ammesso.

## 6. Pilota corrente: golden test su Piemonte/Torino

Il primo obiettivo end-to-end è **riprodurre** i layer canonici già noti di Torino facendo girare il
processore generalizzato su `Nord/piemonte/` (dati già scaricati). Serve come test di regressione:
il riconoscimento deve mappare i dataset noti sulle classi canoniche attese
(vedi `Nord/piemonte/_catalog.csv`, 946 dataset).

## 7. Uso

```bash
# riconoscimento sul catalogo reale di Torino (pilota)
python3 run.py recognize --catalog "../Nord/piemonte/_catalog.csv" --ente r_piemon

# stato della catena (cosa è aggiornato / da rifare)
python3 run.py status
```

## 8. Cosa NON è ancora implementato

- `stages/stage_01_discover.py`, `stage_02_download.py`, `stage_04_compose.py`, `stage_05_load.py`: stub con contratto definito.
- `lib/admin.py`: lookup ISTAT da `Geography_Locations/outputs/` (da implementare per il compose).
- `05_load` non scriverà mai sul DB senza un dry-run approvato (come da `PIPELINE_CONTRACT.md`).
