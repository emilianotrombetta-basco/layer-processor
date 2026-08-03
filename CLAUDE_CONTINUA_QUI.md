# Continua qui — Layer_Processor (handoff Claude → Claude)

> Stato al **2026-08-03**. Cartella: `/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor`.
> Questo file è **autosufficiente**: leggi solo questo per ripartire. Dettaglio storico/tecnico in `CODEX_HANDOFF_LAYER_PROCESSOR.md`.

---

## 0) Stato piattaforma — hub + deploy (agg. 2026-08-03)
- La piattaforma è ora presentata come **Pipeline Operativa** (ex "modello a 4 layer"): 7 processori su 3 stream + convergenza.
  Hub grafico interattivo in `MobilityLens_Hub.html` (root del progetto; copia anche in `mobilitylens-react/public/`, servita online).
- Processori: **Layer Processor** (ATTIVO, questo repo) → **Urbanist Processor** · **RAG** → **Updater** ⇄ **Project** · **PUMS Processor** (parallelo) → **Database Processor** → Supabase.
  Solo il Layer Processor è realizzato; gli altri sono placeholder "in sviluppo".
- **Deploy**: hub live su https://www.mobilitylens.com/MobilityLens_Hub.html (repo GitHub `MobilityLens/mobilitylens-react`).
  Fix build Vercel (mappa Leaflet → `next/dynamic` `ssr:false`) + esclusione `public/data` in **PR #126** (da mergiare).
- **Prossimo passo UI (Fonti)**: passare dal raggruppamento **per ente editore** (`sources_catalog()`, esplode in decine di card
  "Provincia di X · 1 dataset") a un modello **per Regione** con i dataset **nazionali validi per tutte le regioni**
  (`sources_payload(scope)` esiste già: torna regionali + provinciali + nazionali con relationship). + filtro per dataset.

## 1) Git & stato
- **Branch**: `feat/kb-nazionale-adapters-catasto` (NON ancora fuso su `main`; l'utente decide).
- **Commit fatti**: `4de3da8` (KB + 5 adapter + DEMOGRAFIA + motore catasto + dashboard Fonti) e
  `a0e85a1` (+9 fonti browser + fix estrazione).
- **NON committato** (lavoro in corso, sul working tree): l'adapter **`lib/sparql_source.py`** +
  wiring negli stage + `dashboard_server.py` (formats) + `registry/sources.yaml` (`n_cultura_on` → attivo).
  → **Da committare** appena riprendi (tutto testato e funzionante).
- **NON pushare i dataset.** `.gitignore` blindato: `ITALIA/` (28 GB), `raw/`, `work/`, `out/`,
  `dashboard/node_modules`, `dist`, i CSV/zip scaricati. Committa SOLO codice/config/docs.
  Escludi sempre `tools/node_modules` (gitlink).

## 2) Cos'è & architettura
Pipeline a stadi che scala l'approccio Torino a tutta Italia:
`01 discover → 02 download → 03 recognize → 04 compose` (→ 05 Supabase, futuro).
Obiettivo finale: **semaforo di edificabilità** per comune/lotto + layer tematici uniformi.
- Registry fonti: `registry/sources.yaml`. Target compose: `registry/composition_targets.yaml`.
  Tassonomia: `registry/canonical_taxonomy.yaml`; dizionario recognize: `registry/layer_dictionary.yaml`.
- **Dashboard** (2 processi): API Python `dashboard_server.py` su **:8765**; UI React/Vite in
  `dashboard/` su **:3000** (`npm run dev`). Avvio di entrambi: `python3 start_dashboard.py`.
  La UI parla con l'API hardcoded a `127.0.0.1:8765`. Dopo modifiche a `dashboard_server.py`
  **riavvia l'API**; la UI (vite) fa hot-reload da sola (se l'HMR si impianta, riavvia `npm run dev`).
