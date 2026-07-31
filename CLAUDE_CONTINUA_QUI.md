# Continua qui — Layer_Processor (handoff Claude → Claude)

> Handoff per una nuova chat Claude, perché il contesto della precedente stava finendo.
> Progetto: `/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor`
> **Niente è stato committato.** L'utente committa quando decide lui.
> Per il dettaglio tecnico completo leggi **`CODEX_HANDOFF_LAYER_PROCESSOR.md`** (sezione in cima `AGGIORNAMENTO SESSIONE 2026-07-29`, sottosezioni A–H).

---

## 🔶 AGGIORNAMENTO 2026-07-31 sexies (+4 fonti: toponimi/ISPRA idrogeo/ACI/POSAS) — leggi prima

**Niente committato dopo il commit `4de3da8` (branch feat/kb-nazionale-adapters-catasto).**

- **n_toponimi_italia** (http_download) attivo: GeoPackage IGM `geonames.gpkg` (~586 MB,
  risorsa unica dal CKAN dati.gov.it). Non scaricato nel test (grande).
- **n_ispra_idrogeo** (http_download) attivo: API REST `idrogeo.isprambiente.it/api/pir/comuni`
  = indice 7899 comuni (JSON, 2.2 MB). Gli INDICATORI di rischio per-comune sono in
  `/api/pir/comuni/{uid}` → arricchimento in compose.
- **n_aci_opendata** (http_download) attivo e testato: Autoritratto 2023 (parco veicoli)
  + Annuario 2024, zip OD diretti da aci.gov.it.
- **n_istat_posas** (html_resources) attivo: demo.istat.it pubblica ~112 zip PER PROVINCIA
  (link diretti nella pagina) → discover ne trova 107. Popolazione età/sesso 1/1/2026.
- **FIX estrazione zip best-effort** in `http_download._extract_zip`: `stdin=DEVNULL` +
  `check=False`; una voce non estraibile (es. nome file con accento → write error di
  unzip) ora dà `extract_warning`, NON fa fallire il download. (Sbloccava ACI.)

**Catalogo "Fonti": 49/77 scaricabili. Delle 27 fonti KB nuove: 15 attive.**

### +4 crackate col BROWSER (ispezione link/JS) e cablate
- **n_mef_irpef** (http_download): CSV comunale 2024 diretto
  `finanze.gov.it/.../v_4_0_0/contenuti/Redditi_..._comunale_CSV_2024.zip` → DEMOGRAFIA.
- **n_mef_immobili_pubblici** (html_resources): 30 zip per categoria PA da
  de.mef.gov.it/.../dati_immobili_2023.html (pattern `Imm_.*_2023.zip`) → ANALISI_URBANISTICA.
- **n_ispra_suolo** (http_download): XLSX `consumo_di_suolo_estratto_dati_2025_anni_2006_2024.xlsx`
  (regionale/prov/comunale) → ANALISI_URBANISTICA.
- **n_istat_basi_territoriali** (html_resources): 20 shapefile regione sezioni 2021
  (`istat.it/storage/cartografia/basi_territoriali/2021/R<NN>_21.zip`) → geometria join censimento.
METODO browser che funziona: naviga la pagina → `javascript_exec` estrai gli <a> con
href .csv/.zip → se non ci sono, `read_network_requests` per le XHR → cabla.

### + n_catasto_tn cablato (browser): OPENkat SHP intera provincia (~792 MB)
`export_semestrale_VL_SGC/2039_catasto_shp.zip` → SEMAFORO. Attivo (non scaricato, grande).

**Catalogo: 50/77 scaricabili. Delle 27 KB nuove: 16 attive.**

### Restano ~11 — TAIL DURO (serve tecnica diversa, non solo http_download)
- **WAF/nega navigazione**: ANAC ("Request Rejected"), ISPRA rifiuti (catasto-rifiuti nega).
- **Auth/API complessa**: colonnine PUN (AWS API Gateway + OAuth in config.json, oppure
  feature service ArcGIS su hub-pun-gse.maps.arcgis.com da individuare).
