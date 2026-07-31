# Handoff Codex — Layer_Processor (scala nazionale dei layer)

Aggiornato al 2026-07-30. Cartella: `/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor`.

---

## ⭐ 5 TARGET NUOVI + ADAPTER csv_direct (2026-07-31 bis, Claude)

**Niente committato.**
- **5 target** in `registry/composition_targets.yaml` con **`planned: true`**:
  BENI_CULTURALI, CONNETTIVITA_DIGITALE, TRASPARENZA_APPALTI, TURISMO_RICETTIVITA,
  AMBIENTE_RIFIUTI. Il flag `planned` li ESCLUDE dalla completezza compose
  (filtro in `dashboard_server.py`: `target_keys` salta gli spec con `planned`).
  Se aggiungi builder/canonical per questi, togli `planned` quando sono pronti.
- **`feeds_target`** delle fonti KB riagganciato ai nuovi target (vedi
  CLAUDE_CONTINUA_QUI). Emilia-Romagna: aggiunto `emilia_romagna_moka` al set
  `formats` di `compact_source` → ora le fonti E-R risultano scaricabili (10/11).
- **Nuovo adapter `lib/csv_direct.py`** (CSV a URL diretto), collegato a
  stage_01/stage_02 e al set eseguibile. `n_mimit_carburanti` è `active` e testato
  (2/2 CSV). Config via `csv_datasets: [{key,title,url,delimiter,skip_rows,geometry,
  lat_field,lon_field,join_field}]`. GOTCHA MIMIT: delimiter `|`, riga 1 = data.
- MANCA il compose per dati tabellari nazionali (join tabella→geometria comune
  ISTAT): builder/modalità nuova in compose_engine. È il prossimo pezzo grosso.

---

## ⭐ KB NAZIONALE + SEZIONE "PER FONTE" (2026-07-31, Claude)

**Niente committato.**

### KB nazionale: +27 fonti in `registry/sources.yaml` (status: todo)
Registrate su richiesta utente (NON scaricare, solo catalogare + verificare
accessibilità). Tutte `livello: nazionale` (tranne `n_catasto_tn` = regione 04),
`adapter: null` + `proposed_adapter: <nome>` (adapter da implementare), `status: todo`.
Chiavi: n_toponimi_italia, n_anncsu, n_catasto_tn, n_agcom_connettivita,
n_arco_beni_culturali, n_cultura_dataset_locali, n_cultura_on,
n_istat_censimento_sezioni, n_istat_basi_territoriali, n_anac_opendata,
n_istat_posas, n_mimit_carburanti, n_istat_asia_ul, n_mef_immobili_pubblici,
n_istat_pendolarismo, n_istat_censimento_comuni, n_colonnine_ricarica, n_mef_irpef,
n_salute_presidi, n_miur_scuole, n_siope, n_ispra_suolo, n_ispra_idrogeo,
n_ispra_rifiuti, n_runts, n_istat_turismo, n_aci_opendata.
Verifica accessibilità (HEAD/range, senza scaricare) in
`registry/KB_ACCESS_CHECK.md`: tutti gli endpoint rispondono; dati diretti reali
per ANNCSU (STRAD/INDIR), ISTAT zip censimento, MIMIT CSV.

### REGOLA CATASTO (utente)
Tutto il catasto si scarica SOLO dall'Agenzia delle Entrate (`n_catasto_inspire` /
ANNCSU). NON creare downloader catastali regionali. I layer regionali
`topic: planningCadastre` sono PRG/PUG (zonizzazione), non particelle → verificato
che NON esistono downloader catastali regionali da bloccare. TN colmato da
`n_catasto_tn` (catastotn.tndigit.it); Bolzano ancora senza fonte. Backup dataset
catasto: dati.gov.it id 9d74351a. `n_catasto_inspire` ora ha `canonical_catasto: true`,
`backup_dataset_url`, `also_published_via`.

### Sezione "Per fonte" (4° tab dashboard) — download per singola fonte
Nuova sezione per scaricare i dati di UNA fonte, indipendente dal territorio.
- **Backend** `dashboard_server.py`:
  - `GET /api/sources/catalog` → `sources_catalog()`: tutte le 77 fonti via
    `compact_source`, raggruppate (Nazionale + regioni), con `download_available`
    per-fonte. Testato: 77 fonti, 24 scaricabili, 9 gruppi.
  - `JobManager.start_source_stage(stage, source_key, only_new, batch_size)`:
    lancia `run.py <stage> --source <key> --progress` per una singola fonte;
    solleva se la fonte non ha adapter attivo (status todo). Riusa `_run_command`
    (PROGRESS/RESULT_JSON già gestiti).
  - `POST /api/jobs` con campo `source` → instrada a `start_source_stage`.
- **Frontend** `dashboard/app/page.tsx`: 4° tab "Per fonte" (`tab==="catalog"`),
  fetch `/api/sources/catalog`, griglia per gruppo con pulsante "Scarica" per-fonte
  (abilitato solo se `download_available`), altrimenti "Adapter da implementare".
  Build OK, tsc pulito su page.tsx, test SSR verdi.
- NOTA (pre-esistente, non introdotta): `compact_source.download_available` usa un
  set `formats` hardcoded che NON include `emilia_romagna_moka` né `vda_prg_*` →
  quelle fonti risultano "non scaricabili" anche nel tab Fonti. Da valutare se
  aggiungerle al set (dominio Codex per E-R).

⚠️ Riavviare la dashboard (API + `npm run dev`) per vedere la nuova sezione.

---

## ⭐ BUGFIX TRENTINO + CATASTO NAZIONALE (2026-07-30, Claude)

**Niente committato.**