- CLI: `python3 run.py <discover|download|recognize|compose> ...`
  - `discover --source <key>` · `download --source <key> --progress [--refresh]`
  - `recognize --catalog work/catalog/<key>.csv --ente <key>`
  - `compose --targets <T> --scope-level region --scope-key <RR>`

## 3) Adapter disponibili (`lib/`)
Regionali storici: `wfs_generic`, `arcgis_rest`, `ckan_collection`, `ckan_mit`, `socrata`,
`websit_xml`, `veneto_webgis`, `emilia_romagna_moka`, `liguria_geoportal`, `piemonte_catalog`,
`vda_*`, `local_spatial`.
**Nuovi (questa sessione, riusabili):**
- `csv_direct` — CSV a URL diretto; converte i CSV con lat/lon in GeoJSON di punti.
- `http_download` — file/zip diretti + estrazione unzip **best-effort** (una voce non estraibile
  dà `extract_warning`, non fallisce). SSL permissivo (SECLEVEL=1) per i gov.it.
- `html_resources` — scrapa una pagina, prende i link risorsa (anche datati), scarica via http_download.
- `istat_sdmx` — dataflow SDMX-CSV ISTAT (`/data/{IT1,ID,ver}/all?format=csv`).
- `sparql_source` — query SPARQL paginata (LIMIT/OFFSET) → GeoJSON (punti da lat/lon o tabella).
- `catasto_inspire` — MOTORE (non adapter di pipeline): parser streaming particelle INSPIRE +
  navigazione zip annidati `ITALIA/<REG>.zip→<PROV>.zip→<COMUNE>.zip→_ple.gml`. On-demand.
Il dispatch è in `stages/stage_01_discover.py` e `stages/stage_02_download.py`; il set "eseguibile"
(per `download_available` in dashboard) è la dict `formats` in `compact_source` (`dashboard_server.py`).

## 4) Fonti KB nazionali — 27 nuove, **17 ATTIVE**
Attive e scaricabili (adapter · → target):
`n_mimit_carburanti`(csv_direct→PUNTI_INTERESSE, **composto**) · `n_istat_censimento_sezioni`
(http_download→DEMOGRAFIA, **composto**) · `n_salute_presidi`(html_resources→SERVIZI_POLARITA) ·
`n_miur_scuole`(html_resources→SERVIZI_POLARITA) · `n_anncsu`(http_download→RETE_VIABILITA) ·
`n_istat_asia_ul`(istat_sdmx→COMMERCIO; NB aggregato per classe ampiezza, non comune) ·
`n_istat_pendolarismo`(http_download zip BULK→MOBILITA) · `n_toponimi_italia`(http_download GPKG IGM) ·
`n_ispra_idrogeo`(http_download API /pir/comuni→RISCHI) · `n_aci_opendata`(http_download→MOBILITA) ·
`n_istat_posas`(html_resources 107 zip prov→DEMOGRAFIA) · `n_mef_irpef`(http_download CSV comunale→DEMOGRAFIA) ·
`n_mef_immobili_pubblici`(html_resources→ANALISI_URBANISTICA) · `n_ispra_suolo`(http_download XLSX→ANALISI_URBANISTICA) ·
`n_istat_basi_territoriali`(html_resources shp sezioni 2021) · `n_catasto_tn`(http_download SHP ~792MB→SEMAFORO) ·
`n_cultura_on`(**sparql_source**→PUNTI_INTERESSE: 6260 luoghi cultura geolocalizzati ✅).
Dashboard "Fonti": **~51/77 scaricabili**.

