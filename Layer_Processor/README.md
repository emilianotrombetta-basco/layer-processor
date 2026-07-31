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

## 1. Ordine territoriale (regola predefinita, adattata al contesto)

L'analisi incrocia normalmente piani a tre livelli. Il registry e la composizione li processano
**in quest'ordine predefinito**:

```
1. REGIONE            (piani regionali: PPR, PTR, PAI/PGRA regionale, rete ecologica…)
2. PROVINCIA          (provincia + area metropolitana: PTCP/PTC2, viabilità provinciale…)
3. COMUNE             (dettaglio: PRG/PRGC, PUC, catasto, servizi comunali…)
```

- Il livello e l'ente sono codificati nella chiave sorgente (come in Torino: `r_piemon`=regione,
  `p_bi`=provincia Biella, `c_<istat>`=comune).
- `registry/regional_planning_profiles.yaml` può escludere livelli istituzionali non esistenti e
  dichiarare strumenti, conteggi e fonti attesi. Per la Valle d'Aosta l'ordine è
  **regione → comune**; il contenitore provinciale ISTAT resta solo tecnico.
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
    regional_planning_profiles.yaml ← ordinamenti, strumenti e coperture attesi per regione
    composition_targets.yaml    ← prodotti finali, stati, scale e quality gate del semaforo
    canonical_taxonomy.yaml     ← i layer FINALI target (le classi canoniche)
    layer_dictionary.yaml       ← formulazione layer → classe canonica (+ match + confidence)
  lib/                          ← utilità condivise
    normalize.py                ← norm() + tokenizzazione titoli
    recognize.py                ← matcher: (title, topic, fields) → canonico + confidence + motivo
    state.py                    ← hashing input/output per idempotenza
    admin.py                    ← lookup ISTAT regione/provincia/comune (TODO)
    planning_context.py         ← carica e valida le aspettative regionali
  stages/                       ← uno script per stadio (idempotenti)
    stage_01_discover.py        ← cataloghi ArcGIS/WFS/Socrata/WebSIT → inventario layer
    stage_02_download.py        ← GeoJSON/JSON/SHP-ZIP a batch, checkpoint e ripresa
    stage_03_recognize.py       ← raw/catalog → riconoscimento + proposte           [attivo]
    stage_04_compose.py         ← layer riconosciuti → layer finali + manifest [VdA + PGT Lombardia]
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

I target iniziali di Composizione sono `PIANI_MATURITA`, `VINCOLI_COMUNALI` e
`SEMAFORO_EDIFICABILITA`. Il verde è ammesso soltanto con copertura completa
degli input obbligatori; in caso contrario lo stato resta `UNASSESSED`.

La vista **Territorio · Copertura nazionale** misura l'avanzamento regionale
dei cinque stadi: ogni stadio completato vale 20%. Il 100% richiede catalogo
completo, download senza elementi mancanti, riconoscimento concluso, tutti i
target di composizione completi e una ricevuta di caricamento/promozione dello
stadio 05. Output parziali e semplici file presenti non vengono contati come
stadi completati.

La pagina **Processi** conserva le opzioni necessarie alla ripresa delle
esecuzioni fallite o interrotte. `Riprendi` rilancia lo stesso stadio e scope:
per il Download usa sempre `only_new`, quindi i file già acquisiti vengono
saltati; Riconoscimento e Composizione ripartono in modo idempotente e la
Composizione conserva i target selezionati.