### Bugfix 1 — discover ArcGIS: falsi "layer non presente o non interrogabile"
`lib/arcgis_rest.py` `discover()` costruiva `remote_ids` filtrando i layer del
listing radice del MapServer per `layer.get("type") == "Feature Layer"`. Ma il
JSON radice del MapServer **non espone `type`** (compare solo su `/MapServer/<id>?f=json`):
`remote_ids` risultava vuoto e ogni layer configurato veniva marcato mancante.
Colpiva `r_tn_pericolosita` (2 errori: layer id 5 "Sintesi finale" e id 3 "Ambiti
fluviali idraulici", entrambi interrogabili — Feature Layer, Map,Query,Data).
**Fix:** una foglia interrogabile = `id` presente, `type in (None, "Feature Layer")`
e `not subLayerIds` (i gruppi hanno `subLayerIds`). Esclude i gruppi, include le
foglie anche quando `type` è assente. Ricompila OK.

### Bugfix 2 — dashboard: "205/198 layer scaricati" (>100%, impossibile)
Il denominatore in `dashboard_server.py` (dettaglio pipeline discover e download)
usava la catena `downloadable_count OR len(services) OR len(layers)`. La fonte
CKAN `r_tn_servizi_valli` ha 10 risorse nel catalogo CSV ma il suo `_services.json`
ha solo `resources` (niente `layers`/`services`/`downloadable_count`) → contribuiva
**0** al denominatore ma **9** al numeratore (`layers_downloaded`). Sommato sulle
due pipeline TN-AA dava 205/198. **Fix:** in entrambi i punti il denominatore ora
è `_csv_row_count(catalog)` (il catalogo CSV è la verità autoritativa: una riga per
item scaricabile, incluse le risorse CKAN), con i conteggi manifest come solo
fallback. Nuovo esito: **205/209** (r_tn_pup 93/96, r_bz_piani 112/113). ⚠️ Riavviare
la dashboard API per servire i nuovi numeri.
3 fallimenti download **reali** (source-side, ritentabili): CKAN `valle-dei-laghi`
HTTP 400, `r_tn_prguso` HTTP 400 (fonte `status: todo`, solo WMS), BZ
`G.A.K. Zonen - Zone P.C.C.A.` timeout.

### Fonte nuova — `n_catasto_inspire` (nazionale, `status: todo`)
Aggiunta a `registry/sources.yaml` (blocco fonti nazionali, prima del blocco FVG).
Cartografia catastale INSPIRE dell'Agenzia delle Entrate, **già scaricata** in
`Layer_Processor/ITALIA/` (~28 GB, 19 zip regionali). Struttura annidata:
`REGIONE.zip → PROV.zip (sigla) → <BELFIORE>_<COMUNE>.zip →
{_map.gml = CP:CadastralZoning (fogli), _ple.gml = CP:CadastralParcel (particelle)}`,
CRS EPSG:6706 (RDN2008 geografico, ordine lat/lon).
- **Copertura: 19/20 regioni. Manca il Trentino-Alto Adige (04)** — catasto tavolare
  (libro fondiario) gestito dalle Province Autonome di Trento/Bolzano, fuori dal
  dataset INSPIRE nazionale; da acquisire dai portali provinciali.
- **TODO adapter `catasto_inspire`**: cammina gli zip annidati e materializza/compone
  per-regione particelle e fogli. `lib/local_spatial.py` NON basta (vuole file singoli
  in `local_datasets`, non zip annidati). È la base geometrica del semaforo per-lotto.

### Follow-up FVG — NON eseguiti (in coda, documentati su richiesta utente)
1. **PRGC comunali via Eagle-FVG** → zonizzazione vera (`PRG_ZONING`), onboarding per-comune.
2. **PAI idraulico Tagliamento/Isonzo** via Autorità di Bacino Alpi Orientali (fonte separata).

### Regola utente (nuova)
Quando l'utente chiede di **"rinfrescare i dati"**, rinfrescare **solo quella regione**.

---

## ⭐ HOTOSM POI + JOB DASHBOARD (2026-07-30)

Fonte nazionale `n_hotosm_poi` integrata tramite `lib/local_spatial.py`:
1.048.796 punti GeoJSON e 726.749 poligoni Shapefile, collegati via symlink,
riconoscimento 2/2. I poligoni alimentano `ANALISI_URBANISTICA` come uso
osservato non prescrittivo; i punti alimentano il nuovo target
`PUNTI_INTERESSE`. Verifica Bologna: 3.842 poligoni HOTOSM e 8.904 punti;
Emilia-Romagna: 74.535 punti. Licenza/attribuzione ODbL conservate.

Dashboard aggiornata: job globale sempre visibile con percentuale e
`Vai al processo`; le risposte 409 per job già attivo includono `active_job`;
gli errori dei manifest sono apribili con `Spiega errori`. Verifica Liguria:
quattro errori mostrati con i messaggi reali. Test Python correnti: 19.

---

## ⭐ AGGIORNAMENTO EMILIA-ROMAGNA (2026-07-30) — leggere PRIMA

Onboarding regionale completato in locale e non committato. Lo scope dashboard
`08` orchestra PUG, PSC e otto mosaici provinciali/metropolitani delle tutele.
L'adapter `lib/emilia_romagna_moka.py` inizializza la sessione del viewer
ufficiale e instrada ArcGIS REST attraverso il proxy Moka pubblico.

Verifica live:

- 17 layer PUG, 9 layer PSC e 184 layer PTCP/PTM: **210 layer** complessivi;
- download reale riuscito su un layer PUG (84 feature) e uno PTCP Modena
  (253 feature);
- riconoscimento: PUG 14/17, PSC 9/9, tutele provinciali 177/184;
- i sette layer provinciali residui hanno titoli formati soltanto da numeri di
  articolo e restano intenzionalmente in revisione;
- i tre layer PUG non assegnati sono la griglia strutturale: devono essere
  classificati per feature usando `TIPO_ESTR`;
- Rimini è registrato `todo` ed escluso dallo scope perché il MapServer Moka
  ufficiale restituisce HTTP 500.

Il profilo `08` documenta la doppia vigenza PUG/PSC-POC-RUE, la quota massima
del 3% come limite comunale (non diritto edificatorio del lotto), e la
permanenza delle componenti paesaggistiche PTCP durante la transizione a
PTAV/PTM. Aggiunti due test dell'adapter; suite completa: **15 test passati**.

---

## ⭐ HOTFIX DOWNLOAD VDA (2026-07-29, 17:41) — leggere PRIMA

Corretto il job `Download · Valle d'Aosta` che terminava con 5 errori
`ArcGIS 400 Invalid or missing input parameters`.

Cause distinte:

1. il catalogo trattava 87 `Raster Layer` (immagini SuperDove, SkySat e ortofoto
   `.tif`) come se fossero interrogabili con `/query?f=geojson`;
2. i batch da 1.000 objectId generavano URL troppo lunghi per il proxy INVA sui
   layer vettoriali grandi.

`lib/vda_platform.py` ora conserva tutti gli **856 layer** nell'inventario, ma
distingue **769 layer vettoriali scaricabili** e **87 riferimenti raster
metadata-only**. I raster restano visibili e tracciati con URL/metadati, senza
essere conteggiati come download GeoJSON falliti. La paginazione vettoriale è
stata ridotta a 500 feature.

Verifica reale successiva: 5/5 layer `Ambiti` completati senza errori
(`Boschi`, `Laghi e zone umide`, `Frane`, `Inondazioni`, `Valanghe`), per oltre
430 MB e 21.952 feature complessive. Il contatore corretto dopo la verifica è
**592/769 vettoriali disponibili, 0 errori**. La run fallita resta nello storico
come traccia diagnostica; la ripresa avviata dalla dashboard prosegue soltanto
dai pendenti.

Test aggiunto: `tests/test_vda_platform.py`. Totale corrente: **13 test Python
passati**.

---

## ⭐ AGGIORNAMENTO VENETO (2026-07-29) — leggere PRIMA

Onboarding Veneto realizzato **in locale, non committato**. La dashboard e
`python3 run.py sync --region 05` usano ora un adapter eseguibile che parte dai
WebGIS ufficiali e non da un inventario fisso.

### Stato verificato

| fonte | adapter | contenuto | discovery |
|---|---|---|---:|
| `r_veneto` | `veneto_webgis` | pianificazione comunale + PTRC 2020 | **269 layer WFS unici / 2 WebGIS** |
| `p_vr`, `p_vi`, `p_bl`, `p_tv`, `p_ve`, `p_pd`, `p_ro` | da configurare | PTCP e portali provinciali/metropolitani | fonti documentate, download non ancora attivo |

L'adapter `lib/veneto_webgis.py` legge le configurazioni live dei WebGIS 213
(pianificazione comunale) e 191 (PTRC 2020), le incrocia con il `GetCapabilities`
del WFS regionale e deduplica i layer presenti in più tavole. La verifica reale ha
restituito:

- 4 layer comunali: confini correnti, Province, perimetri AUC L.R. 14/2017 e
  zonizzazione del Piano Regolatore Comunale;
- 266 layer PTRC unici;
- 269 layer totali, perché un confine amministrativo appartiene a entrambi gli
  insiemi.

### Download reale e ripresa

Sono stati scaricati **2/269 layer**:

- confine comunale: 559 feature, circa 15,3 MB;
- AUC: 507 feature, circa 130 MB.

Restano 267 pendenti. Il WFS è paginato a 500 feature; la dashboard limita ogni run
a 10 layer, scrive atomicamente gli artefatti e al riavvio salta quelli conclusi.
Il manifest conserva topic, gruppo del viewer e provenienza.

Il download dei confini genera automaticamente:

`../Geography_Locations/outputs/admin_municipalities_veneto_current.geojson`

L'overlay contiene **559 Comuni correnti** e sostituisce soltanto il Veneto nella
dashboard/composizione, senza riscrivere il registro amministrativo nazionale
storico.

### Contesto territoriale da preservare

- Il livello comunale è articolato in PAT/PATI (strategico) e PI (operativo e
  conformativo); AUC e PAT non bastano da soli per concludere che un'area sia
  edificabile.
- Il PTRC 2020 è vigente, ma la pagina ufficiale precisa che **non ha valenza di
  piano paesaggistico** ai sensi del D.Lgs. 42/2004; il PPR è ancora in formazione.
- La Regione elenca sette PTCP approvati. Per Venezia il riferimento efficace
  censito resta il PTCP; lo strumento metropolitano futuro è denominato **PTGM**.
- Fragilità, vincoli paesaggistici e consumo di suolo sono overlay obbligatori
  prima di produrre un Semaforo di edificabilità.

Queste regole sono in `registry/regional_planning_profiles.yaml`. Le voci Veneto in
`registry/layer_dictionary.yaml` riconoscono AUC, zonizzazione PRC, fragilità
geologica, sistema rurale e stato del piano.

### Dashboard, riconoscimento e test

- Scoperta: completata, **269/269**.
- Download: parziale, **2/269**.
- Riconoscimento: completato, **30 riconosciuti e 239 proposte (11,2%)**; non
  auto-classificare i temi PTRC specialistici senza regole certe.
- Copertura regionale: **40%**, perché Scoperta e Riconoscimento sono completi.
- La pagina `Fonti` mostra `r_veneto` come fonte diretta attiva e le sette fonti
  provinciali come `Da configurare`, con piano e link ufficiali.
- **12 test Python passati** e build dashboard passata.

### File da preservare

- `lib/veneto_webgis.py`: discovery live, deduplica e generazione overlay comunale.
- `lib/wfs_generic.py`: metadati per layer, batch configurabile e manifest coerente
  anche quando si scarica un solo servizio.
- `stages/stage_01_discover.py`, `stages/stage_02_download.py`: dispatch adapter.
- `registry/sources.yaml`: fonte regionale eseguibile + sette fonti provinciali.
- `registry/regional_planning_profiles.yaml`, `registry/layer_dictionary.yaml`.
- `run.py`, `dashboard_server.py`, `lib/compose_engine.py`.
- `tests/test_veneto_webgis.py`.

### Comandi di ripresa

```bash
cd "/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor"
python3 run.py discover --source r_veneto --progress
python3 run.py download --source r_veneto --max-services 10 --progress
python3 run.py sync --region 05 --max-services 10 --progress
python3 run.py context --region 05 --json
```

### Prossimi passi

1. Completare i 267 download con batch successivi e sorvegliare dimensione/tempo
   della zonizzazione comunale.
2. Inventariare e attivare endpoint vettoriali stabili per i sette PTCP.
3. Implementare la composizione Veneto usando PI/zonizzazione come base
   conformativa, AUC/PAT come contesto e PTRC/fragilità/vincoli come overlay.
4. Non eseguire il caricamento: `stage_05_load.py` resta uno stub e richiede
   approvazione esplicita.

---

## ⭐ AGGIORNAMENTO LOMBARDIA (2026-07-29) — leggere PRIMA

Onboarding Lombardia realizzato **in locale, non committato**. Il pulsante regionale e
`python3 run.py sync --region 03` partono da zero e processano insieme tre fonti ufficiali:
ArcGIS regionale, inventario PGTWEB/Socrata e PTM della Città metropolitana di Milano.

### Stato verificato

| fonte | adapter | contenuto | discovery |
|---|---|---|---:|
| `r_lombar` | `arcgis_rest` | Mosaico PGT, stato PGT, PPR, geologia, confini, PTR/PT7, PTCP | 138 layer / 7 servizi |
| `r_lombar_pgtweb` | `socrata` | inventario amministrativo PGTWEB | 1 dataset / 38.851 record |
| `r_lombar_ptm` | `websit_xml` | PTM vigente Milano, shapefile ZIP | 157 pacchetti unici / 1 catalogo |
| **Totale dashboard Lombardia** | | | **296 dataset / 9 servizi** |

Dettaglio dei 138 layer ArcGIS:

| servizio | layer |
|---|---:|
| Mosaico PGT — Tavola delle Previsioni | 32 |
| Stato di approvazione PGT + scheda PGTWEB | 2 |
| Piano Paesaggistico Regionale | 29 |
| Fattibilità geologica | 1 |
| Comuni correnti | 1 |
| Quadro PTR/PT7 (`ptr_tav2`, nome tecnico storico) | 33 |
| Mosaico PTCP, sola rappresentazione di dettaglio ID 83–122 | 40 |

Il catalogo XML del PTM contiene 284 righe perché lo stesso dato è richiamato da più tavole.
`lib/websit_xml.py` le deduplica in **157 ZIP unici**, conservando tavole, categorie, data,
metadati e WMS. Download atomico e ripresa sono verificati con
`tx_PTM_Zone_Omogenee.zip` (273.941 byte, archivio integro).

Download locali al momento: **8/296** senza errori:

- 6 layer ArcGIS, inclusi confini correnti, stato PGT, PPR, un layer PTR e un layer PTCP;
- inventario Socrata completo, **38.851 record**, 52,8 MB;
- 1 pacchetto PTM.

Il batch dashboard è 2 per fonte. Le run successive saltano gli artefatti conclusi e
ripartono dai pendenti.

### Confini comunali correnti e compatibilità

`tools/update_lombardia_admin.py` genera un overlay separato:

`../Geography_Locations/outputs/admin_municipalities_lombardia_current.geojson`

Contiene esattamente **1.501 comuni**, geometrie valide. Non riscrive il registro nazionale
storico: dashboard e composizione sostituiscono soltanto la Regione 03 in memoria. Sono presenti
i codici correnti `012144` e `013256`; sono esclusi `013199`, `013228`, `018002`, `018082`.

### Composizione PGT realmente attiva

`PIANI_MATURITA` è abilitato per Lombardia. `lib/compose_engine.py`:

1. legge le 38.851 righe Socrata;
2. deduplica le sezioni del procedimento in 6.332 piani;
3. distingue piano vigente e procedimento successivo in corso;
4. assegna lo stato amministrativo e lo stato della cartografia;
5. unisce i risultati ai 1.501 comuni correnti.

Output: `out/PIANI_MATURITA/03.geojson`, **1.501 geometrie tutte valide**.

| stato | comuni |
|---|---:|
| Testo definitivo approvato | 879 |
| Approvato, cartografia in consegna/caricamento | 593 |
| Definitivo in valutazione | 7 |
| Bozza in valutazione | 2 |
| Iter non avviato | 12 |
| Non determinato | 8 |

Il manifest è correttamente `partial`: 1.493/1.501 comuni hanno un piano corrente o una
procedura attiva determinabile; gli 8 mancanti non vengono riempiti con assunzioni.

### Dashboard e riconoscimento

- Scoperta: completata, **296/296 censiti**.
- Download: parziale, **8/296**.
- Riconoscimento: completato su **296/296**; 189 riconosciuti e 107 in revisione
  (**63,9%**). I 58 PTM non riconosciuti sono soprattutto layer `Mission`/grafici poco
  descrittivi e restano proposte, non auto-merge.
- Composizione: `PIANI_MATURITA` presente ma con copertura parziale.
- Caricamento: non disponibile, richiede approvazione e implementazione dello stadio 05.
- Copertura nazionale: **40%**, perché solo Scoperta e Riconoscimento sono completi.

### Modifiche tecniche da preservare

- `lib/arcgis_rest.py`: collezioni multi-MapServer, filtro `layer_id_range`, OID cursor,
  geometrie Esri, manifest cumulativo e ripresa.
- `lib/socrata.py`: firma remota `{count,max_update}`, paging e skip incrementale.
- `lib/websit_xml.py`: parsing XML, topic editoriali, deduplica ZIP e download atomico.
- `tools/run_sources.py` / `tools/run_recognize_sources.py`: pipeline multi-fonte dashboard.
- `tools/update_lombardia_admin.py`: overlay comunale non distruttivo.
- `dashboard_server.py`: scope Lombardia con tre fonti e composizione limitata a
  `PIANI_MATURITA`.
- La pagina `Fonti` espone per ogni fonte formato, dataset previsti/scaricati,
  batch, cartella locale, ripresa e i due comandi equivalenti; il pulsante
  `Vai a Processi` porta all'esecuzione senza dover aprire gli script `.py`.
- `tests/test_arcgis_rest.py`, `tests/test_socrata.py`, `tests/test_websit_xml.py`:
  **10 test passati**; dashboard `npm run build` passata.

### Limiti da non nascondere

1. Restano **288 download**: l'inventario è completo, i dati grezzi no.
2. Il mosaico PTCP regionale è una base armonizzata; non sostituisce la verifica dell'atto
   vigente e delle varianti di ogni Provincia. Il PTM specifico è configurato soltanto per Milano.
3. Il servizio REST `ptr_tav2` espone i temi del quadro di salvaguardia/PT7, ma conserva un
   nome tecnico storico: la vigenza normativa va riferita agli atti PTR, non dedotta dal nome REST.
4. Non sono ancora implementati in Lombardia `VINCOLI_COMUNALI`,
   `SEMAFORO_EDIFICABILITA` e gli altri layer finali per investitori.
5. PGTWEB documenta procedimenti e caricamento, ma il recupero massivo dei singoli PDF/NTA
   non è ancora incluso.
6. `stage_05_load.py` resta uno stub e non pubblica nulla su Supabase.

### Comandi di ripresa

```bash
cd "/Users/emilianotrombetta/Documents/espansione del dominio/Layer_Processor"
python3 run.py sync --region 03 --max-services 2 --progress
python3 tools/run_recognize_sources.py \
  --sources r_lombar,r_lombar_pgtweb,r_lombar_ptm
python3 run.py compose --targets PIANI_MATURITA \
  --scope-level region --scope-key 03 --scope-name Lombardia --progress
```

---

## ⭐ AGGIORNAMENTO SESSIONE (2026-07-29) — leggere PRIMA

Lavoro fatto tutto **in locale, NON committato**. Focus: pulizia fonti, ricategorizzazione target,
e onboarding di **3 nuove regioni/province autonome** (Piemonte piani, Trentino, Alto Adige/Bolzano)
con **3 nuovi adapter generici** + una nuova feature di download incrementale.

### A) Rimozione PUMS / OpenCUP / PNRR (deciso con l'utente)
Rimossi da `registry/sources.yaml`: `p_to_pums`, `n_opencup`, `n_pnrr`, `n_pums`. Rimossa la riga uMap
PUMS da `registry/piemonte_reference_catalog.csv` (p_to: `expected_dataset_count` 184→183, note aggiornate).
I **concetti canonici** macro-4 (`INVESTIMENTI_OPENCUP`, `PUMS_PROGRAMMATO`, `INTERVENTI`) e le regole in
`layer_dictionary.yaml` sono stati **lasciati dormienti** (non alimentati) — l'utente NON ha chiesto di
toglierli dalla tassonomia. Se serve pulire, chiedere prima.

### B) Ricategorizzazione target (deciso con l'utente)  ⟶ `composition_targets.yaml`, `composition_mapping.yaml`
- **CATASTO** non è più un layer finale a sé → assorbito in **ANALISI_URBANISTICA** (`sources` +
  `canonical_classes` + classe accendibile `fogli_catastali`).
- **INFRASTRUTTURE_AINOP** e **SOSTA_ACCESSI** → assorbiti in **RETE_VIABILITA** (geometry `mixed`,
  classi `sosta_accessi`/`infrastrutture_ainop`, `national_feeds: [n_ainop_opere]`).
- `n_ainop_opere.feeds_target` aggiornato a `RETE_VIABILITA`. Layer finali: 15→12 nel mapping.

### C) 3 NUOVI ADAPTER generici (riutilizzabili per altre regioni)  ⟶ agganciati in `stage_01`/`stage_02`
1. **`lib/wfs_generic.py`** — WFS singola-endpoint, multi-featureType. Legge `type_names` da config o
   auto da GetCapabilities. Download GeoJSON paginato (`startIndex`/`count`). Supporta `proxy_template`
   (`"...ogcproxy?...url={url}"`) per host intranet dietro proxy. `livello` in manifest → cartella corretta.
2. **`lib/arcgis_rest.py`** — ArcGIS REST Map/FeatureServer. Paginazione a **cursore OBJECTID**
   (`OID>{last}` orderBy) — NON `resultOffset` (inaffidabile). Usa **`f=json` + conversione Esri→GeoJSON**
   interna (`_esri_to_geojson_geometry`, gestisce rings/holes) perché alcuni server hanno `f=geojson` rotto.
   `_get_json` con 6 retry + backoff (le pagine con geometrie piene vanno in timeout).
3. **`lib/ckan_collection.py`** — raccoglie i GeoJSON di PIÙ dataset CKAN per `organizations` +
   `title_patterns` (a differenza di `ckan_mit` che fa un solo `ckan_dataset`).

### D) Feature "SOLO DATI NUOVI" a livello feature (deciso con l'utente)  ⟶ `wfs_generic`, `arcgis_rest`, `liguria_geoportal`
In modalità non-refresh il download **non salta più per semplice presenza del file**: confronta il
**conteggio feature locale** (dal `_manifest.json` della run precedente, fallback: parsing GeoJSON) con
il **conteggio server** (WFS `resultType=hits` / ArcGIS `returnCountOnly`). Se diverso (o file mancante)
→ riscarica l'intero layer; se uguale → salta. Motivo: alcuni layer si aggiornano più spesso.
Validato: dry-run Bolzano ha saltato 52/58 e ripreso i 6 cambiati (Δ=1-2 feature). Helper condivisi
duplicati nei tre file: `_previous_feature_counts`, `_feature_count_local`. **NB:** riscarica il layer
intero, non il delta (così gestisce anche update/cancellazioni).

### E) Nuove FONTI in `sources.yaml` (10) + dati scaricati in `raw/`
| key | adapter | contenuto | esito |
|---|---|---|---|
| `p_to_prgc_mosaico` | wfs_generic | Mosaico PRGC attuale Città Metrop. Torino (26 classi semantiche, WFS opengis.csi.it) | ✅ 212.769 feature |
| `r_tn_pup` | wfs_generic (proxy) | Trentino PUP, 83 feature type `pub_pup` via proxy webgis | ✅ 297.986 feature |
| `r_tn_prguso` | wfs_generic | Trentino Uso Suolo Pianificato (PRG comuni) | ❌ `status: todo` — no WFS (solo WMS), richiesta a PAT pronta |
| `r_tn_pericolosita` | arcgis_rest | Trentino Carta Sintesi Pericolosità (ArcGIS) | ✅ 448.500 feature (fix f=json + cursore OID) |
| `r_tn_servizi_valli` | ckan_collection | Servizi+POI Comunità di Valle (civico) | ✅ 9/10, 742 feature |
| `r_bz_piani` | wfs_generic | Bolzano PUC/Bauleitplan+Paesaggistico+Zone Pericolo (`p_bz-TerritorialPlans`, 58 ft) | ✅ 698.723 feature |
| `r_bz_piani_gvcc` | wfs_generic | Bolzano nuovo Piano Comunale + attuativi (`gvcc-TerritorialPlans`, 11 ft) | ✅ ~9.6k feature |
| `r_bz_pericoli` | wfs_generic | Bolzano IFFI frane/valanghe (`pczs-Hazards`, 16 ft) | ✅ 110.284 feature |
| `r_bz_geologia` | wfs_generic | Bolzano geologia (`p_bz-Geology`, 10 ft) | ✅ 53.222 feature |
| `r_bz_idrologia` | wfs_generic | Bolzano idrologia/corsi d'acqua (`p_bz-Hydrology`, 18 ft) | ✅ 24.621 feature |

Per il **Piemonte** l'inventario `piemonte_reference_catalog.csv` conteneva già PPR (132 file, scaricati:
`--service "ppr -"`) e la **Mosaicatura PRG storica** per 8 province (`--service "mosaicatura prg"`, scaricata).