### Ancora TODO (~10) — tail duro, tecnica dedicata
- **SPARQL (adapter c'è, servono le query)**: `n_cultura_dataset_locali`, `n_arco_beni_culturali`
  → stesso `sparql_source`, endpoint `dati.cultura.gov.it/sparql`. La query geo che funziona:
  `PREFIX geo:<http://www.w3.org/2003/01/geo/wgs84_pos#> SELECT ?s ?nome ?lat ?long WHERE
  {?s geo:lat ?lat; geo:long ?long. OPTIONAL{?s rdfs:label ?nome}}`. Per ArCo servono predicati
  specifici (schede catalografiche, spesso senza geo). **PROSSIMO PASSO NATURALE.**
- **WAF/blocco navigazione**: `n_anac_opendata` ("Request Rejected"), `n_ispra_rifiuti`.
- **Auth/API cloud**: `n_colonnine_ricarica` (PUN: AWS API Gateway+OAuth in config.json, o feature
  service ArcGIS su hub-pun-gse.maps.arcgis.com da individuare).
- **SPA con export via interazione**: `n_runts`, `n_siope`, `n_agcom_connettivita`,
  `n_istat_censimento_comuni` (gli URL `DWL/PERMPOP/MUN/<flow>` sono SPA, zip reale ignoto).
- **SDMX lento**: `n_istat_turismo` (id dataflow da trovare via `dataflow/IT1/all/latest?detail=allstubs`).
- **METODO che funziona** per le SPA: nel browser → `navigate` alla pagina → `javascript_exec`
  estrai gli `<a>` con href .csv/.zip/.xlsx → se non ci sono, `read_network_requests` per le XHR
  (o leggi `config.json`) → cabla con http_download/html_resources.

## 5) Composizione
- **DEMOGRAFIA** ha builder dedicato `compose_demografia` (`lib/compose_engine.py`, in `COMPOSERS`):
  legge il censimento ISTAT per sezione della regione (`raw/nazionale/n_istat_censimento_sezioni/
  dati_regionali_2023/extracted/.../R<NN>_*.xlsx`), aggrega per PROCOM→comune (P1=pop, P2/P3 M/F,
  P14-P29 età), calcola indici, unisce alla geometria comunale. Provato VdA (122.877 ab.).
  Join chiave: `str(PROCOM).zfill(6)` == admin `key`.
- **Ricetta fonte nazionale a PUNTI → layer** (provata su MIMIT→PUNTI_INTERESSE): adapter scarica/
  converte in GeoJSON punti → `applies_to_all_regions: true` sulla fonte → classe canonica in
  `canonical_taxonomy.yaml` + regola in `layer_dictionary.yaml` → aggiungi la classe alle `sources:`
  del target → (opz.) ramo in `compose_feature_layer` per name/licenza → recognize + compose.
- **5 target `planned: true`** (BENI_CULTURALI, CONNETTIVITA_DIGITALE, TRASPARENZA_APPALTI,
  TURISMO_RICETTIVITA, AMBIENTE_RIFIUTI): esclusi dalla completezza compose finché non alimentati.
- **DA FARE**: builder compose per dati **tabellari** nazionali (CSV/XLSX → join a geometria comune
  ISTAT) per far fruttare IRPEF/ASIA/immobili/consumo-suolo, ecc. MIMIT/cultura_on erano facili
  (coord native); questi sono tabelle da joinare per codice comune.

## 6) Catasto (regola utente: TUTTO dall'Agenzia Entrate)
- Nazionale INSPIRE: `ITALIA/` (19 regioni, manca il 04 TN-AA = tavolare). Motore `lib/catasto_inspire.py`
  pronto e provato (Allein 7.649 particelle → `out/CATASTO_PARTICELLE/A205_ALLEIN.geojson`).
- Trentino: `n_catasto_tn` attivo (OPENkat SHP). **Bolzano: nessuna fonte** (lasciare vuoto).
- **Per il semaforo mancano 2 pezzi**: (1) crosswalk **ISTAT↔Belfiore** (admin usa ISTAT, catasto usa
  Belfiore: match per nome comune o tabella ISTAT codici catastali); (2) overlay zonizzazione PRG
  sulle particelle → classificazione edificabilità.
- NON creare downloader catastali regionali; i layer `topic: planningCadastre` sono PRG/PUG (zonizzazione).

## 7) Dashboard "Fonti" (ridisegnata)
Sezione unificata (ex "Fonti"+"Per fonte") **raggruppata per ENTE EDITORE** (categorie collassabili:
ISTAT, ISPRA, MEF, MIC, Agenzia Entrate…; `.gov` generici → "OpenData Governo"). Card categoria =
nome+icona+"N dataset · X scaricabili"+Scarica gruppo+chevron; espansa → dataset con Scarica/Riscarica ·
Verifica (badge disponibilità) · Fonte↗. Toolbar: Solo scaricabili · Solo dati nuovi · Aggiorna · Scarica tutte.
Backend: `sources_catalog()` (raggruppa per `_publisher`), `/api/sources/check?key=`,
`POST /api/jobs {source}` (singola) e `{sources:[...]}` (gruppo/tutte), `start_source_stage`/`start_sources_batch`.
Frontend: `dashboard/app/page.tsx` + CSS `dashboard/app/globals.css` (`.catalog-*`).

## 8) Gotcha da NON ri-derivare
- **SDMX ISTAT**: HEAD dà 405; serve `/all` nel path; i dataflow "BULK" non hanno `/data` → il file
  zip sta nell'annotazione `ATTACHED_DATA_FILES` della struttura dataflow (via browser/curl).
- **gov.it TLS**: molti (salute, mimit portale, ecc.) rifiutano l'handshake default di Python →
  contesto SSL con `set_ciphers("DEFAULT@SECLEVEL=1")` (già in http_download/html_resources/sparql/`_check_url`).
- **unzip nomi con accento**: davano "write error" e facevano fallire tutto → estrazione best-effort
  (stdin=DEVNULL, check=False) già in `http_download._extract_zip`.
- **SPARQL**: nel `PREFIX` usa `#` letterale (non `%23`) o lo doppio-encodi → 0 risultati.
- **Trento webgis / Torino / Bolzano / Deflate64**: vedi CODEX_HANDOFF (proxy ogcproxy, outputFormat=geojson,
  path OWS per host, unzip di sistema).

## 9) Regole di lavoro (utente)
- Parla **italiano**. **Non committare** senza richiesta esplicita. **Non pushare i dataset.**
- "Rinfresca i dati" = **solo quella regione**. Download pesanti in background, riferisci l'esito reale (conteggi/errori), niente ottimismo.
- Downloader **per-regione** (specificità territoriale); l'uniformità sta nella composizione.
- C'è **Codex in parallelo** sugli stessi file (Lombardia/Veneto/E-R, recognize, mapping): non revertire il suo lavoro, coordina via CODEX_HANDOFF.

## 10) Prossimi passi (in ordine)
1. **Committa** il lavoro SPARQL (sparql_source + cultura_on) sul branch.
2. **SPARQL cultura_dataset_locali + ArCo** (stesso adapter, query da rifinire) → BENI_CULTURALI.
3. Continua il tail SPA col metodo browser (RUNTS/SIOPE/AGCOM/colonnine/turismo/censimento_comuni/ANAC/ISPRA rifiuti).
4. **Builder compose tabellare** (join CSV/XLSX comune→geometria) per IRPEF/ASIA/immobili/suolo → i rispettivi target.
5. Catasto: crosswalk ISTAT↔Belfiore + overlay zonizzazione → semaforo per-lotto.

## Verifica veloce che tutto compili
```bash
cd Layer_Processor
python3 -c "import py_compile,glob; [py_compile.compile(f,doraise=True) for f in glob.glob('lib/*.py')+glob.glob('stages/*.py')+['dashboard_server.py','run.py']]; print('OK')"
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['registry/sources.yaml','registry/composition_targets.yaml','registry/canonical_taxonomy.yaml','registry/layer_dictionary.yaml']]; print('YAML OK')"
```
