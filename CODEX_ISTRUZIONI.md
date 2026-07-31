# Istruzioni per Codex - Atlante dei piani Piemonte

Documento di handoff per continuare il lavoro sull'app Piemonte. Stato aggiornato al
2026-07-21. Tutti i percorsi sono assoluti o relativi alla cartella app indicata.

> Non stampare, copiare o committare il contenuto di `.env.local`: contiene credenziali
> Supabase. Il file va solo usato dal server.

## 1. App e avvio

App principale:
`/Users/emilianotrombetta/Library/Application Support/PiemonteBeta/app`

File chiave:
- `server.mjs`: API Node, lettura Supabase, layer GeoJSON locali, filtri territoriali.
- `index.html`: frontend Leaflet single-file.
- `piemonte_catalog.mjs`: catalogo Piemonte.
- `data/`: symlink verso i GeoJSON locali condivisi.
- `mobility/`: artefatti flussi SVR e TPL.
- `.env.local`: symlink con variabili Supabase, non mostrare.

Avvio:

```bash
cd "/Users/emilianotrombetta/Library/Application Support/PiemonteBeta/app"
PORT=4188 node server.mjs
```

Riavvio:

```bash
kill "$(lsof -tiTCP:4188 -sTCP:LISTEN)"
cd "/Users/emilianotrombetta/Library/Application Support/PiemonteBeta/app"
PORT=4188 node server.mjs
```

URL:
- `http://127.0.0.1:4188`
- `http://10.0.0.57:4188`

Endpoint utili:
- `/health`
- `/api/regions`
- `/api/piemonte/catalog`
- `/api/piemonte/layer?id=PIE-...`
- `/api/territories?region=piemonte`
- `/api/territory?region=piemonte&code=001`
- `/api/piemonte/traffic`
- `/api/piemonte/traffic/layer`

## 2. Regole importanti da mantenere

- Quando l'utente seleziona una provincia, un comune o entrambi, i layer attivi devono
  appartenere/intersecare quei poligoni. Non tornare a filtri per bbox.
- In `server.mjs`, `getTerritoryFeature()` restituisce anche la geometria esatta della
  provincia come `st_union` dei comuni.
- In frontend, `applyTerritoryFilter()` carica la geometria territoriale esatta e
  `featureInTerritory()` usa attributi territoriali e campionamento geometrico.
- La provincia di Torino ha codice `001`.
- Le query Supabase pesanti vanno tenute sequenziali o limitate: il pool va facilmente in
  timeout se si fanno molti conteggi paralleli.
- I GeoJSON statici possono essere serviti con cache: se una modifica non compare, fare hard
  reload o usare cache busting.
- Il file dettagliato PRG storico Torino da 122 MB non va caricato in UI: usare sempre la
  versione overview.
- Le particelle catastali complete sono oltre 200k feature: in UI usare l'overview per foglio
  o progettare vector tiles.

## 3. Stato layer - Mappa

### 1. Inquadramento normativo e trasformabilita

Gruppo: **Strategie e Piani territoriali**.

Tema: **Assetto territoriale regionale** (`piemonte-assetto`).

Layer attivi:
- `PIE-COMUNE-TORINO` - **Comune di Torino**
  - 1 feature.
  - File: `data/piemonte_comune_torino.geojson`.
- `PIE-PROVINCIA-TORINO` - **Provincia di Torino**
  - 312 comuni.
  - File: `data/piemonte_provincia_torino_comuni.geojson`.
- `PIE-SVILUPPO-PRG` - **Sviluppo Piani Regolatori**
  - 312 comuni.
  - File: `data/piemonte_sviluppo_piani_regolatori.geojson`.
  - Criterio: un comune e "presente" se contiene almeno un elemento in uno dei layer di
    `Zonizzazione e disciplina comunale`: `PIE-PRG-ZONE`, `PIE-PRG-STORICO`,
    `PIE-PRG-STORICO-TO`.
  - Stato attuale: 309 comuni presenti, 3 assenti.
  - Comuni assenti: Mappano, Val di Chy, Valchiusa.
- `PIE-STAT-ZONE` - **Quartieri Torino**
  - 94 feature.
  - File: `data/piemonte_zone_statistiche.geojson`.
  - Sorgente: `/Users/emilianotrombetta/Documents/espansione del dominio/Nord/piemonte/boundaries/Azzonamenti_Statistici_-_Zone_statistiche__ed751fd9`.