### F) GOTCHA tecnici scoperti (fanno risparmiare ore)
- **Trento webgis** (`webgis.provincia.tn.it/wgt`) è mf-geoadmin; GeoServer su host **intranet**
  `geoservices.cloud-intra.tn.it` NON raggiungibile diretto → si passa dal **proxy** del webgis:
  `https://webgis.provincia.tn.it/wgt/services/ogcproxy/capabilities?url=<WFS-encoded>`. Gestito da `proxy_template`.
- **Double-encoding**: passando dal proxy, NON pre-codificare `:`/`/` nei param interni → usare
  `urlencode(params, safe=":/,")` (altrimenti il GeoServer PAT fa HTTP 500). Già fatto in `wfs_generic`.
- **Torino PRGC WFS (MapServer CSI)**: rifiuta `application/json`, vuole `outputFormat=geojson`.
- **ArcGIS Trento pericolosità**: `f=geojson` ritorna VUOTO oltre ~58k feature (bug server) e
  `resultOffset` si blocca ~58k → cursore OBJECTID + `f=json` + conversione. `returnCountOnly` diceva
  448.991 ma il geojson ne dava solo 58k: ecco perché.
- **Bolzano path OWS incoerente tra host**: `geoservices.buergernetz.bz.it/geoservice1/<ws>/ows` MA
  `geoservices{1,2,3}.civis.bz.it/geoserver/<ws>/ows` (path `/geoservice1/` vs `/geoserver/`). Prendere
  l'URL esatto dal contesto `mapview.civis.bz.it/maps/api/v1/contexts/PROV-BZ-GEOBROWSER-MAPVIEW`.