La pagina **Fonti** non è soltanto un elenco di link: per ogni adapter attivo
mostra formato, numero previsto e già scaricato, batch, cartella `raw/`,
modalità di ripresa e i comandi equivalenti. `Vai a Processi` consente di
eseguire Scoperta e Download dall'interfaccia; lasciando attivo `Solo dati
nuovi`, i click successivi acquisiscono i batch pendenti.

Le cinque sezioni della pipeline sono espandibili e richiudibili. Quando una
sezione è chiusa mostra soltanto il nome; il processo attivo viene aperto
automaticamente. Download mantiene compatto il riepilogo e carica chiamate/log
solo su richiesta. Lo storico mostra inizialmente sei esecuzioni ed è filtrabile
per concluse o da riprendere.

Un job attivo è sempre mostrato in un banner globale, anche se l'utente passa a
un altro territorio. Il banner riporta percentuale stimata, elementi elaborati,
durata e `Vai al processo`. Anche il conflitto `Un processo è già in esecuzione`
restituisce lo stesso collegamento. Quando un riepilogo segnala errori, il
pulsante `Spiega errori` apre i messaggi conservati nel manifest o nel log.

## 5. Il dizionario dei layer (cuore del sistema)

Governance identica agli alias comuni (`pipeline/aliases/NORMALIZATION_RULES.md`):

- `registry/canonical_taxonomy.yaml` definisce **a mano** le classi canoniche finali (riuso dei temi Torino).
- `registry/layer_dictionary.yaml` mappa formulazioni note → classe canonica con regole di match e `confidence`.
- Il matcher (`lib/recognize.py`) **propone**; non fa auto-merge cieco. I layer non riconosciuti finiscono
  in `work/proposals/` per revisione umana → poi si estende il dizionario. Nessun alias ambiguo ammesso.

## 6. Pilota corrente: Piemonte/Torino riproducibile da zero

`Nord/piemonte/` è soltanto il golden test storico e **non è un input operativo**.
Il registry versionato conserva l'inventario degli URL ufficiali, non i file:

- `r_piemon`: 445 risorse del Geoportale Regione Piemonte;
- `p_to`: 184 riferimenti di Città metropolitana, ARPA, PUMS e GTFS, di cui
  181 scaricabili e 3 conservati come metadati;
- `c_001272`: 223 risorse del Geoportale del Comune di Torino.

Da un'installazione vuota, `Scoperta fonti` ricrea i tre cataloghi in `work/catalog/`
e `Download` acquisisce nuovamente i file dai portali ufficiali. I download sono
atomici, divisi in batch e riprendibili: un nuovo click scarica soltanto i pendenti.
I tre scope restano separati, quindi caricare prima Torino non duplica né blocca il
successivo caricamento delle fonti metropolitane, regionali o delle altre province.
Il feed GTFS GTT resta deliberatamente `restricted_noncommercial`: l'URL è censito,
ma non viene scaricato automaticamente per una piattaforma rivolta a investitori
finché non è disponibile un'autorizzazione commerciale.

## 7. Lombardia riproducibile da zero

Lo scope Lombardia esegue insieme tre fonti ufficiali:

- `r_lombar`: 138 layer ArcGIS da Mosaico PGT, stato PGT, PPR, fattibilità
  geologica, confini correnti, quadro PTR/PT7 e mosaico PTCP di dettaglio;
- `r_lombar_pgtweb`: inventario Socrata PGTWEB, 38.851 record alla verifica del
  29 luglio 2026;
- `r_lombar_ptm`: 157 pacchetti shapefile unici del PTM vigente di Milano,
  deduplicati dai 284 riferimenti presenti nelle dieci tavole del catalogo XML.

`python3 run.py sync --region 03` e il pulsante Lombardia della dashboard
includono tutte e tre le fonti. I dati grezzi restano separati per provenienza;
un'interruzione lascia intatti i file conclusi e la run successiva riparte dai
pendenti. La composizione `PIANI_MATURITA` deduplica l'inventario PGTWEB e lo
aggancia ai 1.501 confini comunali correnti.

## 8. Veneto riproducibile da zero

La fonte attiva `r_veneto` non dipende da una lista di nomi salvata a mano. A ogni
scoperta legge le configurazioni correnti dei due WebGIS ufficiali:

- pianificazione comunale (`webgisId=213`): confini correnti, Province, perimetri
  AUC della L.R. 14/2017 e zonizzazione del Piano Regolatore Comunale;
- PTRC 2020 vigente (`webgisId=191`): tavole e temi regionali disponibili nel WFS.

Le configurazioni vengono incrociate con `GetCapabilities` del WFS regionale e le
ripetizioni fra tavole sono deduplicate. Alla verifica del 29 luglio 2026 risultano
**269 layer unici**. Il download WFS è paginato a 500 feature e la dashboard esegue
al massimo 10 layer per batch; un nuovo avvio salta i file già completi e riparte
dai pendenti.

Il download del confine comunale genera automaticamente
`../Geography_Locations/outputs/admin_municipalities_veneto_current.geojson`, con
**559 Comuni correnti**. L'overlay sostituisce per il solo Veneto il registro
nazionale storico senza modificarlo.

PAT/PATI e AUC descrivono il quadro strategico; per attribuire edificabilità
conformativa servono PI, zonizzazione, NTA e atti vigenti del Comune. Il WebGIS
regionale stesso dichiara che la sua rappresentazione non ha valore conformativo.
Le sette fonti PTCP provinciali/metropolitane sono già visibili nella pagina
`Fonti`, ma restano `todo` finché non viene verificato per ciascuna un endpoint
vettoriale stabile e riprendibile.

## 9. Emilia-Romagna riproducibile da zero

Lo scope `08` usa il proxy pubblico ufficiale Moka, inizializzando una sessione
per raggiungere i MapServer ArcGIS regionali senza dipendere dagli host interni:

- `r_emilia_romagna_pug`: 17 layer vettoriali del modello dati PUG;
- `r_emilia_romagna_psc`: 9 layer del mosaico PSC, inclusa la copertura dei
  Comuni presenti in banca dati;
- otto mosaici delle tutele PTCP/PTM per Bologna, Ferrara, Forlì-Cesena,
  Modena, Parma, Piacenza, Ravenna e Reggio Emilia.

Alla verifica live del 30 luglio 2026 il catalogo aggregato contiene **210
layer**. Il riconoscimento classifica tutti i 9 layer PSC e 177 dei 184 layer
provinciali; i sette residui hanno titoli composti soltanto da riferimenti ad
articoli normativi e restano correttamente in revisione. Nel PUG sono
riconosciuti 14 layer su 17: i tre layer della griglia strutturale richiedono
una classificazione per feature tramite `TIPO_ESTR`, non un'etichetta unica
assegnata all'intero layer.

Il mosaico di Rimini è censito come `todo`: il servizio Moka ufficiale risponde
attualmente con HTTP 500 e viene quindi escluso dalla pipeline regionale finché
non torna interrogabile. PTCP e PTM sono trattati come tutele ancora efficaci,
non come piani integralmente sostituiti: la L.R. 24/2017 mantiene infatti in
vigore le loro componenti paesaggistiche durante la transizione a PTAV/PTM.

### Fonte nazionale HOTOSM per usi e punti di interesse

`n_hotosm_poi` registra l'export nazionale OpenStreetMap/HOTOSM del 28 gennaio
2025: **1.048.796 punti** GeoJSON e **726.749 poligoni** Shapefile. L'adapter
`local_spatial` non duplica gli oltre 1,8 GB presenti nel workspace: collega i
file e tutti i componenti dello Shapefile in `raw/nazionale/n_hotosm_poi/`.

I poligoni alimentano `ANALISI_URBANISTICA` come overlay di uso osservato
esplicitamente non prescrittivo; i punti alimentano il target autonomo
`PUNTI_INTERESSE`. Entrambi conservano `amenity`, `shop`, `tourism`,
`man_made`, nome, indirizzo, `osm_id`, `osm_type`, attribuzione e licenza
ODbL 1.0. Il lettore è progressivo e filtra prima per estensione territoriale,
così non carica in RAM l'intero dataset nazionale.

Verifica reale su Bologna: 3.842 poligoni HOTOSM aggiunti ad Analisi Urbanistica
e 8.904 POI puntuali; sull'intera Emilia-Romagna il layer puntuale contiene
74.535 elementi.

## 10. Uso

```bash
# Piemonte: Regione, Città metropolitana/ARPA e Comune di Torino
python3 run.py discover --source r_piemon --progress
python3 run.py download --source r_piemon --max-services 25 --progress
python3 run.py discover --source p_to --progress
python3 run.py download --source p_to --max-services 20 --progress
python3 run.py discover --source c_001272 --progress
python3 run.py download --source c_001272 --max-services 20 --progress