Nota: il vecchio layer **Ambiti di integrazione territoriale** proveniva da Supabase,
`piemonte.datasets` id `252`, sorgente `AIT.zip` / `AIT.shp`, tabella `piemonte.ptr`,
33 feature. Non e piu nel tema Assetto, ma resta catalogabile come `PIE-PTR-AIT`.

### Zonizzazione e disciplina comunale

Tema: `piemonte-zonizzazione`.

Layer:
- `PIE-PRG-ZONE` - **Zonizzazione urbanistica**
  - Supabase `piemonte.prg`, sorgente `zone_di_piano`.
  - 8.368 feature.
  - Popup migliorati con categoria urbanistica (`DESC_ZP_ES`), codice zona (`ID_ZP`),
    tipo zona (`ID_TIPO_ZP`) e attributi utili.
- `PIE-PRG-STORICO` - **Edifici di interesse storico**
  - Supabase `piemonte.prg`, sorgente `edifici_di_particolare_interesse_storico`.
  - 1.245 feature.
  - Popup con tipo edificio (`TIPO_ED_ST`) e dati storici disponibili.
- `PIE-PRG-STORICO-TO` - **PRG storico provincia Torino**
  - 3.699 feature overview.
  - File UI: `data/piemonte_prg_storico_torino_dest_uso_overview.geojson`.
  - File dettagliato da non usare in mappa: `data/piemonte_prg_storico_torino_dest_uso.geojson`
    (79.227 feature, circa 122 MB).
  - Sorgente:
    `/Users/emilianotrombetta/Documents/espansione del dominio/Nord/piemonte/planningCadastre/Mosaicatura_PRG_Piani_Regolatori_Generali_-_Storico__8092e59a/Mosaicatura_PRG_Torino.zip`
  - Shapefile: `TORINO/dest_uso_polyg.shp`.
  - Overview aggregata per comune, destinazione d'uso, compromissione e caratteristica storica.

### Catasto

Tema: `piemonte-catasto`.

Layer:
- `PIE-CATASTO-FOGLI` - **Catasto**
  - 489 feature.
  - File: `data/piemonte_catasto_torino_overview.geojson`.
  - Overview per foglio di mappa, non particelle singole.
  - Campi principali: `catasto`, `foglio`, `cit_foglio`, `particelle_terreni`,
    `particelle_fabbricati`, `particelle_catasto_urbano`, `particelle_acque`,
    `particelle_strade`, `totale_elementi_catastali`.

Sorgenti in:
`/Users/emilianotrombetta/Documents/espansione del dominio/Nord/piemonte/planningCadastre`

Dataset usati:
- `Catasto_Terreni_11000_-_Fogli_di_mappa__5cc34843/fogli.zip`
- `Catasto_Terreni_11000_-_Particelle_terreni__32e350bf/particelle_terreni.zip`
- `Catasto_Terreni_11000_-_Particelle_fabbricati__6865be70/particelle_fabbricati.zip`
- `Catasto_Urbano_11500__85cea270/catasto_urbano.zip`
- `Catasto_Terreni_11000_-_Particelle_acque__346e533e/particelle_acque.zip`
- `Catasto_Terreni_11000_-_Particelle_strade__abdfd249/particelle_strade.zip`

### Tutele paesaggistiche

Tema: `piemonte-paesaggio`.

Layer locali:
- `PIE-TUT-AREE-PROTETTE` - 402 feature.
- `PIE-TUT-FITOSANITARI-DIVIETO` - 3.079 feature.
- `PIE-TUT-ACQUE-SPECIFICHE` - 13 feature.
- `PIE-TUT-PREGIO-PAESAGGISTICO` - 24 feature.
- `PIE-TUT-VINCOLI-PAESAGGISTICI` - 69 feature.
- `PIE-TUT-PROTETTE-ISTITUITE` - 264 feature.
- `PIE-TUT-PROTETTE-PROV-IST` - 8 feature.
- `PIE-TUT-PROTETTE-PROV-PROP` - 4 feature.
- `PIE-TUT-CORRIDOI-ECO` - 1 feature.
- `PIE-TUT-AVE` - 19.626 feature overview.
- `PIE-TUT-CONNETTIVITA` - 10.736 feature overview.

I file generati sono in `data/piemonte_tutele_*.geojson`. Le sorgenti sono in:
`/Users/emilianotrombetta/Documents/espansione del dominio/Nord/piemonte/environment`.