- **SPARQL/RDF (serve adapter `sparql` nuovo)**: cultura_on, cultura_dataset_locali, ArCo
  (endpoint dati.cultura.gov.it/sparql).
- **SPA con export via interazione**: RUNTS, SIOPE, AGCOM, censimento_comuni (MUN).
- **SDMX lento**: turismo (id dataflow da trovare, server lento).
- **on-demand**: catasto_inspire (motore `lib/catasto_inspire.py` pronto).

---

## 🔶 AGGIORNAMENTO 2026-07-31 quinques (SDMX + pendolarismo + motore catasto)

**Niente committato.**

### ISTAT SDMX/BULK — pendolarismo + ASIA attivi
- `n_istat_asia_ul` (istat_sdmx) attivo — ma i 2 dataflow ASIA sono aggregati per
  CLASSE DI AMPIEZZA comune (non per-comune).
- `n_istat_pendolarismo` (http_download) ATTIVO e TESTATO — matrice O-D comune→comune
  per lavoro 2021, dal file BULK `DWL/PERMPOP/MATPEN/matrix_pendoLAVORO_2021.zip`
  (1.57 MB). SCOPERTA: i dataflow "BULK" ISTAT non hanno API `/data`; il file zip
  sta nell'annotazione `ATTACHED_DATA_FILES` della struttura dataflow.
- `n_istat_censimento_comuni` resta todo: gli URL `DWL/PERMPOP/MUN/<flow>` sono SPA
  JS (non file diretti), nome zip reale ignoto; l'API /data è troppo lenta.
- Catalogo "Fonti": 41/77 scaricabili.

### Motore catasto INSPIRE — `lib/catasto_inspire.py` FATTO e provato
- Parser streaming dei `CP:CadastralParcel` dai `_ple.gml` + navigazione degli zip
  ANNIDATI `ITALIA/<REG>.zip → <PROV>.zip → <BELFIORE>_<COMUNE>.zip` (BytesIO,
  senza estrarre 28 GB). Coordinate EPSG:6706 lat/lon → GeoJSON [lon,lat].
  API: `regions_present()`, `iter_parcels(region_zip, belfiore=…)`,
  `parse_parcels(file)`, `list_comuni(region_zip)`.
- PROVA: Allein (VdA, belfiore A205) = 7.649 particelle in 0.5s via zip annidati →
  `out/CATASTO_PARTICELLE/A205_ALLEIN.geojson` (4.4 MB), props: riferimento_catastale,
  foglio, particella, comune_catastale (Belfiore).
- **DA FARE per il semaforo**: (1) crosswalk **ISTAT↔Belfiore** (admin usa ISTAT, il
  catasto usa Belfiore; match per nome comune o tabella ISTAT codici catastali);
  (2) overlay zonizzazione PRG sulle particelle → classificazione edificabilità.
  Il motore NON è un download di pipeline (28 GB): è on-demand per-comune/regione.

---

## 🔶 AGGIORNAMENTO 2026-07-31 quater (Salute/Scuole/ANNCSU + view Fonti per ente)

**Niente committato.**

### (2) Adapter bespoke — FATTI
- **`lib/html_resources.py`** (scrapa una pagina, estrae i link risorsa datati, scarica
  via `http_download.download`). SSL permissivo (SECLEVEL=1) per i gov.it con TLS
  restrittivo (helper `ssl_context` in html_resources e http_download; anche
  `_check_url` in dashboard_server).
- **`n_salute_presidi`** (html_resources, `status: active`) — TESTATO: farmacie
  (58.837 righe) + distributori scaricati. CSV con cod_comune/comune/provincia.
- **`n_miur_scuole`** (html_resources, active) — discover prende l'ultimo CSV
  (SCUANAGRAFESTAT…, a.s. 2026/27).
- **`n_anncsu`** (http_download, active) — getds.php?STRAD_ITA/INDIR_ITA → zip via GET
  (HEAD dà HTML, GET dà octet-stream `stradarioItalia.zip`). Discover OK; i file
  nazionali sono grandi (non scaricati nel test).