- **Bolzano attributi bilingui**: `BEZ_I`/`BEZ_D` (destinazione IT/DE), `ISTAT_CODE` per comune,
  `NDA_LINK_IT`/`NDA_LINK_DE` (norme attuazione). Il recognize/compose per BZ dovrà gestire i doppioni IT/DE.

### G) Cosa MANCA (gap confermati, non scaricabili)
- **Trentino PRGUSO/PRGVIN** (zonizzazione PRG 166 comuni): solo WMS, richiesta a PAT pronta in
  `richiesta_PRGUSO_PAT.md` (root progetto). Provinciale (PUP) c'è; comunale no finché PAT non risponde.
- **Trentino PTC** (Comunità di Valle): non su open data (le Comunità pubblicano solo POI/servizi civici).
- **Alto Adige LEROP** (Piano Sviluppo Provinciale): documento strategico, no vettoriale.
- **Alto Adige Maso Chiuso** (Geschlossener Hof): nel catasto `nuop.catastobz.it`, non open data.
- **Piemonte PTCP altre province** (CN/NO/AT/AL/VC/VCO): non nel catalogo regionale (solo Torino PTC2 + Biella PTPv).

### Copertura piani per regione (stato)
- **Piemonte**: provinciale+comunale OK (PPR + mosaicatura PRG). PTCP altre province mancano.
- **Trentino**: provinciale OK (PUP+pericolosità); comunale (PRG) manca → richiesta PAT.
- **Alto Adige**: provinciale+comunale COMPLETO (PUC/Bauleitplan+nuovo Piano+paesaggistico+pericoli). Solo LEROP/Maso fuori.