# Valle d'Aosta: 856 voci censite; 769 vettoriali scaricabili e 87 raster censiti
python3 run.py discover --source r_vda

# verifica ciò che verrebbe scaricato
python3 run.py sync --region 02 --dry-run

# download reale. Il token resta soltanto nell'ambiente e non viene scritto nei log.
export VDA_ARCGIS_TOKEN="<token temporaneo>"
python3 run.py sync --region 02 --progress

# riconoscimento sul catalogo riprodotto dal processore
python3 run.py recognize --catalog "work/catalog/r_piemon.csv" --ente r_piemon

# aspettative operative regionali (testo o JSON per la dashboard)
python3 run.py context --region 02
python3 run.py context --region "Valle d'Aosta" --json

# composizione cartografica per regione o singolo comune
python3 run.py compose --targets PIANI_MATURITA,VINCOLI_COMUNALI,SEMAFORO_EDIFICABILITA \
  --scope-level region --scope-key 02 --scope-name "Valle d'Aosta" --progress
python3 run.py compose --targets PIANI_MATURITA \
  --scope-level municipality --scope-key 007005 --scope-name Arvier --progress

# Liguria: discovery delle 350 Carte tematiche e download riprendibile a batch
python3 run.py discover --source r_liguria --progress
python3 run.py download --source r_liguria --max-services 25 --progress