Nota: `PIE-TUT-AVE` e una overview aggregata da 264.446 feature originali con cella 1 km.
`PIE-TUT-CONNETTIVITA` deriva da raster TIFF campionato, classificato in 5 classi.

### Aree naturali e biodiversita

Tema: `piemonte-natura`.

Layer:
- `PIE-NATURA-2000`
- `PIE-PPR-AMBITI`
- `PIE-PPR-VINCOLI`
- `PIE-PPR-CRINALI`

Le tre classi PPR che prima erano in Tutele paesaggistiche sono state spostate qui.

### Infrastrutture, servizi e attrattivita

Blocchi aggiornati il 2026-07-21.

Script di generazione:
- `scripts/build_piemonte_blocks_layers.py`

Output e layer:
- `PIE-SERV-ISTRUZIONE` - **Istruzione e formazione**
  - 1.024 feature.
  - File: `data/piemonte_servizi_istruzione.geojson`.
- `PIE-SERV-SANITA` - **Sanita e assistenza**
  - 487 feature.
  - File: `data/piemonte_servizi_sanita.geojson`.
- `PIE-SERV-CULTURA-SPORT` - **Cultura, sport e attrattori**
  - 3.314 feature.
  - File: `data/piemonte_servizi_cultura_sport.geojson`.
- `PIE-MOB-METRO` - **Metropolitana**
  - 45 feature.
  - File: `data/piemonte_mobilita_metro.geojson`.
- `PIE-MOB-CICLABILE` - **Rete ciclabile**
  - 4.148 feature.
  - File: `data/piemonte_mobilita_ciclabile.geojson`.
- `PIE-MOB-SHARING-RICARICA` - **Sharing e ricarica**
  - 264 feature.
  - File: `data/piemonte_mobilita_sharing_ricarica.geojson`.
- `PIE-MOB-REGOLAZIONE` - **Regolazione accessi**
  - 262 feature.
  - File: `data/piemonte_mobilita_regolazione.geojson`.
- `PIE-MOB-NODI-LOGISTICA` - **Nodi e logistica**
  - 58 feature.
  - File: `data/piemonte_mobilita_nodi_logistica.geojson`.
- `PIE-ECO-COMMERCIO` - **Attivita e luoghi del commercio**
  - 31.217 feature.
  - File: `data/piemonte_economia_commercio.geojson`.
- `PIE-ECO-MERCATI` - **Mercati e fiere**
  - 251 feature.
  - File: `data/piemonte_economia_mercati.geojson`.
- `PIE-ECO-PRODUTTIVI` - **Poli produttivi e strutture commerciali**
  - 1.414 feature.
  - File: `data/piemonte_economia_poli_produttivi.geojson`.

Temi UI:
- **Servizi e polarita territoriali** (`piemonte-servizi`): istruzione, sanita,
  cultura/sport e `PIE-PRG-SERVIZI`; 7.296 geometrie, 4 classi.
- **Mobilita e accessibilita** (`piemonte-mobilita`): stazioni PTC2, metropolitana,
  ciclabili, sharing/ricarica, regolazione accessi e nodi logistici; 4.884 geometrie,
  6 classi.
- **Commercio e sistema produttivo** (`piemonte-economia`): commercio, mercati/fiere,
  poli produttivi e strutture commerciali; 32.882 geometrie, 3 classi.

Popup dedicato: i nuovi layer mostrano categoria, tipo, indirizzo/luogo, comune,
dettaglio, lettura per investimento, fonte e layer originale.

### Modello attrattivita lat/lon

Piattaforma separata:
- `attrattivita.html`
- URL locale: `http://127.0.0.1:4188/attrattivita.html`

Script di generazione:
- `scripts/build_piemonte_attractiveness_latlon.py`

Output:
- `data/piemonte_attrattivita_latlon.geojson`
  - 6.822 punti lat/lon.
  - Griglia metrica: 1 km dentro la Citta metropolitana di Torino.
  - Ogni punto contiene `lat`, `lon`, `indice_attrattivita`, `classe_attrattivita`,
    `score_accessibilita_flussi`, `score_servizi`, `score_economia`,
    `score_mobilita_locale` e conteggi dei POI vicini.

Formula attuale:
- 35% accessibilita da flussi SVR (`mobility/svr_flow_nodes.geojson`);
- 30% servizi: istruzione, sanita, cultura/sport;
- 25% economia: commercio, mercati/fiere, poli produttivi;
- 10% mobilita locale: sharing/ricarica, nodi logistici, metro, ciclabili e regolazione
  accessi.