- Salute/Scuole **NON sono CKAN** (portali custom) → risolti con html_resources.

### Adapter SDMX ISTAT — FATTO (`lib/istat_sdmx.py`)
- Costruisce l'URL SDMX-CSV (`{base}/data/{IT1,ID,ver}/all?format=csv&startPeriod&endPeriod`)
  da `sdmx_datasets: [{key,title,dataflow_id,version,start,end,key_filter?}]`; download via
  `http_download`. Base: `https://esploradati.istat.it/SDMXWS/rest`. GOTCHA SDMX: HEAD dà 405,
  serve `/all` nel path, il server è LENTO sui dataflow grandi (usa background/timeout lungo).
- `n_istat_asia_ul` ATTIVO e testato (2 CSV, ~200 KB ciascuno). CAVEAT: i 2 dataflow ASIA
  (183_285, 183_1163) sono aggregati per **classe di ampiezza** comune (REF_AREA=INH_*),
  NON per singolo comune → non componibili per-comune.
- TODO SDMX: pendolarismo (dataflow-id da trovare nel databrowser, i tentativi danno 404),
  censimento-comuni (flowRef `IT1,DF_DCSS_*_TV_*,1.0` VALIDI=200 ma download grande/lento →
  l'utente l'ha rimandato), turismo (id da confermare). L'adapter è pronto: basta l'ID+config.

### View "Fonti" ridisegnata: raggruppata per ENTE EDITORE (categorie collassabili)
- Backend `sources_catalog()` ora raggruppa per **publisher** (helper `_publisher`
  da `ente`, prima del trattino lungo; alias per ISTAT/ISPRA/MIT/MEF/MIC/MIUR…;
  `.gov` generici → "OpenData Governo"). 49 categorie invece di 77 voci flat
  (ISTAT 7, ISPRA 3, MEF 3, MIC 3, Agenzia Entrate 3, MIT 2…). Ordine: nazionali
  prima, poi per numero dataset. Nuovi endpoint: `GET /api/sources/check?key=`
  (disponibilità per-fonte), `POST /api/jobs {sources:[...]}` (download di gruppo/tutte
  via `run_sources.py`, `JobManager.start_sources_batch`).
- Frontend `dashboard/app/page.tsx`: tab "Per fonte" e "Fonti" **unificate** in una
  sola "Fonti". Card CATEGORIA collassabile (icona favicon/monogramma dell'ente,
  nome, "N dataset · X scaricabili", "Scarica gruppo", chevron). Espansa → griglia
  dei dataset con Scarica/Riscarica · Verifica (badge disponibilità) · Fonte↗.
  Toolbar: Solo scaricabili · Solo dati nuovi · Aggiorna · Scarica tutte. CSS in
  globals.css (`.catalog-cat*`). Build+tsc puliti. ⚠️ Se l'HMR di vite si impianta
  su un save intermedio, riavvia `npm run dev`.

---

## 🔶 AGGIORNAMENTO 2026-07-31 ter (MIMIT end-to-end nel layer)

**Niente committato. RICETTA fonte nazionale a punti → layer finale (PROVATA su MIMIT).**
`n_mimit_carburanti` (distributori) ora arriva **composto** in PUNTI_INTERESSE su
qualunque regione. Prova: `out/PUNTI_INTERESSE/02.geojson` = 14.814 feature, di cui
**85 distributori MIMIT** su VdA (nome/bandiera/gestore/indirizzo, licenza «Open data
MIMIT», ritagliati sui comuni). Passi replicabili per ogni nuova fonte nazionale a punti:
1. **Adapter** scarica il dato (csv_direct converte i CSV-con-coordinate in GeoJSON
   di punti: `local_path` del manifest → il .geojson; il csv resta in `csv_path`).
2. **`applies_to_all_regions: true`** sulla fonte → entra in `_region_entities` di
   OGNI regione (gancio nazionale in `compose_engine`).
