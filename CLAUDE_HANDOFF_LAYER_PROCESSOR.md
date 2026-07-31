# Handoff per Claude — Layer Processor nazionale

Aggiornato al **28 luglio 2026**.

Questo documento è la fotografia autorevole dello stato corrente del progetto:

```text
/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor
```

Le descrizioni più vecchie che parlano di stadi ancora completamente stub, di
`Catalogo non configurato` per la Valle d’Aosta o di token obbligatorio per tutti
i servizi pubblici valdostani sono superate.

La piattaforma Piemonte in:

```text
/Users/emilianotrombetta/Library/Application Support/PiemonteBeta/app
```

è un progetto distinto. Può essere usata come riferimento per tassonomia,
composizione e resa cartografica, ma non va modificata salvo richiesta esplicita.

---

## 1. Obiettivo del modello

Layer Processor deve generalizzare a tutta Italia il lavoro svolto inizialmente
su Piemonte/Torino.

La pipeline ha cinque stadi:

1. **Scoperta fonti** — individua servizi, mappe, layer e metadati ufficiali.
2. **Download** — scarica i dati grezzi in batch, con checkpoint e ripresa.
3. **Riconoscimento** — associa i dataset alla tassonomia canonica.
4. **Composizione** — genera i layer cartografici finali.
5. **Caricamento** — valida e pubblica i risultati con procedura controllata.

L’ordine territoriale ordinario è:

```text
regione → provincia/città metropolitana → comune
```

Il profilo regionale può modificarlo. In Valle d’Aosta la pianificazione è:

```text
regione → comune
```

Il contenitore provinciale valdostano può esistere tecnicamente nella
cartografia amministrativa, ma non costituisce un livello ordinario di piano.

---

## 2. Avvio locale

Metodo più semplice:

```bash
cd "/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor"
open "Avvia Layer Processor.command"
```

Avvio manuale del controller:

```bash
cd "/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor"
python3 -u dashboard_server.py
```

Avvio manuale del frontend:

```bash
cd "/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor/dashboard"
npm run dev
```

Indirizzi:

```text
Dashboard:  http://localhost:3000
API locale: http://127.0.0.1:8765
Health:     http://127.0.0.1:8765/api/health
```

Al momento dell’handoff frontend e controller locali sono stati verificati e
avviati. Se si modifica `dashboard_server.py`, il controller deve essere
riavviato. Il frontend usa HMR.

---

## 3. Stato attuale della dashboard

File principali:

```text
dashboard/app/page.tsx
dashboard/app/globals.css
dashboard_server.py
```

La dashboard contiene tre sezioni principali.

### Processi

- Cinque sezioni corrispondenti agli stadi del modello.
- Tutte le sezioni sono espandibili/collassabili.
- Avvio degli script tramite pulsanti, senza aprire manualmente i file `.py`.
- Stato della run, avanzamento, tempo trascorso e chiamate individuali.
- Filtri sulle chiamate concluse, fallite, in corso o saltate.
- Download suddiviso in batch.
- Interruzione e ripresa dal checkpoint.
- Storico delle esecuzioni filtrabile.
- Composizione con selezione dei prodotti da generare.
- Pulsante per visualizzare i layer finali del territorio appena elaborato.

### Territorio

- Mappa nazionale interattiva.
- Selezione di regione e provincia dalla mappa.
- Percentuale di completamento per territorio.
- Ognuno dei cinque stadi vale il 20%.
- Il 100% significa: fonti scoperte, dati scaricati, riconoscimento completato,
  layer finali creati e caricamento completato.
- Dettaglio di fonti, layer finali, copertura dei piani e prossimo stadio.
- Classifica di avanzamento delle regioni.

### Fonti

Nuova sezione implementata il 28 luglio 2026.

L’utente può selezionare:

```text
regione → provincia → comune
```

e visualizzare le fonti applicabili al territorio.

La pagina mostra:

- nome della fonte e dell’ente;
- collegamento al portale ufficiale;
- stato della fonte;
- livello amministrativo;
- rapporto con il territorio selezionato;
- tipi di piano o strumenti urbanistici associati;
- tipo tecnico della fonte.

Relazioni possibili:

| Relazione | Significato |
|---|---|
| `diretta` | fonte dello stesso livello del territorio selezionato |
| `sovraordinata` | fonte regionale/provinciale applicabile a un livello inferiore |
| `locale` | fonte provinciale/comunale contenuta nel territorio selezionato |
| `nazionale` | dataset operativo valido per tutti i territori |

Filtri disponibili:

- ricerca testuale;
- tipo di piano;
- livello della fonte;
- solo fonti attive;
- azzeramento rapido dei filtri.

API:

```text
GET /api/sources?level=region&key=02&name=Valle%20d%27Aosta
GET /api/sources?level=province&key=001&name=Torino
GET /api/sources?level=municipality&key=001272&name=Torino
```

La risposta include:

```text
scope
total
active
status_counts
sources[]
```

Il selettore supporta fino a 500 comuni per provincia. È stato verificato il
percorso completo Piemonte → Torino → Comune di Torino.

---

## 4. Registro delle fonti

File di verità:

```text
registry/sources.yaml
```

Al momento contiene **13 fonti**:

- fonti regionali Piemonte;
- tre fonti regionali Valle d’Aosta;
- fonte regionale Liguria;
- fonti provinciali/metropolitane Torino e Biella;
- fonte comunale Torino;
- cinque fonti nazionali operative.

Ogni fonte può dichiarare:

```yaml
key:
livello:
ente:
region_istat:
province_istat:
comune_istat:
kind:
url:
plan_types:
planning_instruments:
status:
notes:
```

`planning_instruments` contiene il nome esplicito dello strumento, per esempio:

```text
PTP, PRG, PRGC, PTR, PPR, PAI, PTC, PTM, PUC, PTC2, PTPv, PUMS, PNRR
```

Non sostituire questi valori con la sola categoria generica `regolatore`,
`stato` o `operativo`: la UI deve mostrare il tipo di piano comprensibile.

Con la Valle d’Aosta selezionata, l’API completa restituisce otto fonti:

- cinque nazionali;
- geoportale SCT;
- stato ufficiale dei PRG;
- feed aggiornamenti dei PRG.

---

## 5. Valle d’Aosta

Profilo:

```text
registry/regional_planning_profiles.yaml → profiles."02"
```

Strumenti attesi:

- **PTP** regionale, sovraordinato;
- **PRG/PRGC** per tutti i 74 comuni;
- nessun PTCP provinciale.

Fonti ufficiali:

```text
Repertorio:
https://mappe.regione.vda.it/pub/geoCartoSCT/

Stato di adeguamento PRG:
https://mappe.regione.vda.it/pub/geonavitg/geopiani.asp

PTP:
https://mappe.regione.vda.it/pub/geonavsct/index.html?repertorio=PTP_Vincoli
```

Adapter principale:

```text
lib/vda_platform.py
```

I servizi ArcGIS `domini1/Public` rispondono con HTTP 499 se interrogati
direttamente, ma il viewer pubblico utilizza il proxy INVA:

```text
https://mappe.regione.vda.it/INVA/config/config.ashx?
```

Il proxy inserisce lato server il token necessario ai servizi pubblici. Per
questo flusso non serve salvare credenziali locali.

Discovery tecnico verificato:

```text
56 servizi Public
856 layer
```

Il repertorio utente comprende 44 temi generali e la selezione completa dei sei
servizi PTP.

Download:

- query ArcGIS paginata;
- `objectIds` in blocchi;
- output GeoJSON WGS84;
- file in `raw/regione/r_vda/<servizio>/<layer>.geojson`;
- ripresa automatica dei file già presenti;
- chiamate e fallimenti visibili in dashboard.

L’ultima run di download è terminata, ma lo stadio può restare indicato come
`parziale` finché non sono disponibili tutti i layer attesi. Non confondere il
100% della singola run con la copertura certificata dell’intero catalogo.

Metadati PRG:

```text
lib/vda_prg_updates.py
work/metadata/r_vda_prg_updates.json
```

Contengono stato ufficiale di adeguamento e, quando presente, data di
aggiornamento del PRG.

---

## 6. Liguria

Profilo:

```text
registry/regional_planning_profiles.yaml → profiles."07"
```

Gerarchia attesa:

- PTCP paesistico con efficacia transitoria;
- progetto PPR;
- PTR;
- PTC delle Province di Imperia, Savona e La Spezia;
- PTM della Città metropolitana di Genova;
- PUC comunali;
- piani di bacino come overlay obbligatorio.

