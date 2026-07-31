# Handoff Codex — Semaforo, Analisi Urbanistica, Mercato immobiliare

Aggiornato al 2026-07-22. App: `/Users/emilianotrombetta/Library/Application Support/PiemonteBeta/app`.
Piattaforma generale `index.html` (Leaflet single-file), catalogo `piemonte_catalog.mjs`, API `server.mjs`.

Avvio server (dev, avviato a mano, NON launchd):
```bash
cd "/Users/emilianotrombetta/Library/Application Support/PiemonteBeta/app"
PORT=4188 node server.mjs   # http://127.0.0.1:4188
```
Dopo ogni modifica a index.html/catalog/server: riavviare il 4188 (kill del pid in LISTEN + rilancio) e ricaricare il browser.

Controlli sintassi:
```bash
node --check piemonte_catalog.mjs
node --check server.mjs
node - <<'NODE'
const fs=require('fs');const html=fs.readFileSync('index.html','utf8');
const s=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
fs.writeFileSync('/tmp/chk.js',s.join('\n'));
NODE
node --check /tmp/chk.js
```

I temi sono in `index.html`, array **`PIEMONTE_THEMES`** (~riga 308+). La colorazione/etichette per feature è nella funzione **`classification(themeId,item,feature,index)`** (~riga 481+). I popup in **`popupRows(themeId,item,p)`** (~riga 915+). La legenda in **`renderLegend`** (~riga 1009): una riga per `classification.key`, swatch = `legendColor||color`, `defaultVisible:false` → riga spuntata off e feature nascoste all'avvio.

---

## GIÀ FATTO in questa sessione (contesto, non rifare)