3. **Classe canonica** dedicata in `registry/canonical_taxonomy.yaml` (es.
   DISTRIBUTORI_CARBURANTE) + **regola** in `registry/layer_dictionary.yaml`.
4. **Aggancio al target**: aggiungi la classe alle `sources:` del target in
   `composition_targets.yaml` (es. PUNTI_INTERESSE: [POI_PUNTUALI, DISTRIBUTORI_CARBURANTE]).
5. (Opz.) ramo dedicato in `compose_feature_layer` per name/licenza/attribuzione.
6. Esegui: `run.py recognize --catalog work/catalog/<key>.csv --ente <key>` →
   `run.py compose --targets <TARGET> --scope-level region --scope-key <RR>`.
GOTCHA: i dati nazionali **tabellari** (senza coord: demografia, ASIA, pendolarismo)
richiedono ancora il join tabella→geometria comune ISTAT (builder non ancora fatto).

### (b) Altri adapter di download — stato
- **`lib/http_download.py` FATTO** (scarica file + estrae zip con `unzip` di sistema).
  `n_istat_censimento_sezioni` → `adapter: http_download`, `status: active`, testato:
  Comuni_2023.zip (34 MB, 14 file) + Dati_regionali_2023.zip (261 MB, 21 file)
  scaricati ed estratti, 0 errori. Contenuto = XLSX per-comune → per DEMOGRAFIA serve
  parsing xlsx + join a geometria sezioni (builder tabellare, TODO).
- **Adapter eseguibili ora**: csv_direct, http_download (oltre a quelli esistenti).
  Catalogo "Per fonte": 36/77 scaricabili.
- **SCOPERTA**: Salute (`dati.salute.gov.it`) e Scuole (`dati.istruzione.it`) **NON
  sono CKAN** (portali custom: package_show dà HTML / 404) → non «facili», servono
  adapter bespoke (analisi API/scraping). ANNCSU getds.php è a due passi (HEAD→HTML,
  GET→octet-stream) → da verificare con GET reale. Restano `status: todo`.
- **Prossimi**: (1) builder compose tabellare (xlsx/csv nazionale → join comune ISTAT)
  per far fruttare ISTAT/ASIA/pendolarismo/IRPEF; (2) adapter bespoke Salute/Scuole/ANNCSU.

---

## 🔶 AGGIORNAMENTO 2026-07-31 bis (target + primo adapter facile)

**Niente committato.**

### Copertura attuale
8/20 regioni con fonti dedicate (tutto il Nord: 01 Piemonte, 02 VdA, 03 Lombardia,
04 TN-AA, 05 Veneto, 06 FVG, 07 Liguria, 08 E-R). Le 12 del Centro-Sud hanno solo
fonti nazionali → i 27 dataset KB (nazionali) estendono la copertura a 20/20.

### 5 nuovi target creati (`registry/composition_targets.yaml`, `planned: true`)
BENI_CULTURALI, CONNETTIVITA_DIGITALE, TRASPARENZA_APPALTI, TURISMO_RICETTIVITA,
AMBIENTE_RIFIUTI. **`planned: true`** = destinazione dichiarata ma non ancora
alimentata; NON concorrono alla completezza compose (filtro aggiunto in
`dashboard_server.py`, riga ~880). `feeds_target` delle fonti KB riagganciato:
ArCo+Cultura→BENI_CULTURALI, AGCOM→CONNETTIVITA_DIGITALE, ANAC+SIOPE→TRASPARENZA_APPALTI,
ISTAT turismo→TURISMO_RICETTIVITA, ISPRA rifiuti→AMBIENTE_RIFIUTI. (Toponimi e basi
territoriali restano `null` = infrastruttura/geocoding.)

### Primo adapter "facile" FATTO: `csv_direct` + MIMIT carburanti ATTIVO
- Nuovo `lib/csv_direct.py` (discover+download di file CSV a URL diretto), collegato
  a `stages/stage_01_discover.py` e `stages/stage_02_download.py`, aggiunto al set
  eseguibile in `dashboard_server.py` (`compact_source.formats`).