Metodo:
- kernel di distanza per ogni sorgente;
- normalizzazione robusta 0-100 con log e percentile 95;
- interrogazione coordinate: la piattaforma cerca il punto modello piu vicino alla coppia
  `lat/lon` inserita o cliccata in mappa.

Simulazione traffico nuovo polo:
- integrata in `attrattivita.html`;
- sorgenti caricate dal browser:
  - `mobility/svr_flow_nodes.geojson` per i nodi di pressione stradale;
  - `mobility/gtfs_stops.geojson` per le fermate GTT;
  - `mobility/gtfs_network.geojson` per linee, modalita e corse/giorno.
- Parametri scenario: tipo polo, utenti/giorno, quota ora di punta, quota auto base.
- Output: viaggi/giorno, auto/giorno, TPL stimato, auto in ora di punta, indice TPL,
  quota auto, nodi stradali SVR piu sollecitati e TPL vicino.
- Il modello distribuisce i viaggi auto sui nodi SVR entro 5 km con peso per distanza e
  flusso esistente; la quota TPL cresce con fermate e linee entro circa 1-1,5 km.

Sezione flusso su strada:
- integrata in `attrattivita.html`;
- caricamento lazy tramite pulsante **Carica flussi**;
- sorgente visualizzata: `mobility/roads_flow.geojson`;
- contenuto: 37.323 tratte lineari reali con `mfw_sum`, velocita, classe di fluidita,
  lunghezza, classe stradale e popup di tratta;
- stile: colore per `band` (`scorrevole`, `rallentato`, `critico`) e spessore per
  `mfw_sum`;
- pannello: KPI tratte/km/mfw_sum, tabella strade piu trafficate e tratti piu critici.
- Nota fonte: il grafo stradale indicato dall'utente
  `Nord/piemonte/transportation/Dati_di_base_-_Grafo_stradale__dda82fe0/grafo_stradale`
  contiene 25.538 archi EPSG:3003 con `ID_EL_ST/TOPONIMO`; il match diretto per ID con
  `roads_flow.geojson` copre 1.038 archi. Per la vista completa dei flussi su strada si
  usa quindi `roads_flow.geojson`, gia basato su geometrie lineari con dati SVR.

## 4. Flussi stradali SVR

La sezione **Flussi provincia** non usa piu il vecchio snapshot 5T/Overpass come fonte
principale. Ora usa SVR 2020 su Elemento Stradale BDTRE.

Sorgente:
`/Users/emilianotrombetta/Documents/espansione del dominio/Nord/piemonte/DatiSVR2020_su_ElementoStradaleBDTRE/DatiSVR2020_su_ElementoStradaleBDTRE.gpkg`

Artefatti:
- `mobility/roads_flow.geojson`
  - 37.323 segmenti BDTRE che intersecano la provincia di Torino.
  - Solo segmenti con `mfw_sum > 0`.
  - Circa 20 MB.
- `mobility/svr_traffic.json`
- `mobility/svr_flow_nodes.geojson`
  - 6.697 nodi/centroidi di flusso.

Endpoint:
- `/api/piemonte/traffic`
- `/api/piemonte/traffic/layer`

UI:
- `Flusso su strade`
- `Flusso ibrido`
- `Flusso (heatmap)`
- `Centroidi segmenti`
- `Rete TPL (GTT)`
- `Fermate`

Campo da mostrare e usare:
- `mfw_sum`: **flusso totale stimato**.

Nota temporale:
- SVR e un modello giornaliero/medio. In app indicare: `giorno feriale medio - no orario`.
- Non c'e misura oraria o fascia oraria nei dati SVR disponibili.

Best practice visuale gia applicata:
- linee per flusso su strada;
- heatmap per densita/intersezioni;
- vista ibrida con cerchi piu grandi, in modo che alcuni si intersechino;
- centroidi segmenti separati per lettura puntuale.

## 5. OpenCUP / Supabase

Schema Supabase: `piemonte`.

Tabella creata:
- `piemonte.opencup`

Caricamento effettuato:
- 261.198 CUP.
- Criterio: solo interventi OpenCUP in Regione Piemonte, provincia Torino / area
  metropolitana, usando `CODICE_REGIONE = '01'` e provincia `001` / sigla `TO`.
- Una riga per CUP.

Campi principali:
- `cup` primary key.
- campi progetto e soggetto.
- `comuni` jsonb.
- `localizzazioni` jsonb.
- `localization_count`.
- `raw_metadata`.
- `source_file`.
- `selection_criterion`.
- `loaded_at`.