### H) COMPOSIZIONE UNIFORME per tutte le regioni  ⟶ `lib/compose_engine.py`, `dashboard_server.py`
Prima la composizione aveva builder solo per 3 target (PIANI_MATURITA, VINCOLI_COMUNALI,
SEMAFORO) e funzionava solo per VdA/Liguria (hardcoded). Ora è **generica e region-agnostic**:
- **`_recognition_for_region(region)`**: non più hardcoded `02/07` → legge `sources.yaml` e unisce
  il recognize di **tutte le entità** della regione (`_region_entities` via `region_istat`). Ogni item
  porta `ente`.
- **`_resolve_raw(item)`**: UUID→file grezzo **indipendente dall'adapter** (prima solo r_vda/r_liguria).
  Strategie in ordine: convenzioni VdA/Liguria → match `uuid` nel `_manifest.json` (piemonte_catalog) →
  ricostruzione nome file `_file_slug(type_name)` (wfs_generic) / glob `L{id}_*` (arcgis) → match CKAN per
  dataset. **Testato OK** su 6 adapter (Bolzano/Trento/Torino WFS, ArcGIS, piemonte_catalog, ckan).
- **`compose_feature_layer(target, scope)`** (NUOVO): builder GENERICO per i 10 target "a feature".
  Raccoglie le feature riconosciute con `canonical_key ∈ target.sources`, le assegna al primo comune
  intersecante (STRtree, geometria originale, no duplicati), emette 1 GeoJSON con provenienza per feature
  (`class`, `source_uuid/title/url/ente`, `attributes`). `_write_target` invariato (manifest + fingerprint).
- **`compose_target`**: dispatcher → builder dedicato se esiste, altrimenti generico. **Tutti i 13 target
  compongono.** Testato su VdA: 10 producono output (Analisi 680, Tutele 22k, Rischi 18k, Mobilità 1.7k,
  Rete 1.6k, Servizi 2.4k, OMI 1, + i 3 speciali), 3 `blocked` corretti (VdA non ha Commercio/Demografia/Energia).
- **`dashboard_server.py`**: rimosso il cap `compose_targets` dal runner VdA (obsoleto). **NB per Codex:**
  i runner Lombardia (03)/Veneto (05) hanno ancora `compose_targets` ristretti — ora sono obsoleti,
  rimuoverli per uniformità (o lasciarli, sono tuoi).

**DIPENDENZA per attivare le nuove regioni**: il compose funziona solo se il **recognize** ha girato e il
`layer_dictionary.yaml` copre le keyword delle nuove regioni. Oggi `work/recognition/` ha p_to, r_lombar*,
r_piemon, r_vda, r_veneto — **mancano r_tn_* e r_bz_*** (Trentino/Bolzano: serve far girare recognize +
aggiungere keyword tedesche BZ e codici PUP TN al dizionario). Il codice di composizione è pronto.

**LIMITE Piemonte (ZIP)**: `_resolve_raw` trova i file r_piemon ma sono **.zip (SHP)**, e il builder generico
legge solo GeoJSON → per Piemonte i target generici restano `blocked` finché non si aggiunge
estrazione ZIP→GeoJSON (unzip SHP + conversione) in `_resolve_raw` o in un passo di normalizzazione.
Le regioni WFS/ArcGIS (VdA, Liguria, Trentino, Bolzano, Torino PRGC) sono GeoJSON diretto e funzionano.

Pulizia fatta: rimossi `__pycache__`, `.tmp` di download interrotti, `.DS_Store`.

### Prossimi passi suggeriti per Codex
1. Far girare `recognize`/`compose` sulle nuove regioni: il **dizionario** (`layer_dictionary.yaml`) e il
   `composition_mapping.yaml` non hanno ancora le mappature `by_region` per Trentino (`pub_pup:*`,
   `CP_sintesi_finale`) e Alto Adige (`UrbanPlan-ZoningPlan-*`, `HazardZonePlan-*`, `LandscapePlan-*`).
2. Attributi bilingui BZ (`BEZ_I`/`BEZ_D`) e destinazione d'uso TN (PUP `descr`/`classid`) → normalizzare
   in classi ANALISI_URBANISTICA.
3. Alla risposta PAT su PRGUSO/PRGVIN: aggiungere fonte (probabilmente file locale SHP → nuovo mini-adapter
   o `piemonte_catalog`-like).

---

## AGGIORNAMENTO SESSIONE (2026-07-27, sera)

Modifiche importanti fatte in questa sessione (tutte **in locale, NON committate**). Riguardano
Valle d'Aosta (download reale dalla piattaforma), il Download (batch/ripresa) e la Composizione
(selezione + stato). La restante struttura (registry, recognize, contratto) è invariata.

### 1) VdA — download LIBERO dalla piattaforma via proxy INVA  ⟶ `lib/vda_platform.py` (NUOVO)
I servizi ArcGIS `https://mappe.regione.vda.it/domini1/rest/services/Public/*` sono token-gated
(HTTP 499), MA il visualizzatore pubblico li raggiunge tramite il proxy
`https://mappe.regione.vda.it/INVA/config/config.ashx?<target_url>` che **inietta il token lato
server**. Passando da lì si scarica tutto gratis, senza iscrizione.
- `discover` → elenca i **56 servizi Public** + i loro layer = **856 layer** (Ambiti, CartaPAI,
  CartaDissesti, CartaGeologicaContinua, CatastoValanghe/Ghiacciai, VincoloIdrogeologico, PRG…).
- `download` → query ArcGIS **paginata via proxy** (`objectIds` a blocchi di 1000, `f=geojson`,
  `outSR=4326`) → file veri in `raw/regione/r_vda/<servizio_slug>/<NNN_layer>.geojson`.
- `registry/sources.yaml`: `r_vda` ora ha `adapter: vda_platform` (+ `proxy`, `public_services`).
- Adapter alternativi presenti: `lib/vda_local.py` (symlink dei 130 file già in
  `../Nord/Valle d'aosta/` — fallback, superato) e `lib/vda_sct.py` (token, inattivo).