- `n_mimit_carburanti` → `adapter: csv_direct`, `status: active`, `csv_datasets`
  (anagrafica impianti + prezzi). **Testato dal vivo: 2/2 CSV scaricati** (~3.5+4 MB).
  GOTCHA CSV MIMIT: delimitatore **`|`** (non `;`), riga 1 = "Estrazione del <data>"
  (header alla riga 2 → `skip_rows: 1`), join per `idImpianto`. L'anagrafica ha
  Latitudine/Longitudine+Comune → punti per PUNTI_INTERESSE.

### TODO — prossimi adapter facili (ordine "quelli facili primi")
1. **CKAN** (`n_salute_presidi` farmacie, `n_miur_scuole`): adapter `*_ckan` che
   risolve la risorsa dal dataset CKAN e scarica (pattern simile a ckan_mit).
2. **Zip diretti ISTAT** (`n_istat_censimento_sezioni`): adapter che scarica lo zip
   e lo estrae (attenzione Deflate64 → `unzip` di sistema).
3. **ANNCSU** (`n_anncsu`): getds.php?STRAD_ITA/INDIR_ITA → zip INSPIRE per regione.
4. Manca ancora il pezzo **compose per dati tabellari nazionali**: join CSV/tabella
   → geometria comune ISTAT (nuovo builder o modalità in compose_engine). MIMIT ha
   coord native (più facile: punti diretti); gli altri sono tabellari da joinare.

---

## 🔶 AGGIORNAMENTO 2026-07-31 (sessione Claude)

**Niente committato.**

### KB nazionale: +27 fonti (status: todo) in `registry/sources.yaml`
Catalogate su richiesta utente (NON scaricare). Fonti open data nazionali: ANNCSU
(stradario/civici), toponimi, catasto TN, AGCOM connettività, ArCo/Cultura beni
culturali, ISTAT (censimento sezioni, POSAS, ASIA, pendolarismo, basi territoriali,
turismo), ANAC, MIMIT carburanti, MEF immobili+IRPEF, colonnine ricarica, Salute
(farmacie...), MIUR scuole, SIOPE, ISPRA (suolo/idrogeo/rifiuti), RUNTS, ACI.
Ognuna con `adapter: null` + `proposed_adapter` + notes ricche. Accessibilità
verificata (tutti rispondono) → `Layer_Processor/registry/KB_ACCESS_CHECK.md`.

### Regola catasto (utente)
Tutto il catasto SOLO da Agenzia Entrate (INSPIRE/ANNCSU). Niente downloader
catastali regionali (verificato: non ce n'erano da bloccare; i layer
`planningCadastre` sono PRG/PUG). TN via `n_catasto_tn`; Bolzano vuoto.

### 4° tab dashboard "Per fonte" — download per singola fonte
Backend: `GET /api/sources/catalog` + `JobManager.start_source_stage` +
`POST /api/jobs {stage,source}`. Frontend: nuovo tab in `dashboard/app/page.tsx`
con pulsante "Scarica" per-fonte (solo se `download_available`). Riusa
`run.py <stage> --source <key> --progress`. Build+test OK. **Riavviare la dashboard
per vederlo.**

---

## 🔶 AGGIORNAMENTO 2026-07-30 (sessione Claude)

**Niente committato.** Stato di questa ripresa:

### Bugfix Trentino (region 04) — FATTI
- **2 errori "layer non presente o non interrogabile" (discover ArcGIS `r_tn_pericolosita`)** = falso positivo.
  Causa: il listing radice del MapServer NON riporta il campo `type`, quindi il filtro
  `type == "Feature Layer"` in [lib/arcgis_rest.py](Layer_Processor/lib/arcgis_rest.py) (≈riga 213) svuotava
  `remote_ids` e marcava ogni layer come mancante. I layer 5 (Sintesi finale) e 3 (Ambiti fluviali) sono
  interrogabili (Feature Layer, Map,Query,Data). **Fix:** una foglia è interrogabile se NON è un gruppo
  (`subLayerIds` assente) e `type` è `None` o "Feature Layer". Al prossimo discover i 2 errori spariscono.