Indici presenti:
- `stato_progetto`
- `anno_decisione`
- `categoria_intervento`
- `soggetto_titolare`
- GIN su `comuni`, `raw_metadata`, `localizzazioni`.

Conteggi stato:
- `ATTIVO`: 184.943.
- `CHIUSO`: 74.619.
- `CHIUSO D'UFFICIO`: 1.636.

OpenCUP e esposto in UI come tema **Investimenti pubblici OpenCUP**
(`piemonte-opencup`) tramite layer `PIE-OPENCUP-COMUNI`, aggregato sui 312 comuni
della Citta metropolitana di Torino.

## 6. Verifiche rapide

Server vivo:

```bash
curl -s http://127.0.0.1:4188/health
```

Catalogo:

```bash
curl -s http://127.0.0.1:4188/api/piemonte/catalog | python3 -m json.tool | head -80
```

Layer Assetto:

```bash
curl -s "http://127.0.0.1:4188/api/piemonte/layer?id=PIE-SVILUPPO-PRG" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d['features']))"
```

Catasto:

```bash
curl -s "http://127.0.0.1:4188/api/piemonte/layer?id=PIE-CATASTO-FOGLI" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d['features']))"
```

PRG storico overview:

```bash
curl -s "http://127.0.0.1:4188/api/piemonte/layer?id=PIE-PRG-STORICO-TO" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d['features']))"
```

Geometria provincia Torino:

```bash
curl -s "http://127.0.0.1:4188/api/territory?region=piemonte&code=001" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['properties']['name'], d['geometry']['type'])"
```

Flussi:

```bash
curl -s http://127.0.0.1:4188/api/piemonte/traffic \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['totals'])"
```

## 7. QA browser atteso

Su `http://10.0.0.57:4188`:

- Assetto territoriale regionale:
  - circa 719 geometrie.
  - legenda con Quartieri Torino, Comune di Torino, Provincia di Torino/comuni,
    Piano regolatore presente, Piano regolatore assente.
- Zonizzazione e disciplina comunale:
  - circa 13.312 geometrie.
  - popup utili su categoria urbanistica, edifici storici e PRG storico.
- Catasto:
  - senza filtro: 489 fogli.
  - filtro provincia Cuneo: 0.
  - filtro provincia Torino: 489.
  - filtro comune Torino: 489.
- Tutele paesaggistiche:
  - circa 34.226 geometrie.
  - circa 15 classi.
- Servizi e polarita territoriali:
  - 7.296 geometrie.
  - 4 classi: Servizi e dotazioni, Istruzione e formazione, Sanita e assistenza,
    Cultura/sport e attrattori.
- Mobilita e accessibilita:
  - 4.884 geometrie.
  - 6 classi: Stazioni ferroviarie, Metropolitana, Rete ciclabile, Sharing e ricarica,
    Regolazione accessi, Nodi e logistica.
- Commercio e sistema produttivo:
  - 32.882 geometrie.
  - 3 classi: Attivita e luoghi del commercio, Mercati e fiere, Poli produttivi e
    strutture commerciali.
- Piattaforma attrattivita lat/lon:
  - `http://127.0.0.1:4188/attrattivita.html`;
  - 6.822 punti modello;
  - input coordinate verificato: restituisce punto piu vicino, distanza e componenti
    dello score.
  - simulazione nuovo polo verificata:
    - scenario ospedale iniziale: produce viaggi/giorno, auto/giorno, TPL stimato,
      nodi SVR e TPL vicino;
    - scenario scuola su coordinate `45.20, 7.55`: ricalcolo domanda e impatto stradale,
      nessun errore console.
  - sezione **Flusso su strada** verificata:
    - caricamento lazy di `mobility/roads_flow.geojson`;
    - 37.323 tratte, circa 5.030 km, `mfw_sum` aggregato visibile;
    - tabelle strade piu trafficate/tratti critici e layer canvas su mappa;
    - pulsante mostra/nascondi funzionante, nessun errore console.
- Flussi provincia:
  - `mfw_sum` visibile come flusso totale stimato.
  - testo temporale: giorno feriale medio, nessuna misura oraria.
  - vista ibrida/heatmap con cerchi sufficientemente grandi da intersecarsi.

## 8. Prossimi passi probabili