- **Semaforo per lotti** (`piemonte-edificabilita`, layer `PIE-SEMAFORO-LOTTI`): base = 79.227 poligoni PRG storico (tutti i comuni CM Torino). Overlay offline coi vincoli → verdetto verde/giallo/rosso + elenco vincoli + composizione dotazioni. Il server sceglie il file da `territory`: senza comune → `data/piemonte_semaforo_comuni.geojson` (overview 760 feat); con comune → `data/semaforo_lotti/<istat>.geojson` (dettaglio per-lotto). Pipeline: `scripts/build_piemonte_semaforo_lotti.py` (overlay pesante → `data/piemonte_semaforo_lotti.geojson`, gitignored) poi `scripts/build_piemonte_semaforo_serving.py` (artefatti serviti).
- **Vincoli overlay** (45.282 geom): fasce fluviali A/B/C, PGRA H/M/L, vincolo idrogeologico, aree protette/tutelate, vincoli paesaggistici PTC2, pregio, corridoi eco, misure acque, divieto fitosanitari + (da Supabase, clippati bbox metro) PAI frane (rosso), PAI esondazioni (giallo), PPR beni paesaggistici (rosso), Natura 2000 (rosso), PPR corpi idrici/reticolo linee (giallo, caso "torrente"), PPR agronomico (giallo). Export: `scripts/export_semaforo_supabase_constraints.py` (API <10k) + `scripts/export_semaforo_big_constraints.mjs` (DB diretto per i >10k; legge `.env.local`, non stampare le credenziali).
- **Composizione "intorno"** per lotto: `doti_servizi/istruzione/sanita/cultura_sport/commercio/tpl` (conteggi entro raggio dal centroide). Mostrati nel popup. `mobility/gtfs_stops.geojson` sta in `mobility/`, non `data/`.
- **Pannello descrizione (insight)** reso collassabile (`#insightToggle`, classe `.insight.collapsed`).
- **Assetto territoriale regionale**: quartieri + comune Torino uniti in un unico layer "Comune di Torino" (colore #1b2430); "Provincia di Torino" (#2b6a8f); layer PRG unico bicolore verde/rosso presente/assente, **rinominato "PRG" e default OFF** (`defaultVisible:true→false`). Catalogo `PIE-SVILUPPO-PRG` titolo → "PRG · presenza per comune".
- **Tutele paesaggistiche → 4 temi**: il tema unico `piemonte-paesaggio` è stato sostituito da 4 temi (stesso subGroup "Tutele paesaggistiche"): `piemonte-aree-protette` (Aree Protette, con Natura 2000), `piemonte-rete-ecologica` (Rete Ecologica e Biodiversità: AVE, corridoi, connettività), `piemonte-vincoli-paesaggistici` (Vincoli D.Lgs 42/2004 + pregio proposto), `piemonte-tutela-idrica` (misure acque + divieto fitosanitari). Le `description` dei 11 layer `PIE-TUT-*` in `piemonte_catalog.mjs` sono state riscritte col dettaglio fornito dall'utente. NB: i `themeId` in catalogo di quei layer sono ancora `piemonte-paesaggio` (cosmetico, usato solo in archivio); il frontend usa `layerKeys`.
- **Mercato immobiliare — gradiente OMI**: passato da mono-blu a caldo→freddo (blu economico → rosso caro) con **soglie dedicate ai due sottoblocchi** (comuni vs quartieri Torino), in `classification` blocco `PIE-OMI-COMUNI||PIE-OMI-QUARTIERI` (~riga 815). FATTO.

---

## DA FARE

### 1) Semaforo — Filtro "solo verdi" + ranking  (#3) ✅ FATTO (2026-07-22)
- Campo `punteggio = doti_servizi*2 + doti_tpl*3 + min(doti_commercio,20)` aggiunto in `build_piemonte_semaforo_lotti.py` (nel dict properties) e propagato in `build_piemonte_semaforo_serving.py` (file per-comune). Distribuzione verdi: min 0 / mediana 30 / max 594.
- `popupRows` (ramo `piemonte-edificabilita`, `if(motivo)`) mostra `['Punteggio dotazioni', …]` solo per i lotti verdi.
- Rigenerazione: `punteggio` è stato calcolato in-place sul file completo esistente (`data/piemonte_semaforo_lotti.geojson`, deriva da campi doti già presenti → nessun ricalcolo overlay) + `build_piemonte_semaforo_serving.py`. Se in futuro si rifà l'overlay pesante, il campo viene ora generato nativamente.
- RESTA OPZIONALE: bottone UI "solo edificabili" che spegne le classi giallo/rosso via i toggle di legenda (`#legendList .legend-toggle[data-key^="edif-"]`). NON fatto.

### 1b) Zone di allertamento di protezione civile (ARPA) ✅ FATTO (2026-07-22)
Nuovo layer/tema `piemonte-allerta` (`PIE-ALLERTA-ZONE`, 11 aree di allertamento), blocco 2 · subGroup "Rischio idraulico e vincoli". Fonte: shapefile ARPA `ZA_Piemonte` (EPSG:32632, CC-BY 4.0) in `Nord/piemonte/climatologyMeteorologyAtmosphere/Arpa_Piemonte_-_Aree_e_sottoaree_di_allerta__14`. Pipeline: `scripts/build_piemonte_allerta_zone.py` → `data/piemonte_allerta_zone.geojson`. Wiring: catalogo (`localGeoJsonLayer`), tema in `PIEMONTE_THEMES`, ramo `classification` (11 zone A–M colorate distinte) e `popupRows`. Layer di inquadramento, NON un vincolo edificatorio.

### 1c) Interventi nel territorio (base progetti) ✅ FATTO (2026-07-22)
Nuovo tema/layer `piemonte-interventi` (`PIE-INTERVENTI`), blocco 4 · subGroup "Investimenti pubblici e progettualità". Sorgente: **`api_endpoint.projects`** (Supabase), tutti i record geolocalizzati del Piemonte = 6.138 punti (OpenCUP 4.973, PNRR 1.148, PUMS 16, AINOP 1; su ~25.400 totali, gli altri senza coordinate). Export node diretto al DB: `scripts/export_piemonte_interventi.mjs` (legge `.env.local`, non stampa credenziali) → `data/piemonte_interventi.geojson` (~4 MB). Normalizza per fonte: costo_totale/finanziamento_pubblico (OpenCUP planned_cost/public_financing; PNRR finanziamento_totale/_pubblico), finanziamento_pnrr, cup, soggetto_attuatore, settore(macrocategory), categoria, fase, anni. Frontend: `classification` colora per **fonte** (punto), popup mappa `settore` (enum EN→IT) e formatta i costi in €. Distinto dall'aggregato `PIE-OPENCUP-COMUNI` (che è per-comune): qui ogni punto è un singolo intervento.

### 1d) TUTELE → blocco unico "Ambiente, Paesaggio e Tutele" (8 classi) ✅ FATTO (2026-07-22)
I 4 temi tutele (`piemonte-aree-protette`, `piemonte-rete-ecologica`, `piemonte-vincoli-paesaggistici`, `piemonte-tutela-idrica`) — 16 righe di legenda totali — sono stati fusi in **un solo tema `piemonte-tutele`** (subGroup "Ambiente, Paesaggio e Tutele") con **8 classi**: (1) Aree protette istituite ← AREE-PROTETTE + NATURA-2000 + PROTETTE-ISTITUITE + PROTETTE-PROV-IST; (2) Aree protette in proposta ← PROTETTE-PROV-PROP; (3) Connettività ecologica (classi 1–5) ← CONNETTIVITA (single key, rampa colore mantenuta per-feature, `legendColor` medio); (4) Rete ecologica strutturale ← CORRIDOI-ECO + AVE; (5) Vincoli paesaggistici attivi; (6) Pregio paesaggistico proposto; (7) Tutela delle acque; (8) Divieti fitosanitari. Implementazione: dispatch in `classification` **scoped a `themeId==='piemonte-tutele'`** (così Natura 2000 resta invariato nel tema `piemonte-natura`) che rimappa gli id_layer sulle 8 key. Meccanismo legenda: `stats` è keyed per `classification.key` → stessa key = una riga (colore = prima feature), mentre la mappa mantiene il colore per-feature (per la rampa connettività). Catalogo: themeId/themeTitle degli 11 `PIE-TUT-*` allineati a `piemonte-tutele` (cosmetico). Popup/tooltip invariati (sono keyed per id_layer).

### 2) ANALISI URBANISTICA — refactor classi ✅ RISULTA GIÀ IMPLEMENTATO (verificato 2026-07-22)
Tema `piemonte-zonizzazione` già rinominato `title:'Analisi Urbanistica'`; `classification` già mappa le 3 fonti (`PIE-PRG-ZONE`/`PIE-PRG-STORICO`/`PIE-PRG-STORICO-TO`) sulle classi semantiche `au-*` condivise (oggetto `AU`); `PIE-CATASTO-FOGLI` già in `layerKeys` con nota "solo Torino". Sezione sotto conservata come riferimento.

### 2-orig) ANALISI URBANISTICA — refactor classi (era "Zonizzazione e disciplina urbanistica")  ⟵ IL PIÙ GRANDE
Tema `piemonte-zonizzazione` in `PIEMONTE_THEMES` (~riga 312). Layer: `PIE-PRG-ZONE` (Torino, Supabase), `PIE-PRG-STORICO` (edifici storici Torino), `PIE-PRG-STORICO-TO` (mosaico storico CM Torino, overview).

**2a. Rinominare** il tema: `title:'Analisi Urbanistica'` (mantieni id `piemonte-zonizzazione`). Aggiorna subtitle/description/reading coerenti.

**2b. Unificare le ~20 classi in classi semantiche uniformi.** Oggi la `classification` produce classi separate e con prefisso "Storico ·". Le tre fonti vanno mappate sulle STESSE chiavi/etichette così da avere layer uniformi esplorabili su tutto il territorio. Chiavi target proposte (`key` → `label`):

| key | label | colore |
|---|---|---|
| `au-residenziale` | Aree Residenziali | #5277a3 |
| `au-produttive` | Aree Produttive | #9b6a3c |
| `au-servizi` | Aree a Servizi e dotazioni | #2f7e9c |
| `au-agricole` | Aree Agricole | #6f8f3d |
| `au-verde` | Verde e pregio naturale | #2f7d62 |
| `au-terziario` | Aree Terziarie / commerciali | #b07c3f |
| `au-turistico` | Aree Turistico-ricettive | #c07a55 |
| `au-polifunzionali` | Aree Polifunzionali | #8b6f9f |
| `au-trasformazione` | Ambiti di Trasformazione | #b85f36 |
| `au-edifici-storici` | Edifici di particolare valore storico | #9c4f39 |
| `au-altro` | Altre aree urbane (da verificare) | #8a97a0 |

**Mapping delle sorgenti → classi (basato su analisi dati reali):**

`PIE-PRG-ZONE` per `ID_TIPO_ZP` (campo `ID_TIPO_ZP`, 8.368 feature Torino):
- `ZUCRM` (4183, residenziale mista), `ZUCS` (673, centrale storica), `ZCC` (358, collinare R6/R7/R8), `ZUSA` (~1000, storico-ambientale) → **au-residenziale**
- `ZUCAP` (112, attività produttive) → **au-produttive**
- `ZVPPE` (334, verde privato con preesistenze), `PUF`/`SERV` → **au-servizi**
- `ZB` (104, zone boscate), `PC` (16, parco naturale collina) → **au-verde**
- `ZUT`/`ATS` (ambiti Spina/PRIU, trasformazione) → **au-trasformazione**
- residuo non mappato → **au-altro**
  → questo elimina completamente "Altre zone PRG" (oggi tutto ciò che non è ZUCRM/ZUCS/ZUCAP/ZUT/PUF finiva in "altro": ZVPPE/ZCC/ZUSA/ZB/PC — ora distribuiti).

`PIE-PRG-STORICO` per `TIPO_ED_ST` (1.245 edifici Torino): **tutti** i tipi (rilevante valore storico 491, valore documentario 433, storico-ambientale 148, gran prestigio 109, manufatti speciali 64) → **au-edifici-storici** (una sola classe "Edifici di particolare valore storico"). Elimina le 5 sottoclassi edifici.

`PIE-PRG-STORICO-TO` per `destinazione_uso` (mosaico CM Torino) — togliere il prefisso "Storico ·" e mappare:
- Aree residenziali → **au-residenziale**
- Aree a servizi/impianti → **au-servizi**
- Aree agricole → **au-agricole**
- Aree produttive → **au-produttive**
- Aree di pregio naturale → **au-verde**
- Aree polifunzionali → **au-polifunzionali**
- Aree terziarie → **au-terziario**
- Aree turistico-ricettive → **au-turistico**
- (vuoto)/"Non classificata" → **au-altro** (residuo minimo; NON inventare destinazione)

Nota "smaltimento" richiesto dall'utente: **"Altre zone PRG"** sparisce (ZVPPE/ZCC/ZUSA/ZB/PC ridistribuiti). **"Storico · Non classificata"** resta solo il residuo realmente privo di `destinazione_uso`, confluito in `au-altro` insieme al residuo PRG-ZONE: unica classe onesta "Altre aree urbane (da verificare)", senza prefisso "Storico".

Implementazione: nella `classification`, nei tre rami (`PIE-PRG-ZONE`, `PIE-PRG-STORICO`, `PIE-PRG-STORICO-TO`) restituire `key`/`label`/`color` dalle tabelle sopra invece delle attuali famiglie. Verificare in legenda che le classi si fondano (stessa `key` da sorgenti diverse = una riga sola con conteggio sommato).

**2c. Catasto come layer di questo blocco.** Aggiungere `PIE-CATASTO-FOGLI` a `layerKeys` del tema `piemonte-zonizzazione` (oggi è nel tema separato `piemonte-catasto`). In description/legenda specificare **"solo Città di Torino"**. Valutare se rimuovere il tema `piemonte-catasto` a sé (o lasciarlo). Il layer catasto ha già `ambito_di_copertura: "Citta di Torino - fonti catastali locali"`.

### 3) Nuovi tipi di vincolo per il semaforo (#4)  — richiede reperimento fonti
Da aggiungere all'overlay (`CONSTRAINTS` in `build_piemonte_semaforo_lotti.py`) una volta reperiti i dati:
- **Fasce di rispetto** (vanno CALCOLATE come buffer): stradale, ferroviaria, cimiteriale, depuratori, elettrodotti/gasdotti, corsi d'acqua 150 m (L.431). Serve geometria sorgente (BDTRE strade in `mobility/roads_flow.geojson`; ferrovie/cimiteri da reperire) + `shapely .buffer`.
- **Boschi / vincolo forestale**: carta forestale regionale Piemonte (cercare in `Nord/piemonte/` — es. `farming/` o `geoscientificInformation/`).
- **Classe sismica** per comune: tabella regionale (join su `codice_istat`), non geometrica.
- **Vincolo aeroportuale** (Caselle): mappa di vincolo/ostacoli ENAC.
Ognuno: esportare/derivare GeoJSON in `data/`, aggiungere a `CONSTRAINTS` con severità (rosso/giallo) e rifare overlay+serving.

---

### 4b) Nuovi layer valutati (da costruire)
Pattern: estrarre lo shapefile, riproiettare EPSG:3003→WGS84 (come `build_piemonte_blocks_layers.py`, che usa `pyshp`+`pyproj`+`shapely`), scrivere GeoJSON in `data/`, aggiungere voce a `piemonte_catalog.mjs` (+ classification/popup/theme in `index.html`).
- **Incendi boschivi** — FONTE OK: `Nord/piemonte/environment/Incendi_boschivi_-_Aree_e_Punti_di_innesco__5d8d0dd5/incendi_boschivi.zip` (aree + punti di innesco). → aggiungere al blocco rischi (tema `piemonte-rischio` o nuovo "Incendi boschivi"). Utile anche come vincolo/segnalazione nel semaforo.
- **Produzione di energia** — FONTE OK: `Nord/piemonte/structure/` con 3 zip PTC2: `centrali_idroelettriche.zip`, `centrali_teleriscaldamento.zip`, `centrali_biomasse.zip`. → nuovo tema in blocco 3 "Infrastrutture… stato attuale" (es. "Produzione di energia"), classi per tipo di centrale.
- **Strade / viabilità** — la mobilità NON ha un layer strade. Esiste `mobility/roads_flow.geojson` (BDTRE, 37.323 segmenti, oggi usato solo in Flussi provincia). → aggiungere un layer "Rete stradale" al tema `piemonte-mobilita` (attenzione al peso: valutare overview/semplificazione).
- **Sorgenti** e **Fontanili** — DATO NON DISPONIBILE: le cartelle `environment/Sorgenti__2666b617` e `environment/Fontanili__83c59eab` contengono solo `mappastart.do.bin` (pagina webmap, non un dataset). Serve ri-scaricare la fonte prima di poterli aggiungere come elementi naturali.

## Comandi pipeline semaforo (dopo modifiche ai dati/vincoli/composizione)
```bash
cd "/Users/emilianotrombetta/Library/Application Support/PiemonteBeta/app"
python3 scripts/build_piemonte_semaforo_lotti.py      # overlay pesante (qualche minuto)
python3 scripts/build_piemonte_semaforo_serving.py    # artefatti serviti (veloce)
# poi riavvia il 4188
```

## Verifiche browser attese
- **Analisi Urbanistica**: legenda con ~10-11 classi uniformi (niente prefissi "Storico ·", niente "Altre zone PRG"); una classe "Aree Residenziali" che somma PRG-ZONE residenziali + storico residenziale; "Edifici di particolare valore storico" unica; Catasto presente con nota "solo Torino".
- **Mercato immobiliare** (comuni e quartieri): gradiente blu→rosso, quartieri differenziati (non tutti nella fascia alta).
- **Assetto territoriale**: 3 voci; PRG spento all'avvio.
- **Semaforo**: click su lotto mostra tutti i vincoli + dotazioni (+ punteggio per i verdi).