- **"205/198 layer scaricati" (impossibile >100%)** = denominatore sottostimato. La fonte-collezione CKAN
  `r_tn_servizi_valli` ha 10 risorse nel catalogo CSV ma il suo `_services.json` non ha `layers`/`services`/
  `downloadable_count` → contribuiva 0 al denominatore ma 9 agli scaricati. **Fix in
  [dashboard_server.py](Layer_Processor/dashboard_server.py):** denominatore = righe del catalogo CSV
  (verità autoritativa), manifest solo come fallback. Ora mostra **205/209** (209 = inventario reale:
  205 scaricati, 3 falliti source-side, +1 layer ArcGIS non ancora tentato per il bug sopra).
  ⚠️ **La dashboard API va riavviata** per servire i nuovi numeri (`python3 start_dashboard.py`).
- **3 fallimenti download reali** (source-side, ritentabili al prossimo refresh): CKAN `valle-dei-laghi`
  HTTP 400, `r_tn_prguso` HTTP 400 (fonte `status: todo`, solo WMS — vedi `richiesta_PRGUSO_PAT.md`),
  BZ `G.A.K. Zonen - Zone P.C.C.A.` timeout.

### Catasto nazionale — AGGIUNTO come fonte (`n_catasto_inspire`, `status: todo`)
- Dataset INSPIRE dell'Agenzia delle Entrate, già scaricato in `Layer_Processor/ITALIA/` (~28 GB, 19 zip
  regionali). Struttura annidata: `REGIONE.zip → PROV.zip → <BELFIORE>_<COMUNE>.zip →
  {_map.gml = fogli/CadastralZoning, _ple.gml = particelle/CadastralParcel}`, EPSG:6706 (lat/lon).
- **Copre 19/20 regioni. MANCA: Trentino-Alto Adige (04)** — le Province Autonome di Trento e Bolzano
  usano il **catasto tavolare** (libro fondiario), non pubblicato nel dataset INSPIRE nazionale; va preso
  dai portali provinciali.
- **Da fare:** adapter `catasto_inspire` che cammina gli zip annidati e materializza/compone per-regione
  (il `local_spatial` esistente vuole file singoli, non zip annidati). Base geometrica del semaforo per-lotto.

### Follow-up FVG — NON eseguiti (documentati, in coda)
1. **PRGC comunali via Eagle-FVG** → la zonizzazione vera (target `PRG_ZONING`). Onboarding per-comune.
2. **PAI idraulico Tagliamento/Isonzo** via Autorità di Bacino Alpi Orientali — fonte separata.

### Regola utente (nuova)
- **Quando l'utente chiede di "rinfrescare i dati", si rinfresca SOLO quella regione**, mai tutte insieme.

---

## Cos'è il Layer_Processor (in 30 secondi)
Pipeline a stadi che scala l'approccio Torino a tutta Italia:
`01 discover → 02 download → 03 recognize → 04 compose` (→ 05 Supabase, futuro).
Obiettivo: da tante fonti regionali eterogenee produrre **layer finali uniformi** (zonizzazione,
vincoli, rischi, mobilità, ecc.) e in ultima analisi un **semaforo di edificabilità** per comune/lotto.
- Fonti: `registry/sources.yaml` (23 fonti). Ogni regione ha un **adapter dedicato** (giusto così:
  tiene conto delle specifiche del territorio).
- Composizione: `lib/compose_engine.py` — ora **generica per tutte le regioni** (vedi sotto).
- Dashboard locale: `dashboard_server.py` + `start_dashboard.py` (avvia con `python3 start_dashboard.py`).