- Correzione del 2026-07-21 ore 15:50 circa:
  - `index.html` ora classifica `PIE-QUADRO-PIANI` per `semaforo_maturita`
    (`verde`, `giallo`, `arancio`, `grigio`) invece di mostrarlo come unico layer grigio.
  - Il tema **Semaforo dei vincoli di costruzione** usa una base verde comunale
    (`PIE-PROVINCIA-TORINO`) più la disciplina PRG di Torino (`PIE-PRG-ZONE`) e
    vincoli gialli/rossi sovrapposti. La classificazione PRG sintetica mette in rosso
    le zone boscate, in giallo centro storico/storico-ambientale, verde privato,
    servizi/parchi e in verde le zone consolidate o di trasformazione da leggere nelle NTA.
  - Nel semaforo costruibilità sono stati aggiunti vincoli paesaggistici e tutele:
    `PIE-PPR-VINCOLI`, `PIE-PPR-ACQUE`, `PIE-PPR-AGRICOLTURA`, `PIE-NATURA-2000`,
    `PIE-TUT-PREGIO-PAESAGGISTICO`, `PIE-TUT-VINCOLI-PAESAGGISTICI`,
    `PIE-TUT-PROTETTE-ISTITUITE`, `PIE-TUT-PROTETTE-PROV-IST`,
    `PIE-TUT-PROTETTE-PROV-PROP`, `PIE-TUT-CORRIDOI-ECO`,
    `PIE-TUT-ACQUE-SPECIFICHE`.
  - I popup del semaforo distinguono verde/giallo/rosso e ricordano che il verde non
    equivale a edificabilità automatica: resta necessaria la verifica del PRG comunale.
  - `boot()` in `index.html` non aspetta piu obbligatoriamente `/api/ainop/regions`:
    AINOP e ora opzionale con timeout breve, cosi la dashboard Piemonte non resta bloccata
    su "Caricamento catalogo" se l'endpoint AINOP/Supabase e lento.
  - QA browser dopo la correzione:
    - **Maturità dei piani per comune**: 312 geometrie, 4 classi
      (98 verde, 64 giallo, 147 arancio, 3 grigio).
    - **Semaforo dei vincoli di costruzione**: 3 classi
      (rosso/giallo/verde); visualizzate 55.120 geometrie su 91.043 disponibili per effetto
      dei limiti di anteprima dei layer Supabase pesanti.
  - Popup/tooltip dedicati aggiunti per AIT, Stato PRGC comunale, PPR ambiti/vincoli/crinali,
    Natura 2000, PPR acque, PAI frane/esondazioni, PPR agricoltura, stazioni PTC2,
    servizi PRG, ambiti di trasformazione, progetti unitari, PUMS e tutele ambientali.
  - OpenCUP esposto in UI:
    - script: `scripts/build_piemonte_opencup_comuni.mjs`;
    - output: `data/piemonte_opencup_comuni.geojson`;
    - layer catalogo: `PIE-OPENCUP-COMUNI`;
    - tema UI: **Investimenti pubblici OpenCUP**;
    - aggregazione: 312 comuni, CUP localizzati da `piemonte.opencup`, con progetti totali,
      attivi/chiusi, periodo decisione, costo, finanziamento, settore e soggetto prevalente.
    - Avvertenza: importi dei CUP multi-comune conteggiati su ogni comune localizzato, non
      ripartiti pro quota.
    - QA browser: 312 geometrie, 4 classi su `progetti_attivi`, nessun errore console.

  - Blocchi servizi/mobilita/economia esposti in UI:
    - script: `scripts/build_piemonte_blocks_layers.py`;
    - 11 nuovi GeoJSON locali in `data/piemonte_servizi_*`, `data/piemonte_mobilita_*`,
      `data/piemonte_economia_*`;
    - 11 nuovi layer in `piemonte_catalog.mjs`;
    - temi UI: **Servizi e polarita territoriali**, **Mobilita e accessibilita**,
      **Commercio e sistema produttivo**.
    - QA browser: servizi 7.296 geometrie / 4 classi, mobilita 4.884 geometrie / 6 classi,
      economia 32.882 geometrie / 3 classi, nessun errore console.

- Raffinare popup di PRG storico con legenda piu leggibile sulle destinazioni d'uso.
- Valutare vector tiles o semplificazione multi-scala per catasto dettagliato e PRG storico
  completo.
- Aggiungere una vista "fonti/sources" che mostri provenienza, data, copertura e limiti di ogni
  layer.
- Mantenere aggiornata questa pagina ogni volta che si aggiungono o si rinominano layer.