- Verificato: discover 56/856; download reale `AttivitaAgricole/Agriturismi` = 53 feature.
- **Cartella download ordinata** (richiesta utente): `raw/regione/<ente>/<gruppo>/<layer>.geojson`
  uniforme tra regioni (Liguria: `M<map>/L<layer>.geojson`).

### 2) Download — batch = CHUNK, non tetto; ripresa/interruzione  ⟶ `run.py`, `stage_02`, adapters, dashboard, `page.tsx`
Prima "Batch 5" scaricava 5 layer e si fermava. Ora:
- UI «Per volta»: **«Tutte» (0) = default** → scarica **tutti i pendenti** in chunk; 5/25/50/100 = run limitato.
- UI «Solo dati nuovi» (default ON) → salta i file già presenti (**ripresa**). OFF → `--refresh` (riscarica).
- **Interrompi** (già esistente, SIGTERM) + **Riprendi** (Avvia → pendenti). Checkpoint per-layer.
- `run.py download --refresh`; `stage_02.run(..., refresh=...)`; `liguria_geoportal`/`vda_sct`/`vda_platform`
  filtrano ai pendenti se `not refresh`; `--max-services` = limite opzionale per esecuzione.
- `dashboard_server.start_region_stage(..., requested_only_new)`: niente più tetto forzato; aggiunge
  `--max-services` solo se batch>0 e `--refresh` se non only_new. Fix conteggi VdA (`layers_downloaded`,
  `services` lista) → la dashboard mostra «X/856 layer scaricati».

### 3) Composizione — selezione + stato + motore geometrico  ⟶ `lib/compose_engine.py` (NUOVO), `lib/composition_state.py`, `stage_04`, `run.py`, dashboard
Richiesta utente: la Composizione deve **chiedere quali layer formare**, indicando i **presenti** e i
**da aggiornare** (perché la sorgente con cui erano stati calcolati è stata riscritta).
- `lib/composition_state.py`: per ogni target (`registry/composition_targets.yaml`) e territorio calcola
  `assente` / `presente` / `da_aggiornare` confrontando i fingerprint registrati in
  `out/<TARGET>/<terr>.manifest.json` (`sources:[{path,fingerprint}]`) con i file attuali (`lib/state`).
- UI: ogni target è una riga con **checkbox + badge di stato**; pulsante **«Componi selezionati»**.
- `run.py compose --targets a,b --scope-level .. --scope-key ..`; `dashboard_server.start_compose`;
  POST `/api/jobs` con `stage:"compose", targets:[...]`.
- **Il motore geometrico è ora implementato per la Valle d'Aosta** e scrive
  `out/<TARGET>/<terr>.geojson` + `out/<TARGET>/<terr>.manifest.json` con fingerprint delle sorgenti.
- `PIANI_MATURITA`: usa il layer ufficiale `prg_prescrittiva/060`, normalizza APP/APC/VIC/BVT/BCV/AFF/INA
  tramite `composition_targets.yaml` e usa i confini ISTAT. Verificato: **74/74 comuni**, geometrie valide.
- `VINCOLI_COMUNALI`: risolve i file raw dai UUID del riconoscimento, conserva provenienza e confidence,
  classifica famiglia/severity in modo conservativo e ritaglia le geometrie sui comuni con `STRtree`.
  Verificato scope VdA: **3.895 feature**, tutte valide, nessun ISTAT mancante. La copertura è volutamente
  `partial`: 15 fonti riconosciute disponibili, 142 mancanti, catalogo regionale 856 layer.
- `SEMAFORO_EDIFICABILITA`: il download mirato di `P4 Zone`/`P4 Zone (BORDI)` risponde HTTP 400.
  Il motore quindi pubblica soltanto un overview cartografico comunale **UNASSESSED** (74 poligoni grigi),
  con `missing_inputs` e disclaimer; non inventa zone e non assegna RED/YELLOW/GREEN.
- `run.py compose` emette `PROGRESS`, `CALL_JSON` e `RESULT_JSON`. Una run `partial` termina con exit 0
  (processo concluso con avvertimenti), mentre `failed` resta non-zero.
- Il visualizzatore `/api/final-layers` carica i tre output: verificato **4.043 feature**, non troncate.

### 3b) Metadati PRG VdA pronti per PIANI_MATURITA  ⟶ `lib/vda_prg_updates.py` (NUOVO), fonte `r_vda_prg_updates`
Il geoportale VdA `category/pianificazione/prg` è un feed WordPress (non ospita file: rimanda a
geourbapub, le cui geometrie sono già in `vda_platform`). Utile come METADATO. `lib/vda_prg_updates.py`
(`python3 -m lib.vda_prg_updates`) produce **`work/metadata/r_vda_prg_updates.json`**: per **tutti i 74
comuni** VdA lo **stato ufficiale di adeguamento** PRG (da `ServiziGlobali/Siti/MapServer/3`: 66 Approvato,
ecc.) + la **data ultimo aggiornamento** per i 27 comuni nel feed wp-json. Chiavi per record:
`codcom, comune, stato_prg, stato_prg_desc, last_prg_update, events[]`.
**Uso in `stage_04` PIANI_MATURITA (VdA):** join `codcom → comune` alle geometrie comunali
(`Geography_Locations/outputs/admin_municipalities.geojson`, regione 02) → poligono comunale con stato
+ data, come il `PIE-QUADRO-PIANI` di Torino. Mappa stati in `composition_targets.yaml` (APP/APC/VIC/…).

### 3c) OMI nazionale — adapter completo (perimetri + valori)  ⟶ `lib/omi.py` (NUOVO), `run.py omi`, fonte `n_omi`
Scaricabile GRATIS, senza autenticazione, da tutta Italia via gli endpoint del viewer GeoPOI
(Agenzia Entrate). **Verificato end-to-end** (Aosta B2: compravendita 1200–3500, locazione 6–14,6 €/m²).
Catena: `zoneomi.php?richiesta=1` province · `=2&prov=` comuni (CODCOM Belfiore) · `=5` semestri
(20 disp., 20161→attuale) · `=3&codcom=` zone (ZONA/FASCIA/LINK_ZONA) · `=6&codcom=&semestre=` geometrie
GeoJSON per zona · `=8&codcom=&semestre=&zo=ZONA` tipologie · `stampaomi.php?CC/LINK_ZONA/S/T/ZONA/0/0`
→ **valori** (tabella compravendita/locazione min/max per tipologia e stato conservativo).
- `lib/omi.py`: `discover()` (province+semestri+campi), `download(scope, semesters|last_years, fields, refresh, max_comuni)`.
  Output: `raw/nazionale/omi/<semestre>/<PROV>/<CODCOM>.geojson` (zone con `quotazioni[]` nelle properties) + `_manifest.json` (ripresa).
- `run.py omi --action discover` · `run.py omi --scope all|province|comuni [--province AO,TO] [--last-years N | --semesters 20252,20251] [--fields ...] [--refresh] [--max-comuni N] [--dry-run] --progress`.
- Campi valore (`VALUE_FIELDS`): compravendita_min/max/sup, locazione_min/max/sup; dimensioni: tipologia, stato_conservativo.
- Registrato in `sources.yaml` come `n_omi` (endpoint documentati). Alimenta il layer finale **VALORI_OMI**.

