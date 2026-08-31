# Continua qui — Layer_Processor (handoff Claude → Claude)

> Stato al **2026-08-04**. Cartella: `/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor`.
> Questo file è **autosufficiente**: leggi solo questo per ripartire. Dettaglio storico/tecnico in `CODEX_HANDOFF_LAYER_PROCESSOR.md`.

---

## 0) Stato piattaforma — hub + deploy (agg. 2026-08-03)
- La piattaforma è ora presentata come **Pipeline Operativa** (ex "modello a 4 layer"): 7 processori su 3 stream + convergenza.
  Hub grafico interattivo in `MobilityLens_Hub.html` (root del progetto; copia anche in `mobilitylens-react/public/`, servita online).
- Processori: **Layer Processor** (ATTIVO, questo repo) → **Urbanist Processor** · **RAG** → **Updater** ⇄ **Project** · **PUMS Processor** (parallelo) → **Database Processor** → Supabase.
  Solo il Layer Processor è realizzato; gli altri sono placeholder "in sviluppo".
- **Deploy**: hub live su https://www.mobilitylens.com/MobilityLens_Hub.html (repo GitHub `MobilityLens/mobilitylens-react`).
  Fix build Vercel (mappa Leaflet → `next/dynamic` `ssr:false`) + esclusione `public/data` in **PR #126** (da mergiare).
- **Fonti — FATTO** (working tree, NON committato): la vista "Fonti" del dashboard è ora **per Regione**.

