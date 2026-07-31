# Handoff per Claude - Piattaforma generale Atlante Piemonte

Aggiornato al 2026-07-22.

Questo file serve per continuare il lavoro sulla **piattaforma generale** dell'Atlante dei piani Piemonte, cioe la dashboard principale in `index.html`.

Non lavorare sulla piattaforma separata dell'attrattivita (`attrattivita.html`) a meno che venga richiesto esplicitamente. Quella e una sandbox laterale.

## App

Cartella app:

```bash
/Users/emilianotrombetta/Library/Application Support/PiemonteBeta/app
```

Avvio:

```bash
cd "/Users/emilianotrombetta/Library/Application Support/PiemonteBeta/app"
PORT=4188 node server.mjs
```

URL:

```text
http://127.0.0.1:4188
```

File principali:

- `index.html`: frontend Leaflet single-file della piattaforma generale.
- `server.mjs`: API Node, Supabase, GeoJSON locali, territori e flussi.
- `piemonte_catalog.mjs`: catalogo dei layer Piemonte.
- `data/`: GeoJSON locali, via symlink condiviso.
- `mobility/`: dati SVR e GTFS per sezione Flussi provincia.
- `.env.local`: credenziali Supabase. Non stampare, non copiare, non committare.

## Ambito del lavoro

Lavorare su:

- piattaforma generale `index.html`;
- catalogo layer `piemonte_catalog.mjs`;
- API/layer in `server.mjs`;
- popup, legenda, blocchi tematici, filtri territorio, archivio, documenti;
- sezione **Flussi provincia** della dashboard principale.

Non lavorare ora su:

- `attrattivita.html`;
- `data/piemonte_attrattivita_latlon.geojson`;
- `scripts/build_piemonte_attractiveness_latlon.py`.

Questi file esistono, ma sono fuori dallo scope attuale.

## Regole importanti

- Il filtro per provincia/comune deve usare geometrie territoriali reali, non bbox.
- Provincia Torino: codice `001`.
- `getTerritoryFeature()` in `server.mjs` restituisce la geometria esatta della provincia come union dei comuni.
- `applyTerritoryFilter()` in `index.html` carica il territorio esatto e `featureInTerritory()` filtra su attributi + geometria.
- Supabase puo andare in timeout con troppe query parallele: mantenere query pesanti sequenziali o limitate.
- Non caricare in mappa layer enormi senza overview.
- Il PRG storico Torino completo da 122 MB non va usato in UI: usare sempre overview.
- Le particelle catastali complete sono troppo grandi: in UI resta l'overview per foglio.

## Stato dashboard generale

La piattaforma generale e organizzata in 4 macro-blocchi.

### 1. Regole e costruibilita

Temi principali:

- **Assetto territoriale regionale** (`piemonte-assetto`)
  - Comune Torino, Provincia Torino, Sviluppo PRG, Quartieri Torino.
- **Maturita dei piani per comune** (`piemonte-quadro-piani`)
  - 312 comuni, 4 classi: verde/giallo/arancio/grigio.