# Lombardia: tutte le fonti regionali + PGTWEB + PTM Milano
python3 run.py sync --region 03 --max-services 2 --progress
python3 tools/run_recognize_sources.py \
  --sources r_lombar,r_lombar_pgtweb,r_lombar_ptm
python3 run.py compose --targets PIANI_MATURITA \
  --scope-level region --scope-key 03 --scope-name Lombardia --progress

# Veneto: pianificazione comunale + PTRC 2020, inventario live e batch riprendibili
python3 run.py discover --source r_veneto --progress
python3 run.py download --source r_veneto --max-services 10 --progress
python3 run.py sync --region 05 --max-services 10 --progress
python3 run.py context --region 05 --json

# Emilia-Romagna: PUG, PSC e tutele provinciali/metropolitane
python3 run.py sync --region 08 --max-services 10 --progress
python3 tools/run_recognize_sources.py \
  --sources r_emilia_romagna_pug,r_emilia_romagna_psc,p_bo_ptcp_tutele,p_fe_ptcp_tutele,p_fc_ptcp_tutele,p_mo_ptcp_tutele,p_pr_ptcp_tutele,p_pc_ptcp_tutele,p_ra_ptcp_tutele,p_re_ptcp_tutele
python3 run.py context --region 08 --json

# HOTOSM nazionale: ingest locale, riconoscimento e composizione territoriale
python3 run.py discover --source n_hotosm_poi --progress
python3 run.py download --source n_hotosm_poi --progress
python3 run.py recognize --catalog work/catalog/n_hotosm_poi.csv --ente n_hotosm_poi --force
python3 run.py compose --targets ANALISI_URBANISTICA,PUNTI_INTERESSE \
  --scope-level municipality --scope-key 037006 --scope-name Bologna --progress

# stato della catena (cosa è aggiornato / da rifare)
python3 run.py status
```

## 11. Cosa NON è ancora implementato

- Gli adapter `discover/download` delle regioni non ancora configurate nel registry.
- `stage_04_compose.py`: attivo per Valle d'Aosta e per la maturità PGT Lombardia.
  In VdA lo stato PRG è completo 74/74;
  i vincoli sono prodotti con geometria originale ritagliata per comune e copertura esplicita.
  Il Semaforo resta `UNASSESSED` finché P4 Zone e inventario completo dei vincoli non sono disponibili.
- Il download di `P4 Zone` dal proxy VdA risponde attualmente HTTP 400; non viene creata
  una zonizzazione sostitutiva. È pubblicato soltanto l'overview comunale grigio.
- Il compose Piemonte/Liguria/Veneto e la classificazione RED/YELLOW/GREEN di dettaglio sono da completare.
- `stage_05_load.py`: stub con contratto definito.
- `lib/admin.py`: lookup ISTAT da `Geography_Locations/outputs/` (da implementare per il compose).
- `05_load` non scriverà mai sul DB senza un dry-run approvato (come da `PIPELINE_CONTRACT.md`).