## 1) Git & stato
- **Branch**: `feat/kb-nazionale-adapters-catasto` (NON ancora fuso su `main`; l'utente decide).
- **Remote**: `origin` → `https://github.com/MobilityLens/mobilitylens-react.git`.
- **Ultimo commit**: `4f4bddb` (`feat(layer-processor): harden SPARQL source ingestion`), già pushato su
  `origin/feat/kb-nazionale-adapters-catasto`.
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
- CLI: `python3 run.py <discover|download|recognize|compose> ...`
  - `discover --source <key>` · `download --source <key> --progress [--refresh]`
  - `recognize --catalog work/catalog/<key>.csv --ente <key>`
  - `compose --targets <T> --scope-level region --scope-key <RR>`

## 3) Adapter disponibili (`lib/`)
Regionali storici: `wfs_generic`, `arcgis_rest`, `ckan_collection`, `ckan_mit`, `socrata`,
`websit_xml`, `veneto_webgis`, `emilia_romagna_moka`, `liguria_geoportal`, `piemonte_catalog`,
`vda_*`, `local_spatial`.
**Nuovi (riusabili):**
- `csv_direct` — CSV a URL diretto; converte i CSV con lat/lon in GeoJSON di punti.
- `http_download` — file/zip diretti + estrazione best-effort. SSL permissivo (SECLEVEL=1).
- `html_resources` — scrapa pagina, prende link risorsa, scarica via http_download.
- `istat_sdmx` — dataflow SDMX-CSV ISTAT (`/data/{IT1,ID,ver}/all?format=csv`).
- `sparql_source` — query SPARQL paginata (LIMIT/OFFSET) → GeoJSON (punti o tabella).
- `catasto_inspire` — parser streaming particelle INSPIRE (on-demand, non pipeline).
- **`cruscotto` (NUOVO 2026-08-04)** — adapter per cruscotto-italia.dati.gov.it: download
  parallelo ~7900 comuni, produce un CSV per sezione (turismo, PUN, ANAC, SIOPE, RUNTS,
  beni_culturali). Cache per comune in `raw/nazionale/n_cruscotto_italia/_cache/`. Workers=5
  con retry+backoff (il server blocca oltre ~100 richieste rapide).

Il dispatch è in `stages/stage_01_discover.py` e `stages/stage_02_download.py`.

## 4) Fonti — **81/81 ATTIVE** (zero todo/metadata/dead)
Fonti con adapter proprio: wfs_generic(13), emilia_romagna_moka(10), http_download(12),
html_resources(5), piemonte_catalog(3), ckan_mit(2), arcgis_rest(2), istat_sdmx(2),
sparql_source(2), cruscotto(1), + altri singoli.
Fonti con `superseded_by` (dati coperti da un'altra fonte): 12.

### Fonti attivate (2026-08-04)
- **`n_arco_beni_culturali`** — sparql_source → ArCo, 2385 comuni. Alimenta BENI_CULTURALI.
- **`n_cruscotto_italia`** — cruscotto adapter, 6 sezioni. Alimenta TURISMO/TRASPARENZA.
- **`n_istat_censimento_comuni`** — SDMX funzionante, 3/3 CSV.
- **`n_ispra_rifiuti`** — CSV, AMBIENTE_RIFIUTI 100% match.
- **`n_colonnine_ricarica`**, **`n_anac_opendata`**, **`n_runts`**, **`n_siope`**,
  **`n_istat_turismo`** — superseded_by n_cruscotto_italia.
- **7 province Veneto** (p_vr/vi/bl/tv/ve/pd/ro) — superseded_by r_veneto (IDT2 WFS).
- **`r_tn_prguso`** — attivato (WFS server sporadicamente down, gestisce gracefully).
- **`p_to_gtfs`** — attivato con http_download (ZIP 19.5 MB, licenza non-commerciale).
- **`p_bi`** — superseded_by r_piemon (link PTPv 404, dato nel Geoportale regionale).
- **`r_vda_prg_updates`** — superseded_by r_vda_prg_status.
- **`n_cultura_dataset_locali`** — superseded_by n_arco_beni_culturali (portale solo WordPress).
- **`r_lazio`** — wfs_generic, 248 layer GeoServer Lazio. **221 scaricati**.
  Riconosciuti: **178/248 (72%)** — dopo regole topic-agnostic + Lazio-specifiche.
- **`r_sardegna`** — wfs_generic, 359 layer GeoServer Sardegna. **228 scaricati** (di 359).
  Riconosciuti: **77/359 (21%)** — molti layer non ancora scaricati.
- **`r_basilicata`** — wfs_generic, 67 layer RSDI Basilicata. **Download completo** (65 file).
  Riconosciuti: **51/67 (76%)** — dopo regole topic-agnostic.

## 5) Composizione — **20/21 target con dati** · **5.78M feature** · **9 target a 20/20 regioni**
Target con composer dedicato (in `COMPOSERS` dict):
- **PIANI_MATURITA** — VdA + Lombardia funzionanti.
- **VINCOLI_COMUNALI** — overlay vincoli (PIE, VdA, FVG).
- **SEMAFORO_EDIFICABILITA** — screening tecnico per comune/lotto (solo VdA).
- **DEMOGRAFIA** — censimento ISTAT + merge IRPEF. **20/20 regioni, 7893 comuni**.
- **CONNETTIVITA_DIGITALE** — tabular_join AGCOM. **20/20 regioni**.
- **CONSUMO_SUOLO** — tabular_join ISPRA XLSX. **20/20 regioni**.
- **AMBIENTE_RIFIUTI** — tabular_join ISPRA CSV. **20/20 regioni**.
- **BENI_CULTURALI** — composer dedicato ArCo SPARQL. **20/20 regioni**.
- **TURISMO_RICETTIVITA** — tabular_join cruscotto. **20/20 regioni**.
- **TRASPARENZA_APPALTI** — tabular_join cruscotto ANAC. **20/20 regioni**.

Target generici (`compose_feature_layer`):
- **ANALISI_URBANISTICA** — **20/20 regioni** (1.32M ft). HOTOSM + PRG dove c'è WFS.
- **PUNTI_INTERESSE** — **20/20 regioni** (1.06M ft). POI HOTOSM + distributori MIMIT.
- **RISCHI_PERICOLOSITA** — **6/20** (VdA, TnAA, FVG, LAZ, BAS, SAR — 1.11M ft).
- **TUTELE_AMBIENTALI_PAESAGGISTICHE** — **8/20** (PIE, VdA, TnAA, FVG, ER, LAZ, BAS, SAR — 921k ft).
- **RETE_VIABILITA** — **6/20** (PIE, VdA, TnAA, LAZ, BAS, SAR — 795k ft).
- **ENERGIA_RETI** — **5/20** (TnAA, VEN, LAZ, BAS, SAR — 79k ft).
- **MOBILITA_ACCESSIBILITA** — **6/20** (VdA, TnAA, FVG, LAZ, BAS, SAR — 24k ft).
- **SERVIZI_POLARITA** — **4/20** (VdA, TnAA, LAZ, SAR — 4.3k ft).
- **COMMERCIO_PRODUTTIVO** — **1/20** (TnAA — 41 ft). **VALORI_OMI** — **1/20** (VdA — 1 ft).
File >200MB esclusi dal compose generico (`MAX_SOURCE_FILE_MB = 200` in compose_engine.py).

### Builder compose TABELLARE generico
`compose_tabular_join(target, scope)` in `lib/compose_engine.py`: legge il blocco `tabular:`
del target in `composition_targets.yaml`, localizza il CSV in `raw/nazionale/<ente>/**/<file>`,
indicizza per codice comune ISTAT (zfill 6, supporta code_right, skip_header_rows, XLSX/CSV).
Per aggiungere una fonte tabellare: scarica, aggiungi blocco `tabular:`, registra in COMPOSERS.

## 6) Catasto (regola utente: TUTTO dall'Agenzia Entrate)
- Nazionale INSPIRE: `ITALIA/` (19 regioni, manca il 04 TN-AA = tavolare). Motore `lib/catasto_inspire.py`.
- Trentino: `n_catasto_tn` attivo (OPENkat SHP, 792MB). **Bolzano: nessuna fonte** (lasciare vuoto).
- Per il semaforo mancano: (1) crosswalk ISTAT↔Belfiore; (2) overlay zonizzazione PRG.
- NON creare downloader catastali regionali.

## 7) Gotcha da NON ri-derivare
- **SDMX ISTAT**: HEAD dà 405; serve `/all` nel path; endpoint `esploradati.istat.it/SDMXWS/rest`.
  Accept: `application/json` (non `application/vnd.sdmx...`). L'endpoint `sdmx.istat.it` è redirect loop.
- **gov.it TLS**: contesto SSL con `set_ciphers("DEFAULT@SECLEVEL=1")`.
- **cruscotto-italia.dati.gov.it**: SSL con verify=False (`ssl.CERT_NONE`). Rate-limits a ~100 req
  rapide → usare max 5 worker con backoff. I dati sono pre-aggregati, ~200KB per comune piccolo,
  ~5MB per Roma. Cache in `_cache/<istat>.json`.
- **ArCo SPARQL**: città in UCASE inconsistente (Roma vs ROMA), normalizzare. 2527 città su 7892
  comuni (30% copertura). Endpoint: `dati.cultura.gov.it/sparql`, Accept: `application/sparql-results+json`.
- **ISPRA rifiuti**: prima riga è titolo (skip_header_rows: 1); codice 8 cifre (code_right: 6).
- **unzip nomi con accento**: estrazione best-effort (stdin=DEVNULL, check=False).

## 8) Regole di lavoro (utente)
- Parla **italiano**. **Non committare** senza richiesta esplicita. **Non pushare i dataset.**
- "Rinfresca i dati" = **solo quella regione**. Download pesanti in background, riferisci l'esito reale.
- Downloader per-regione; uniformità nella composizione.
- C'è **Codex in parallelo** sugli stessi file: non revertire il suo lavoro.
- **Output conciso**: il 70% del contesto NON deve essere occupato dai messaggi. Solo output finale.

## 9) Prossimi passi (in ordine)
1. **Trovare WFS Centro-Sud mancanti**: Toscana, Umbria, Marche, Abruzzo, Molise, Campania,
   Puglia, Calabria, Sicilia — nessun WFS pubblico trovato. Per queste regioni i geo target
   (TUTELE, RISCHI, VIABILITA, SERVIZI) restano vuoti senza dati regionali.
   Alternative: ArcGIS REST (Puglia 61 MapServer), CKAN (Toscana?), download manuali.
2. **Completare download Sardegna** — 228/359 layer scaricati, 131 mancanti. Rilanciare download
   con timeout per layer singoli per evitare stalli.
3. Catasto: crosswalk ISTAT↔Belfiore + overlay zonizzazione → semaforo per-lotto.
4. Aprire/revisionare la PR del branch.

### Gotcha cruscotto CSV
Il `compose_tabular_join` usa `sep: ";"` di default (AGCOM usa `;`). Per i CSV del cruscotto
(che usa `,`) serve `sep: ","` nel blocco tabular. Corretto per TURISMO e TRASPARENZA.

### Gotcha compose_feature_layer scope
Lo scope va passato come `{'level': 'region', 'key': '04'}` — NON `scope_level`/`scope_key`.

### Gotcha layer_dictionary topic_in
Molti WFS regionali (Basilicata, Lazio, Sardegna) pubblicano tutto come `planningCadastre`.
Le regole con `topic_in: [geoscientificInformation]` non matchano. Aggiunto blocco di regole
topic-agnostic con keyword specifiche (pericolosita, iffi, danno, litologia, ecc.) — 2026-08-05.

## Verifica veloce che tutto compili
```bash
cd Layer_Processor
python3 -c "import py_compile,glob; [py_compile.compile(f,doraise=True) for f in glob.glob('lib/*.py')+glob.glob('stages/*.py')+['dashboard_server.py','run.py']]; print('OK')"
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['registry/sources.yaml','registry/composition_targets.yaml','registry/canonical_taxonomy.yaml','registry/layer_dictionary.yaml']]; print('YAML OK')"
```