Non trattare automaticamente progetto PPR e Documento preliminare PTR come
piani definitivamente approvati.

Geoportale:

```text
https://srvcarto.regione.liguria.it/geoviewer2/pages/apps/geoportale/index.html
```

Adapter:

```text
lib/liguria_geoportal.py
```

Discovery noto:

```text
350 mappe nella sezione CARTE TEMATICHE
2.281 layer risolti
1.459 layer dichiarati scaricabili
```

Il catalogo Liguria non va dichiarato completamente scaricato finché manifest e
conteggi non lo dimostrano.

---

## 7. Download, batch e ripresa

Comandi principali:

```bash
python3 run.py discover --source r_vda --progress
python3 run.py download --source r_vda --progress
python3 run.py download --source r_vda --max-services 25 --progress
python3 run.py download --source r_vda --refresh --progress
```

Semantica:

- `batch_size = 0` / “Tutte” scarica tutti i pendenti;
- `5`, `25`, `50`, `100` limitano la singola esecuzione;
- “Solo dati nuovi” salta i file già presenti;
- `--refresh` forza il nuovo download;
- ogni layer completato costituisce un checkpoint;
- una run interrotta può essere ripresa dalla dashboard.

Non cancellare dati grezzi o checkpoint per simulare una ripartenza.

---

## 8. Riconoscimento

File:

```text
registry/canonical_taxonomy.yaml
registry/layer_dictionary.yaml
lib/recognize.py
stages/stage_03_recognize.py
```

Stato osservato al momento dell’handoff:

```text
r_piemon: 336 / 945 riconosciuti (35,6%)
p_to:     186 / 405 riconosciuti (45,9%)
r_vda:    185 / 856 riconosciuti (21,6%)
```

I dataset non riconosciuti vanno in:

```text
work/proposals/<ente>.json
```

Regola di governance:

- il matcher propone;
- non esegue merge semantici ambigui;
- le nuove regole vanno aggiunte manualmente al dizionario;
- una formulazione non deve puntare a più classi incompatibili.

---

## 9. Composizione

File di verità:

```text
registry/composition_targets.yaml
```

Motore:

```text
lib/compose_engine.py
lib/composition_state.py
stages/stage_04_compose.py
```

Tre prodotti finali:

### PIANI_MATURITA

Stato di adeguamento dei piani regolatori comunali, rappresentato tramite
poligoni comunali.

Classi principali:

```text
APPROVATO
APPROVATO_CARTOGRAFIA_IN_CONSEGNA
DEFINITIVO_IN_VALUTAZIONE
BOZZA_VALUTATA
BOZZA_IN_VALUTAZIONE
ITER_NON_AVVIATO
NON_DETERMINATO
```

Per la Valle d’Aosta il mapping APP/APC/VIC/BVT/BCV/AFF/INA è già definito.

### VINCOLI_COMUNALI

Layer cartografico dei vincoli ritagliati sul confine comunale.

Ogni feature deve conservare almeno:

```text
comune e codice ISTAT
famiglia e nome del vincolo
severità ed effetto
fonte e URL
classe canonica
confidence del riconoscimento
provenienza territoriale
```

### SEMAFORO_EDIFICABILITA

Verdetto territoriale:

- verde;
- giallo;
- rosso;
- grigio/non valutabile.

Non assegnare verde, giallo o rosso senza gli input urbanistici e i vincoli
necessari. Quando gli input sono incompleti, pubblicare `UNASSESSED` con
`missing_inputs` e disclaimer.

Stato già verificato sulla Valle d’Aosta:

```text
PIANI_MATURITA:        74 comuni
VINCOLI_COMUNALI:      circa 3.895 feature
SEMAFORO_EDIFICABILITA: overview comunale UNASSESSED quando manca P4 Zone
```

Gli output sono:

```text
out/<TARGET>/<territorio>.geojson
out/<TARGET>/<territorio>.manifest.json
```

I manifest registrano fingerprint e fonti. La UI distingue:

```text
assente
presente
da_aggiornare
```

---

## 10. Caricamento

Lo stadio 05 resta sottoposto ad approvazione.

Seguire:

```text
pipeline/PIPELINE_CONTRACT.md
pipeline/sql/01_staging.sql
pipeline/sql/02_promote.sql
```

Ordine obbligatorio:

```text
staging → dry-run con rollback → report → approvazione utente → promote atomico
```

Non eseguire scritture Supabase reali senza dry-run verificato e approvazione
esplicita dell’utente.

Non stampare o committare `.env`, URL con credenziali, token o chiavi.

---

## 11. File importanti

```text
Layer_Processor/
├── dashboard/
│   ├── app/page.tsx
│   ├── app/globals.css
│   └── tests/rendered-html.test.mjs
├── dashboard_server.py
├── run.py
├── registry/
│   ├── sources.yaml
│   ├── regional_planning_profiles.yaml
│   ├── composition_targets.yaml
│   ├── canonical_taxonomy.yaml
│   └── layer_dictionary.yaml
├── lib/
│   ├── vda_platform.py
│   ├── vda_prg_updates.py
│   ├── liguria_geoportal.py
│   ├── planning_context.py
│   ├── composition_state.py
│   └── compose_engine.py
├── stages/
│   ├── stage_01_discover.py
│   ├── stage_02_download.py
│   ├── stage_03_recognize.py
│   ├── stage_04_compose.py
│   └── stage_05_load.py
├── raw/
├── work/
├── out/
└── state/
```

Gerarchie e geometrie amministrative:

```text
Geography_Locations/outputs/admin_regions.geojson
Geography_Locations/outputs/admin_provinces.geojson
Geography_Locations/outputs/admin_municipalities.geojson
```

Alias territoriali:

```text
pipeline/aliases/comune_aliases.csv
pipeline/aliases/comune_exceptions.csv
pipeline/aliases/NORMALIZATION_RULES.md
```

---

## 12. Verifiche

Comandi:

```bash
cd "/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor"

python3 -m py_compile dashboard_server.py run.py lib/*.py stages/*.py
python3 run.py status
git diff --check

cd dashboard
npm test
```

Ultima verifica del 28 luglio 2026:

- compilazione Python riuscita;
- YAML delle 13 fonti valido;
- tutti i record hanno `planning_instruments`;
- build frontend riuscita;
- 2 test frontend superati;
- API `/api/sources` verificata per regione, provincia e comune;
- filtri Fonti verificati nel browser locale;
- selezione del Comune di Torino verificata.

---

## 13. Vincoli tecnici e gotcha

- Usare `urllib` quando possibile: non assumere la presenza di `requests`.
- Output cartografico finale in EPSG:4326.
- Rilevare il CRS sorgente; non assumere sempre EPSG:32632.
- Alcuni shapefile richiedono encoding `latin-1`.
- Archivi Deflate64: usare `unzip` di sistema.
- Non caricare in UI geometrie enormi senza overview o paginazione.
- Le chiamate massive devono essere suddivise in batch.
- Conservare sempre URL, ente, livello, identificativo e fingerprint di fonte.
- Non inventare classificazioni quando mancano gli input.
- La working tree contiene modifiche e file non committati: non cancellare,
  resettare o sovrascrivere cambiamenti preesistenti.

---

## 14. Prossime priorità

1. Completare e certificare la copertura effettiva del download Valle d’Aosta.
2. Risolvere il download dei layer grandi `P4 Zone` e `P4 Zone (BORDI)`.
3. Ricomporre il Semaforo valdostano alla scala urbanistica reale.
4. Migliorare il dizionario usando i proposal VdA e Piemonte.
5. Estendere il motore di composizione alla Liguria.
6. Aggiungere progressivamente le fonti mancanti delle altre regioni,
   specificando sempre `planning_instruments`.
7. Ottimizzare il caricamento dell’elenco comunale nella dashboard se il tempo
   di risposta diventa rilevante.
8. Implementare e verificare il dry-run dello stadio 05 prima di qualsiasi
   pubblicazione.

---

## 15. Regola finale per il passaggio di consegne

Prima di cambiare il modello:

1. leggere questo file;
2. leggere `README.md`;
3. leggere `pipeline/PIPELINE_CONTRACT.md`;
4. controllare `git status --short`;
5. verificare lo stato del controller e delle run in corso;
6. preservare dati raw, checkpoint e modifiche non committate.

La dashboard non è una semplice demo grafica: deve rimanere il pannello locale
da cui avviare gli script reali, seguirne l’avanzamento, interromperli, riprenderli
e controllare la copertura territoriale e le fonti ufficiali.