## Cosa è stato fatto nella sessione precedente (sintesi)
1. **Rimosse** le fonti PUMS / OpenCUP / PNRR (deciso con l'utente).
2. **Ricategorizzati** i target: Catasto → dentro ANALISI_URBANISTICA; AINOP + Sosta → dentro RETE_VIABILITA.
3. **Onboarding 3 nuove aree** con dati scaricati in `raw/`:
   - **Piemonte piani**: PPR (131 file) + Mosaicatura PRG storica 8 province + Mosaico PRGC Torino (WFS, 212k feat).
   - **Trentino (PAT)**: PUP (83 layer, 298k) + Carta Pericolosità (ArcGIS, 448k) + Servizi/POI Comunità.
   - **Alto Adige (BZ)**: Piani PUC/Bauleitplan+Paesaggistico+ZonePericolo (698k) + nuovo Piano Comunale + Pericoli/Geologia/Idrologia (188k).
4. **3 nuovi adapter generici**: `lib/wfs_generic.py`, `lib/arcgis_rest.py`, `lib/ckan_collection.py`.
5. **Feature "solo dati nuovi"** a livello feature (confronto conteggio locale vs server) in wfs_generic/arcgis_rest/liguria_geoportal.
6. **Composizione resa generica** (il pezzo grosso, vedi sotto).
7. Pulizia: rimossi `__pycache__`, `.tmp`, `.DS_Store`.

## Stato della COMPOSIZIONE (il cuore del lavoro attuale)
`lib/compose_engine.py` prima componeva solo 3 target e solo VdA/Liguria (hardcoded). **Ora è generica:**
- `_recognition_for_region` unisce il recognize di tutte le entità di una regione (via `sources.yaml`).
- `_resolve_raw` risolve UUID→file grezzo per **qualsiasi adapter** (testato su 6).
- `compose_feature_layer(target, scope)` = builder generico per i 10 target "a feature".
- `compose_target` = dispatcher: builder dedicato (PIANI_MATURITA, VINCOLI_COMUNALI, SEMAFORO) o generico.
- **Provato su VdA: tutti i 13 target compongono.** La dashboard ora li mostra tutti.

---

## ⚠️ COSA DEVI FARE (in ordine di priorità)

### 1) Attivare la composizione su Trentino e Alto Adige — il passo che manca
Il codice di composizione è pronto ma per Trentino/Bolzano **manca il recognize**:
`work/recognition/` contiene p_to, r_lombar*, r_piemon, r_vda, r_veneto — **NON** r_tn_* né r_bz_*.
Passi:
- Fai girare il recognize per ogni nuova fonte, es.:
  `python3 run.py recognize --catalog work/catalog/r_bz_piani.csv --ente r_bz_piani`
  (idem r_tn_pup, r_tn_pericolosita, r_bz_piani_gvcc, r_bz_pericoli, r_bz_geologia, r_bz_idrologia, p_to_prgc_mosaico).
- Guarda quanti layer vengono riconosciuti vs finiscono in `work/proposals/<ente>.json` (non riconosciuti).
- **Molto probabilmente il `registry/layer_dictionary.yaml` NON copre** i nomi tedeschi di Bolzano
  (`Baugebiete`, `Gefahrenzonen`, `Landschaftsplan`, `UrbanPlan-ZoningPlan-*`…) né i codici PUP Trentino
  (`e103_p_pup` = aree agricole, ecc.). Aggiungi le keyword al dizionario mappandole sulle classi canoniche
  giuste (es. Baugebiete/SettlementAreas → `PRG_ZONING`; HazardZonePlan/Wassergefahren → `RISCHIO_IDRAULICO`).
  Attenzione bilinguismo BZ: attributi doppi `BEZ_I`/`BEZ_D`, `NDA_LINK_IT`/`NDA_LINK_DE`.
- Poi `python3 run.py compose --region 04 --target ANALISI_URBANISTICA` (o via dashboard) e verifica l'output
  in `out/<TARGET>/04.geojson`.
- **Coordina con Codex**: sta lavorando su recognize/dizionario/mapping (`by_region`) per Lombardia/Veneto.
  Non rifare il suo lavoro; allinea le keyword nello stesso file.

### 2) Piemonte = ZIP → serve estrazione
I file di `r_piemon` in `raw/regione/r_piemon/` sono **.zip (Shapefile)**. Il builder generico legge solo
GeoJSON, quindi per Piemonte i target generici restano `blocked`. Serve un passo di estrazione
ZIP→GeoJSON (unzip SHP + conversione, es. con `geopandas`/`fiona`) dentro `_resolve_raw` o come step di
normalizzazione. Le regioni WFS/ArcGIS (VdA, Liguria, Trentino, Bolzano, Torino PRGC) sono già GeoJSON.

### 3) Uniformare i runner dashboard (piccolo)
In `dashboard_server.py` `SCOPE_RUNNERS`: ho tolto il cap `compose_targets` da VdA (02). Lombardia (03) e
Veneto (05) hanno ancora `compose_targets` ristretti → ora sono obsoleti (tutti i target compongono).
Toglili per uniformità **solo dopo aver verificato con Codex** (sono le sue regioni).

### 4) Richiesta PRGUSO Trentino (già pronta)
Il PRG comunale del Trentino (PRGUSO/PRGVIN) NON è scaricabile (solo WMS). La bozza di richiesta a PAT è
in `richiesta_PRGUSO_PAT.md` (root) — l'utente deve solo compilarla e inviarla. Non inviarla tu.

---

## Gotcha da NON ri-derivare (fanno perdere ore)
- **Trento webgis**: GeoServer su host intranet `cloud-intra.tn.it` → si passa dal **proxy** del webgis
  (`webgis.provincia.tn.it/wgt/services/ogcproxy/capabilities?url=<WFS-encoded>`). Gestito da `proxy_template`
  in wfs_generic. NON pre-codificare `:`/`/` nei param interni (usa `urlencode(safe=":/,")`), altrimenti HTTP 500.
- **Torino PRGC (MapServer)**: `outputFormat=geojson` (rifiuta `application/json`).
- **ArcGIS Trento**: `f=geojson` è ROTTO oltre ~58k feature → arcgis_rest usa `f=json` + conversione Esri→GeoJSON
  + cursore OBJECTID (non resultOffset).
- **Bolzano**: path OWS diverso per host: `geoservices.buergernetz.bz.it/geoservice1/<ws>/ows` MA
  `geoservices{1,2,3}.civis.bz.it/geoserver/<ws>/ows`. Contesto layer: `mapview.civis.bz.it/maps/api/v1/contexts/PROV-BZ-GEOBROWSER-MAPVIEW`.
- **Gap non colmabili**: Trentino PTC + LEROP Bolzano (documenti strategici, no vettoriale); Maso Chiuso BZ
  (catasto chiuso); PTCP province Piemonte diverse da Torino (non nel catalogo regionale).

## Come verificare velocemente che tutto compili/funzioni
```bash
cd Layer_Processor
python3 -c "import py_compile; [py_compile.compile(f,doraise=True) for f in ['lib/compose_engine.py','lib/wfs_generic.py','lib/arcgis_rest.py','lib/ckan_collection.py']]; print('OK')"
# test composizione generica su VdA (deve dare 13 target, ~10 con output):
python3 -c "import sys;sys.path.insert(0,'.');from lib import compose_engine as ce;import yaml;[print(t, ce.compose_target(t, {'level':'region','key':'02'}).get('status')) for t in yaml.safe_load(open('registry/composition_targets.yaml'))['targets']]"
```

## Regole di lavoro con questo utente
- Parla italiano.
- **Non committare** senza che l'utente lo chieda esplicitamente.
- Ogni download pesante → in background, e riferisci l'esito reale (conteggi feature, errori) — niente ottimismo.
- I downloader restano **per-regione** (l'utente lo vuole: specificità territoriale). L'uniformità sta nella COMPOSIZIONE.
- C'è **Codex che lavora in parallelo** sugli stessi file (Lombardia/Veneto, recognize, mapping): tieni conto
  delle sue modifiche, non revertirle, coordina via il CODEX_HANDOFF.