- **Semaforo dei vincoli di costruzione** (`piemonte-edificabilita`)
  - Semaforo **per lotti**, non piu overlay di layer separati.
  - Base lotti: 79.227 poligoni del PRG storico mosaicato, tutti i comuni della Citta metropolitana (315 codici ISTAT), ognuno con destinazione d'uso.
  - Ogni lotto e incrociato offline con i vincoli sovraordinati locali (fasce fluviali PAI, PGRA, vincolo idrogeologico, aree protette, vincoli paesaggistici, corridoi ecologici) -> verdetto + elenco esplicito dei vincoli.
  - Classi: verde (edificabile, nessun vincolo rilevato), giallo (condizioni/autorizzazioni), rosso (esclusa o limitata), grigio (destinazione da acquisire).
  - Il verde non significa edificabilita automatica: serve verifica PRG/NTA.
  - Layer unico `PIE-SEMAFORO-LOTTI`. Il server sceglie il file in base al parametro `territory`: senza comune serve l'overview dissolta per comune (`piemonte_semaforo_comuni.geojson`, ~10 MB, sintesi 768 feature); con un comune serve il dettaglio per-lotto `data/semaforo_lotti/<istat>.geojson`.
  - Vincoli ancora da aggiungere (oggi su Supabase, non nell'overlay): PAI frane, PPR beni paesaggistici, Natura 2000, PPR acque/agricoltura. Le destinazioni agricola e pregio naturale sono gia catturate dal PRG.
  - Pipeline: `scripts/build_piemonte_semaforo_lotti.py` (overlay pesante -> `data/piemonte_semaforo_lotti.geojson`, gitignored) poi `scripts/build_piemonte_semaforo_serving.py` (artefatti serviti). Rigenera i serviti senza rifare l'overlay.
- **Zonizzazione e disciplina urbanistica** (`piemonte-zonizzazione`)
  - PRG Torino, edifici storici, PRG storico metropolitano overview.
- **Catasto** (`piemonte-catasto`)
  - Fogli catastali aggregati.

### 2. Ambiente e tutele

Temi principali:

- **Tutele paesaggistiche** (`piemonte-paesaggio`)
  - Aree protette, vincoli paesaggistico-ambientali, rete ecologica, AVE e connettivita.
- **Aree naturali e biodiversita** (`piemonte-natura`)
  - Natura 2000, ambiti PPR, beni PPR, crinali.
- **Pericolosita alluvioni (PGRA)** (`piemonte-pgra`)
  - Classi H/M/L.
- **Acque, fasce fluviali e vincoli** (`piemonte-rischio`)
  - Fasce PAI, vincolo idrogeologico, frane, esondazioni, PPR acque.
- **Agricoltura e paesaggio rurale** (`piemonte-agricoltura`)
  - Aree agricole di interesse agronomico.

### 3. Attrattivita e accessibilita

Temi principali:

- **Mobilita e accessibilita** (`piemonte-mobilita`)
  - 4.884 geometrie, 6 classi.
  - Stazioni ferroviarie, metro, ciclabili, sharing/ricarica, regolazione accessi, nodi logistici.
- **Servizi e polarita territoriali** (`piemonte-servizi`)
  - 7.296 geometrie, 4 classi.
  - Istruzione, sanita, cultura/sport, servizi PRG.
- **Commercio e sistema produttivo** (`piemonte-economia`)
  - 32.882 geometrie, 3 classi.
  - Commercio, mercati/fiere, poli produttivi.
- **Valori immobiliari OMI**
  - comuni e quartieri Torino.
- **Infrastrutture attuali**
  - AINOP.

### 4. Scenari futuri

Temi principali:

- **Investimenti pubblici OpenCUP** (`piemonte-opencup`)
  - 312 comuni, CUP aggregati per comune.
  - Attenzione: importi multi-comune conteggiati su ogni comune localizzato, non ripartiti.
- **Trasformazioni e rigenerazione urbana** (`piemonte-trasformazioni`)
  - Ambiti di trasformazione e progetti unitari.
- **Mobilita sostenibile programmata** (`piemonte-pums`)
  - Interventi PUMS metropolitani.

## Layer recenti gia integrati

Generati con:

```bash
scripts/build_piemonte_blocks_layers.py
```

Layer servizi:

- `PIE-SERV-ISTRUZIONE`: 1.024 feature.
- `PIE-SERV-SANITA`: 487 feature.
- `PIE-SERV-CULTURA-SPORT`: 3.314 feature.

Layer mobilita:

- `PIE-MOB-METRO`: 45 feature.
- `PIE-MOB-CICLABILE`: 4.148 feature.
- `PIE-MOB-SHARING-RICARICA`: 264 feature.
- `PIE-MOB-REGOLAZIONE`: 262 feature.
- `PIE-MOB-NODI-LOGISTICA`: 58 feature.

Layer economia:

- `PIE-ECO-COMMERCIO`: 31.217 feature.
- `PIE-ECO-MERCATI`: 251 feature.
- `PIE-ECO-PRODUTTIVI`: 1.414 feature.

OpenCUP:

- Script: `scripts/build_piemonte_opencup_comuni.mjs`.
- Output: `data/piemonte_opencup_comuni.geojson`.
- Layer: `PIE-OPENCUP-COMUNI`.
- Tema: **Investimenti pubblici OpenCUP**.

## Sezione Flussi provincia

Dati:

- `mobility/roads_flow.geojson`: 37.323 segmenti BDTRE con `mfw_sum > 0`.
- `mobility/svr_traffic.json`: analisi aggregata.
- `mobility/svr_flow_nodes.geojson`: 6.697 nodi/centroidi di flusso.
- `mobility/gtfs_network.geojson`: rete GTT.
- `mobility/gtfs_stops.geojson`: fermate GTT.
- `mobility/gtfs_summary.json`: sintesi GTFS.

Endpoint:

- `/api/piemonte/traffic`
- `/api/piemonte/traffic/layer`

Nota da mantenere in UI:

- SVR e un modello giornaliero/medio.
- Scrivere: `giorno feriale medio - no orario`.
- Campo da usare: `mfw_sum` = flusso totale stimato.

## Verifiche rapide

Server:

```bash
curl -s http://127.0.0.1:4188/health
```

Catalogo Piemonte:

```bash
curl -s http://127.0.0.1:4188/api/piemonte/catalog \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['totals'])"
```

Layer campione:

```bash
curl -s "http://127.0.0.1:4188/api/piemonte/layer?id=PIE-PRG-ZONE" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d['features']))"
```

```bash
curl -s "http://127.0.0.1:4188/api/piemonte/layer?id=PIE-SERV-ISTRUZIONE" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d['features']))"
```

Sintassi:

```bash
node --check piemonte_catalog.mjs
node - <<'NODE'
const fs = require('fs');
const html = fs.readFileSync('index.html','utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
fs.writeFileSync('/tmp/piemonte-index-inline-check.js', scripts.join('\n'));
NODE
node --check /tmp/piemonte-index-inline-check.js
```

## QA browser atteso

Su `http://127.0.0.1:4188`:

- La dashboard deve partire su Piemonte senza restare bloccata su caricamento.
- `/health` deve mostrare `supabase:true`.
- **Maturita dei piani per comune**:
  - 312 geometrie.
  - 4 classi.
- **Semaforo dei vincoli di costruzione**:
  - Intera regione: overview per comune, 768 feature, classi verde/giallo/rosso/grigio.
  - Selezionando un comune: dettaglio per-lotto (Torino ~7.818 lotti) con popup Verdetto/Destinazione/Vincoli/Perche.
- **Servizi e polarita territoriali**:
  - 7.296 geometrie.
  - 4 classi.
- **Mobilita e accessibilita**:
  - 4.884 geometrie.
  - 6 classi.
- **Commercio e sistema produttivo**:
  - 32.882 geometrie.
  - 3 classi.
- **Flussi provincia**:
  - mappa SVR visibile;
  - layer strade, heatmap/nodi, rete TPL e fermate selezionabili;
  - testo temporale coerente: giorno feriale medio, no orario.

## Prossimi passi consigliati

1. Migliorare la piattaforma generale, non `attrattivita.html`.
2. Raffinare popup e legenda del PRG storico metropolitano.
3. Aggiungere una vista/fonti con provenienza, data, copertura e limiti dei layer.
4. Migliorare performance per layer pesanti, soprattutto commercio e tutele overview.
5. Valutare vector tiles o semplificazione multi-scala per catasto dettagliato e PRG storico completo.
6. Rendere piu leggibile il semaforo costruibilita quando molti vincoli si sovrappongono.

## Nota finale

Esiste anche un file piu esteso:

```bash
/Users/emilianotrombetta/Documents/espansione del dominio/CODEX_ISTRUZIONI.md
```

Quello contiene anche la parte sperimentale di attrattivita. Per il lavoro richiesto ora usare questo handoff e restare sulla piattaforma generale.