**DA COSTRUIRE — sezione dashboard «OMI»** (richiesta esplicita utente; Codex, tuo dominio UI):
una pagina/sezione «OMI» per **rinfrescare il DB OMI** con l'utente che decide TUTTO:
scope (**tutta Italia** / province / comuni selezionati), **periodo** (ultimi N anni / semestri espliciti),
**campi** (checkbox: compravendita min/max, locazione min/max, superficie, medi…), pulsante
**«Rinfresca DB OMI»**, avanzamento a batch con ripresa (come Download). Il backend chiama
`run.py omi ...` (o `lib.omi.download`); `dashboard_server` aggiunga un endpoint/`start_omi` analogo a
`start_region_stage`. Il `--dry-run` fornisce il preventivo (#comune×semestre) prima di lanciare.

### 3d) Composizione — 15 layer finali approvati (blocchi 1-3 di mobilitylens/piattaforma)
`registry/composition_targets.yaml` ora ha **16 target**: i 3 core (con builder) + 13 nuovi APPROVATI
(senza builder → appaiono «assente»). Da implementare i builder in `compose_engine.py`:
- Blocco 1: `ANALISI_URBANISTICA` (PRG_ZONING+edifici storici), `CATASTO` (opz.).
- Blocco 2 (**split** di `VINCOLI_COMUNALI`, che resta base tecnica del Semaforo):
  `TUTELE_AMBIENTALI_PAESAGGISTICHE` (famiglie paesaggio/natura/acque) e `RISCHI_PERICOLOSITA`
  (inedificabilità/dissesto) — viste per comune con `derived_from: VINCOLI_COMUNALI` + `families`.
- Blocco 3 (stato attuale): `MOBILITA_ACCESSIBILITA`, `RETE_VIABILITA`, `SOSTA_ACCESSI_URBANI`,
  `SERVIZI_POLARITA`, `COMMERCIO_PRODUTTIVO`, `VALORI_OMI` (←`lib/omi.py`), `DEMOGRAFIA`,
  `ENERGIA_RETI`, `INFRASTRUTTURE_AINOP`. Ogni target ha `sources` (classi canoniche), `expresses`, `classes`.

### 3e) Fonti CKAN MIT (dati.mit.gov.it) — adapter `lib/ckan_mit.py` (NUOVO)
Dataset CKAN scaricati e combinati offline. L'adapter scarica in **locale** al primo giro e
**sovrascrive** con `--refresh` (richiesta esplicita utente). Dispatch via `kind: ckan` /
`adapter: ckan_mit` negli stadi 01/02.
- `discover`: `package_show` → elenco risorse → `work/catalog/<key>.csv`.
- `download`: formato preferito **CSV**>XLSX>XLS>JSON (PDF escluso), in `raw/nazionale/<key>/<nome>.<ext>`
  + `_manifest.json`; skip-esistenti di default, overwrite con `--refresh`. Testato (Opere Incompiute).
- Fonti registrate in `sources.yaml`:
  - **`n_ainop_opere`** (`elenco-opere-pubbliche-censite-su-portale-ainop`, 22 risorse) → alimenta **INFRASTRUTTURE_AINOP** (`feeds_target`).
  - **`n_opere_incompiute`** (`opere-incompiute`, 9 risorse) → alimenta **ANALISI_URBANISTICA** (`feeds_target`).
- CLI: `python3 run.py discover --source n_ainop_opere` · `run.py download --source n_ainop_opere --refresh --progress`.
- Nota: AINOP opere ~100MB (edilizia/ponti stradali sono i file grandi); scaricare a batch. Il builder
  di INFRASTRUTTURE_AINOP e ANALISI_URBANISTICA combinerà questi CSV con le altre fonti.
- **Freschezza (implementata):** `discover` legge la data di ultimo aggiornamento del dataset
  (`metadata_modified` + max `last_modified` risorse) e la confronta con l'ultimo scarico salvato in
  `state/ckan_<key>.json` → ritorna `needs_update` (+ `last_modified`, `downloaded_modified`).
  `download` fa **auto-overwrite** se la data remota è cambiata (senza bisogno di `--refresh`), e salva
  lo stato solo a scarico completo (i batch parziali non marcano il DB come aggiornato).
- **Consultazione per-zona (orchestrazione, da fare in dashboard):** quando l'utente scarica i dati per un
  territorio, l'orchestratore deve **passare in rassegna anche questi DB nazionali** — cioè eseguire
  `discover` su `n_ainop_opere` / `n_opere_incompiute` / `n_omi`, e se `needs_update` è vero lanciarne il
  `download` (aggiornamento). I dati restano nazionali: il filtro sul territorio avviene in `compose`
  (INFRASTRUTTURE_AINOP / ANALISI_URBANISTICA / VALORI_OMI ritagliano il DB sulla zona).

### 3f) RIDISEGNO COMPOSIZIONE — da "layer per fonte" a "layer per DOMANDA DECISIONALE"  ⟵ DIREZIONE CORRENTE
I 16 target attuali in `composition_targets.yaml` sono **provvisori**: NON sono i layer finali. La
piattaforma è per **investitori immobiliari e urbanisti** → i layer vanno organizzati per DOMANDA
("posso intervenire? quanto costruisco? quali rischi? quanto vale? cosa cambierà?"), non per fonte.
Approccio deciso: **mix** — impostare subito la struttura nei registri (layer nuovi come "definiti, in
attesa fonte/motore") E aggiungere le fonti nuove una alla volta (verificate come OMI/AINOP).

**Filtro trasversale — 3 famiglie (mai mescolarle in mappa):** ESISTE (stato attuale) · CONSENTITO
(regole/vincoli) · CAMBIERÀ (pipeline futura). Ogni layer ne dichiara una (`family`).

**Nuova gerarchia: 5 BLOCCHI → sottoblocchi → layer.** Legenda fattibilità:
✅ costruibile ora (dati esistenti) · 🆕 serve nuova fonte · 🧮 derivato/calcolato.

- **BLOCCO 1 · INVESTABILITY** (CONSENTITO) — cosa/quanto si può trasformare
  - 1.1 Trasformabilità urbanistica: **Potenziale di trasformazione** 🧮 (6 classi: immediatamente
    trasformabile → non trasformabile; deriva da destinazione+usi+indice/SLP+altezza+RC+premialità+
    obbligo piano attuativo+perequazione+stato piano; NTA numeriche 🆕 per comune) · **Analisi
    Urbanistica** ✅ · **Maturità dei piani** ✅.
  - 1.2 Edifici e rigenerazione 🆕 (impronta, altezza, piani, volume, epoca, uso, dismesso/
    sottoutilizzato, classe energetica) — fonti Copernicus Urban Atlas, SIAPE, catasto edifici.
- **BLOCCO 2 · RISK & CONSTRAINTS** (CONSENTITO+ESISTE)
  - 2.1 **Vincoli e limitazioni** — un layer per TIPO (paesaggistico, monumentale, bene culturale,
    fascia di rispetto, parco/area naturale, Natura 2000, idrogeologico, aeroportuale, fascia
    ferroviaria/stradale, elettrodotti/servitù, bonifiche/contaminati, archeologico). Ogni vincolo con
    atto/data/ente/autorizzazione/grado/link/attendibilità. Base TUTELE ✅ + **Vincoli in Rete** 🆕.
  - 2.2 **Rischio fisico e climatico** (autonomo dai vincoli): alluvioni, frane, sismico, subsidenza,
    erosione, incendi, isola di calore, impermeabilizzazione, rumore, aria. Per l'investitore 🧮:
    **% lotto interessata**, pericolosità max, edifici esposti, impatto assicurativo, mitigazione,
    penalità score. Base RISCHI ✅ + **IdroGEO/ISPRA** 🆕 + sismica/clima 🆕.
- **BLOCCO 3 · MARKET & DEMAND** (ESISTE)
  - 3.1 **Market attractiveness** 🧮 (valori/trend/rendimento; base OMI ✅ `lib/omi.py`) · **Market
    liquidity** 🆕 (transazioni, assorbimento, vacancy).
  - 3.2 **Domanda territoriale** 🆕 sub-comunale (pop. griglia 1km²/sezione, età, reddito, pendolari…;
    base Demografia ✅ + **ISTAT griglia** 🆕) → indicatori 🧮 (pressione abitativa, domanda
    retail/student/senior housing, bacino lavoratori, vulnerabilità sociale).
- **BLOCCO 4 · ACCESSIBILITY** (ESISTE+CAMBIERÀ)
  - 4.1 **Accessibilità generata** 🧮 (isocrone 15/30/45, frequenza reale TPL, destinazioni
    raggiungibili, congestione, ciclabilità; base Mobilità/Viabilità/Sosta ✅ + **motore isocrone** 🧮).
  - 4.2 **Servizi e polarità** ✅ (upgrade con accessibilità/capacità/pop. servita).
- **BLOCCO 5 · TRANSFORMATION PIPELINE** (CAMBIERÀ)
  - 5.1 **Progetti e investimenti** classificati per **MATURITÀ 1-10** (proposta→finanziato→in
    costruzione→completato/sospeso); peso ≠ tra "citato in PUMS" e "finanziato". Fonti OpenCUP ✅,
    PNRR ✅, AINOP ✅ (`n_ainop_opere`), Opere incompiute ✅ (`n_opere_incompiute`), PUMS ✅.
  - 5.2 **Varianti e trasformazioni** ✅ (ambiti di trasformazione, varianti in corso).

**Output finale = REPORT per area/particella** (evoluzione del "Polygon" della demo): potenziale
edificatorio, vincoli, rischi, mercato, accessibilità, domanda, progetti futuri, qualità/aggiornamento
fonti, **score complessivo** + fattori che lo alzano/abbassano.

**Correzioni sui 16 attuali:** `CATASTO` NON è un layer finale (è base/supporto per particelle) →
declassare. `VALORI_OMI`→Market attractiveness (blocco 3). Mobilità/Viabilità/Sosta→Accessibilità
(blocco 4). I 16 confluiscono nei blocchi 1-4 rielaborati; il vincolo unico si ESPLODE per tipo;
nascono gli indicatori 🧮 (Potenziale trasformazione, Market attractiveness/liquidity, Accessibilità
generata, score).

**Nuove fonti da aggiungere (verificare download come OMI/AINOP, poi registrare in `sources.yaml`):**
Vincoli in Rete (vincoliinrete.beniculturali.it), IdroGEO/ISPRA (idrogeo.isprambiente.it), ISTAT
griglia 1km²/sezioni, SIAPE (siape.enea.it, energia edifici), Copernicus Urban Atlas (land.copernicus.eu),
dati transazioni immobiliari.

**Passi:** (1) riscrivere `composition_targets.yaml` + `composition_mapping.yaml` con blocco/sottoblocco/
`family` e i layer nuovi (🆕/🧮 = definiti, senza builder); (2) UI Composizione raggruppa per blocco→
sottoblocco; (3) aggiungere le fonti nuove incrementalmente; (4) builder + report/score.

### 3g) Sessione tarda: health check fonti, tracciabilità, AINOP XLSX, mappa, pulizia fonti
Tutto in locale, testato.

**Health check dei link fonti** — `dashboard_server.py`:
- `GET /api/sources/health` → per ogni fonte verifica **portale + endpoint dati** (HEAD, fallback GET),
  stato `ok`/`degradato`/`errore`, in parallelo (ThreadPool). Funzioni: `_check_url`, `_source_check_urls`,
  `sources_health`.
- UI: pulsante **«Verifica link»** nella tab **Fonti** (`page.tsx`, stato `health`/`runHealthCheck`) + CSS
  `.sources-health`/`.health-*`. Esito attuale: 13 fonti, r_piemon(403)/p_to(404) = blocchi anti-bot.

**Tracciabilità layer → dati originali** — `dashboard_server.py` (richiesta utente: "da un layer risalire
sempre ai dati originali, interno ma disponibile su richiesta"):
- `GET /api/provenance?target=<LAYER>&level=<liv>&key=<istat>` → legge `out/<TARGET>/<terr>.manifest.json`
  (`sources:[{path,fingerprint}]`) e il GeoJSON prodotto. Ritorna `raw_sources` (file grezzo → chiave
  fonte nel registry via `_source_key_from_path`, ente, **portale**, fingerprint) + `layer_sources`
  (source_uuid/title/url/date distinti per-feature). Esclude i file `registry/` (config). Funzioni:
  `_source_key_from_path`, `layer_provenance`.
- **DA FARE UI (Codex):** azione **«Dati originali»** sul layer composto (stato `presente`/`da_aggiornare`
  nella sezione Composizione) che apre la provenienza da questo endpoint. Endpoint già pronto.

**AINOP in XLSX** — `lib/ckan_mit.py` + `sources.yaml`: aggiunto `prefer_formats` per fonte
(`_chosen_resources(..., rank)`). `n_ainop_opere` ha `prefer_formats: [XLSX, CSV]` → scaricati **11 XLSX
(23MB)** in `raw/nazionale/n_ainop_opere/` (0 CSV residui). Per cambiare formato: edita `prefer_formats`.

**Fonti rimosse** (link morti dal health check): `n_opencup`, `n_opencoesione`, `n_ainop` (vecchia
ainop.mit.gov.it). Restano 13 fonti; l'AINOP corretto è `n_ainop_opere` (CKAN dati.mit.gov.it).

**Mappa Italia** (`page.tsx` `ItalyMap` + `globals.css` + `dashboard_server.admin_geojson`):
- Bordi: tolleranza di semplificazione 0.012→0.005 (regioni) / 0.006→0.0035 (province) + `stroke-linejoin: round`.
- Etichette: nomi accorciati (parte prima di "/" bilingue, troncamento) + **declutter** (repulsione fra
  riquadri, 80 passate, nel `useMemo`) + **alone bianco** (`paint-order:stroke`). Niente più collisioni.

**IMPORTANTE — riavvio controller:** `dashboard_server.py` usa `@lru_cache` su `sources_config()`; dopo
modifiche a `sources.yaml` o a `dashboard_server.py` **riavviare** (`kill $(lsof -ti tcp:8765); python3 -u dashboard_server.py &`).

### 4) Dashboard live
`dashboard_server.py` (:8765) e Next dev (:3000) girano. **Dopo modifiche a `dashboard_server.py`
riavviare il controller**: `kill $(lsof -ti tcp:8765); python3 -u dashboard_server.py &`. Il frontend :3000
fa HMR; i subprocess `run.py` prendono le modifiche degli adapter senza riavvio.

### Prossimi passi (priorità)
1. Correggere nell'adapter VdA il download dei layer grandi `P4 Zone`/`P4 Zone (BORDI)` (HTTP 400
   sulla prima pagina); poi produrre il Semaforo alla scala reale della zona urbanistica.
2. Lanciare/verificare il download completo VdA (856 layer) dalla dashboard con «Tutte» e ricomporre
   `VINCOLI_COMUNALI`, finché il manifest di copertura può essere certificato completo.
3. Estendere lo stesso motore di composizione alla Liguria rispettando PTR/PPR, PTCP/PTM e PUC.
4. Poi `stage_05_load` (dry-run obbligatorio) come da contratto sotto.

---

## Cos'è

Sistema che **generalizza a tutta Italia** ciò che è stato fatto a mano su Torino/Piemonte. Data una
lista di URL (opendata di comuni/province/regioni, geoportali), la catena:

1. **scopre** gli endpoint dei dataset → 2. **scarica** i layer grezzi → 3. **riconosce** cosa sono
(dizionario formulazione→classe canonica) → 4. **compone** i layer riconosciuti in layer finali più
informativi **senza perdere la tracciabilità** → 5. **carica** su Supabase (riuso pipeline esistente).

Non è un monolite: **catena di stadi `.py` idempotenti** orchestrati da `run.py`, guidati da `registry/`.
Ogni stadio rigira solo se il suo input è cambiato (hash in `state/`). L'ordine territoriale predefinito è
**regione → provincia (+ area metropolitana) → comune**, ma viene adattato dai profili regionali:
per la Valle d'Aosta è **regione → comune**, senza introdurre una fittizia fonte provinciale.

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
  run.py                       orchestratore: `recognize`, `context`, `status`; idempotenza via lib/state
  requirements.txt  .gitignore
  registry/
    canonical_taxonomy.yaml    34 classi FINALI, con macro(1..4), plan_type, geometry, topics, torino_ref (PIE-*)
    layer_dictionary.yaml      regole formulazione→canonico: any/all/not_any/topic_in/confidence/examples
    sources.yaml               fonti e adapter; Valle d'Aosta: 44 servizi SCT, 6 PTP e stato PRG
    regional_planning_profiles.yaml
                               livelli, strumenti, coperture e portali attesi per ciascuna regione
  lib/
    normalize.py               norm_name (comuni, = NORMALIZATION_RULES.md) · norm_match (titoli) · tokens
    recognize.py               Recognizer: match(title,topic)→Match(canonical,confidence,score,reason) o proposals
    planning_context.py        carica/valida il profilo regionale; output per pipeline e dashboard
    vda_sct.py                 discovery SCT + export ArcGIS REST a GeoJSON con token solo in ambiente
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
