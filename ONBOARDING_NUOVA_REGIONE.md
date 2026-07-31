# 🧭 Onboarding di una regione/territorio nuovo — LEGGI PRIMA DI INIZIARE

> Guida operativa per aggiungere una nuova regione (o provincia/comune) al **Layer_Processor**.
> Cartella progetto: `Layer_Processor/`.
> **Leggi questo file per intero prima di toccare qualsiasi cosa.** Poi tieni aperti anche
> `CODEX_HANDOFF_LAYER_PROCESSOR.md` e `CLAUDE_CONTINUA_QUI.md` (stato corrente + gotcha).

---

## 0. Principi non negoziabili (regole di lavoro)

1. **Parla italiano.**
2. **Non committare** senza che l'utente lo chieda esplicitamente. Lui committa quando decide lui.
3. **I downloader restano per-regione.** Ogni territorio ha il suo adapter/config: è voluto, tiene
   conto delle specificità (proxy, formati, bilinguismo, endpoint rotti). **L'uniformità sta nella
   COMPOSIZIONE**, non nel download.
4. **Download pesanti → in background**, e **riferisci l'esito reale** (conteggi feature, errori).
   Niente ottimismo: se qualcosa fallisce, dillo con i numeri.
5. **C'è Codex che lavora in parallelo** sugli stessi file (registry, recognize, mapping). Non
   revertire il suo lavoro; le modifiche al dizionario/registry falle **additive** e coordinate via
   `CODEX_HANDOFF_LAYER_PROCESSOR.md`.
6. **Gap non colmabili esistono** (piani solo-WMS, cartaceo, catasti chiusi). Vanno **documentati**,
   non forzati. Se un dato serve ma non è scaricabile, si prepara una richiesta all'ente (vedi
   `richiesta_PRGUSO_PAT.md` come esempio) — **non inviarla tu**.

---

## 1. La pipeline in 30 secondi

```
00 (ricognizione istituzionale)  →  01 discover  →  02 download  →  03 recognize  →  04 compose  →  05 load(futuro)
        capire il territorio         trova gli        scarica il      grezzo →         classe →       Supabase
        e la gerarchia piani         endpoint         GeoJSON         classe canonica  layer finale
```

- **Fonti** → `registry/sources.yaml` (una entry per entità).
- **Riconoscimento** → `registry/layer_dictionary.yaml` (regole testo grezzo → classe canonica).
- **Classi canoniche** (il "concetto", region-agnostic) → `registry/canonical_taxonomy.yaml`.
- **Layer finali** e da quali classi si compongono → `registry/composition_targets.yaml`
  (+ `registry/composition_mapping.yaml` per i mapping `by_region` espliciti).
- **Composizione** → `lib/compose_engine.py` (**generico** per tutte le regioni).
- **Dashboard** → `dashboard_server.py` (API :8765) + frontend Node (:3000), avvio `start_dashboard.py`.

Chi alimenta cosa (concetto → target finale):
`PRG_ZONING/EDIFICI_STORICI/CATASTO → ANALISI_URBANISTICA`,
`AREE_PROTETTE/RETE_ECOLOGICA/VINCOLI_PAESAGGISTICI/ACQUE/AGRICOLTURA → TUTELE_AMBIENTALI_PAESAGGISTICHE`,
`RISCHIO_IDRAULICO/DISSESTO_GEOLOGICO/VINCOLO_IDROGEOLOGICO/ALLERTA → RISCHI_PERICOLOSITA`,
mobilità/viabilità/servizi/commercio/energia/demografia → i rispettivi target di blocco 3.
Obiettivo finale: un **semaforo di edificabilità** per comune/lotto.

---

## STEP 0 · Ricognizione istituzionale (prima di scrivere codice)

Prima di cercare endpoint, **capisci il territorio**. Ogni regione ha una struttura di
pianificazione diversa; sbagliarla significa mappare i layer sulle classi sbagliate.

Domande a cui rispondere e da **scrivere in una nota** (come ha fatto l'utente per FVG):
- Regione a statuto **ordinario o speciale**? Ci sono **Province** o sono state abolite?
  (Cambia se esiste il livello PTCP/area vasta.)
- Qual è il **piano paesaggistico** vigente (PPR) e la sua data? È prescrittivo/prevalente?
- Qual è il **piano territoriale regionale** (PTR/PURG/PUP…) e cosa contiene?
- Livello **comunale**: come si chiama lo strumento (PRG/PRGC/PGT/PI…)? È in transizione
  (es. "variante di conformazione al PPR")?
- Che **rischi** dominano (idraulico PAI, dissesto, valanghe) e come "congelano" l'edificabilità?
- **Bilinguismo / lingue** negli attributi (es. BZ IT/DE)?

Da questa nota ricavi **la mappatura concettuale** (quale piano → quale classe canonica) e
**quali target** ha senso comporre.

---

## STEP 1 · Discover — trovare gli endpoint

1. Individua i **geoportali** ufficiali della regione. Ordine di preferenza tecnica:
   - **WFS** (`GetCapabilities`) → adapter `wfs_generic` (il più riusabile).
   - **ArcGIS REST** (`/MapServer`, `/FeatureServer` + `?f=json`) → adapter `arcgis_rest`.
   - **CKAN / Socrata / open-data** → `ckan_collection` / `socrata` / `ckan_mit`.
   - Piattaforme WebGIS proprietarie → può servire un **adapter dedicato** (es. `veneto_webgis`,
     `liguria_geoportal`, `vda_platform`).
2. Verifica sul campo con `curl`:
   ```bash
   curl -s "https://<host>/geoserver/<ws>/wfs?service=WFS&version=2.0.0&request=GetCapabilities" | head
   curl -s "https://<host>/arcgis/rest/services?f=json" | head
   ```
3. Annota per ogni endpoint: URL base, workspace/service, `output_format` accettato, SRS,
   eventuale **proxy** intranet, quanti layer, formati (GeoJSON vs SHP/ZIP).

**Codici ISTAT** (obbligatori): trova il `region_istat` a 2 cifre in `registry/sources.yaml`
sotto `territorial_registry.regions` (es. `"06": "Friuli-Venezia Giulia"`). Province a 3 cifre,
comuni a 6.

---

## STEP 2 · Registrare le fonti in `sources.yaml`

Una **entry per entità** (una regione può averne molte: piani, pericolosità, geologia, servizi…).
Prefisso della `key`: `r_` regione, `p_` provincia, `c_` comune. Schema reale (esempio):

```yaml
  - key: r_fvg_ppr                       # identificatore univoco (r_<regione>_<tema>)
    livello: regione                     # regione | provincia | comune
    ente: "Regione FVG — Piano Paesaggistico Regionale (PPR)"
    region: "Friuli-Venezia Giulia"
    region_istat: "06"                   # 2 cifre, da territorial_registry.regions
    kind: wfs                            # wfs | arcgis | ckan | ...
    adapter: wfs_generic                 # nome modulo in lib/
    url: "https://irdat.regione.fvg.it/..."     # pagina umana di riferimento
    wfs_url: "https://.../geoserver/<ws>/wfs"    # endpoint macchina
    wfs_version: "2.0.0"
    output_format: "application/json"    # per Torino MapServer usa "geojson"!
    srs: "EPSG:4326"
    # proxy_template: "https://.../ogcproxy?url={url}"   # solo se serve proxy intranet
    topic: planningCadastre              # categoria ISO prevalente
    feeds_target: TUTELE_AMBIENTALI_PAESAGGISTICHE
    dashboard_batch_size: 20             # quanti layer per run di download
    type_names:                          # se noti in anticipo (WFS): elenco layer
      - {name: "<ws>:<layer>", title: "<titolo leggibile>"}
    status: active
    notes: >
      Contesto, gotcha, cosa alimenta. Documenta qui i problemi.
```

Se i `type_names` non sono noti, li scopre il discover dal `GetCapabilities`.

---

## STEP 3 · Download (in background)

```bash
# via CLI, singola fonte:
python3 run.py download --source r_fvg_ppr
# multi-fonte (dashboard usa questo):
python3 tools/run_sources.py download --sources r_fvg_ppr,r_fvg_prgc,r_fvg_pai
```

- Lancia **in background** se pesante; poi riferisci `layers_downloaded` / `layers_failed` reali
  dal manifest `raw/regione/<key>/_manifest.json`.
- I dati grezzi vanno in `raw/regione/<key>/`. **Il builder generico di composizione legge solo
  GeoJSON**: se una fonte è **SHP/ZIP** (come Piemonte `r_piemon`), serve un passo di estrazione
  ZIP→GeoJSON prima di poter comporre.

---

## STEP 4 · Recognize + estendere il dizionario

```bash
python3 run.py recognize --catalog work/catalog/r_fvg_ppr.csv --ente r_fvg_ppr
```

- Guarda la % riconosciuta e i **non riconosciuti** in `work/proposals/<ente>.json`.
- Estendi `registry/layer_dictionary.yaml` **in coda, con regole additive** (il matcher tiene il
  best score: non togli nulla a Codex). Ogni regola: `canonical` + `any:[keyword]` (+ opz.
  `all`, `not_any`, `topic_in`, `confidence`, `examples`).

**Trucchi verificati (fanno risparmiare ore):**
- Le keyword sono **minuscole, senza accenti**, punteggiatura → spazio
  (`"corsi d'acqua"` → `"corsi d acqua"`). Match per **sottostringa** di token: keyword corte
  rischiano falsi positivi → usa keyword **lunghe e distintive**.
- **`topic_in` è un gate**: se il titolo ha un `topic` noto **fuori** dalla lista, la regola NON
  scatta. Molti piani portano tutto come `topic=planningCadastre`, che blocca classi ambientali
  (ACQUE, AREE_PROTETTE…). **Una regola SENZA `topic_in` bypassa il gate.**
- Per evitare falsi positivi cross-regione quando ometti `topic_in`, usa keyword **ultra-specifiche**:
  codici univoci (es. `"z101 p pup"` Trentino) o termini in **lingua** non italiana (tedesco BZ).
- Il rumore cartografico (inquadramenti, toponomastica, confini, simboli, elementi lineari/puntuali
  generici) **va lasciato non riconosciuto**: mapparlo inquina i layer finali.

---

## STEP 5 · (Se serve) nuova classe canonica

Se un dato reale non ha una classe canonica adatta (es. **POI generici**), creala — **decisione
dell'utente**, non forzare mapping approssimativi:
1. `registry/canonical_taxonomy.yaml` → aggiungi la classe:
   ```yaml
     SERVIZI_POI:
       macro: 3
       plan_type: stato
       geometry: point
       description: "…"
       topics: [structure, society]
       torino_ref: []
   ```
2. `registry/composition_targets.yaml` → aggiungila alle `sources:` del target giusto
   (es. `SERVIZI_POLARITA`).
3. `registry/layer_dictionary.yaml` → regola che mappa i layer sulla nuova classe.
4. Ri-esegui recognize e verifica.

---

## STEP 6 · Compose (verifica l'output reale)

```bash
python3 run.py compose --scope-level region --scope-key 06 --targets ANALISI_URBANISTICA
# tutti i target:
python3 run.py compose --scope-level region --scope-key 06 \
  --targets ANALISI_URBANISTICA,TUTELE_AMBIENTALI_PAESAGGISTICHE,RISCHI_PERICOLOSITA
```

- Output in `out/<TARGET>/<region_istat>.geojson` + `.manifest.json`.
- Controlla `status: completed`, `features`, e `coverage.classes`.
- ⚠️ Alcuni builder dedicati (es. **VINCOLI_COMUNALI**) fanno assegnazione spaziale ai comuni e
  possono essere **molto lenti** su regioni multi-fonte: componi un target per volta e valuta i tempi.

---

## STEP 7 · Collegare la regione alla DASHBOARD

Perché i pulsanti dei processi compaiano nella dashboard servono **due voci** in
`dashboard_server.py`, chiavate `("region", "<istat>")`:

```python
# SCOPE_RUNNERS — abilita recognize + compose (compose_available default True; niente
#                 compose_targets = TUTTI i target permessi grazie al builder generico)
("region", "06"): {
    "ente": "r_fvg_ppr",                                  # entità primaria
    "label": "Friuli-Venezia Giulia",
    "prefixes": None,
    "catalog": ROOT / "work" / "catalog" / "r_fvg_ppr.csv",
},

# SCOPE_PIPELINES — abilita discover + download + progress; elenca TUTTE le entità
("region", "06"): {
    "source": "r_fvg_ppr",
    "sources": ["r_fvg_ppr", "r_fvg_prgc", "r_fvg_pai", ...],
    "label": "Friuli-Venezia Giulia",
},
```

Regole:
- Se `sources` ha **>1 entità**, il recognize usa `tools/run_recognize_sources.py --sources …` e il
  download `tools/run_sources.py … --sources …` (gestito in automatico).
- Escludi dalle `sources` le entità **non scaricabili** (solo-WMS): trascinerebbero giù il progresso.
- Dopo la modifica **riavvia l'API** (non basta il frontend):
  ```bash
  kill <pid_dashboard_server>; PYTHONUNBUFFERED=1 nohup python3 -u dashboard_server.py --port 8765 > /tmp/dashboard_api.log 2>&1 &
  ```
  Poi **ricarica** http://localhost:3000. Verifica via API:
  ```bash
  curl -s "http://localhost:8765/api/dashboard?level=region&key=06" | python3 -m json.tool | grep -A2 available
  ```

---

## Gotcha noti (da NON ri-derivare)

- **Torino PRGC (MapServer)**: `outputFormat=geojson` (rifiuta `application/json`).
- **ArcGIS**: `f=geojson` può rompersi oltre ~58k feature → `arcgis_rest` usa `f=json` +
  conversione Esri→GeoJSON + cursore su OBJECTID (non `resultOffset`).
- **Trento**: GeoServer su host intranet → si passa dal **proxy** ogcproxy del webgis; non
  pre-codificare `:`/`/` nei parametri interni (`urlencode(safe=":/,")`) o HTTP 500.
- **Bolzano**: path OWS diverso per host; attributi **bilingui** IT/DE (`BEZ_I`/`BEZ_D`).
- **ZIP/SHP**: il compose generico legge solo GeoJSON → serve estrazione preventiva.
- **Piani solo-WMS** (es. PRGUSO Trentino): non scaricabili come vettoriale → gap documentato +
  richiesta all'ente.

---

## ✅ Checklist finale per una regione nuova

- [ ] STEP 0 — nota istituzionale scritta (gerarchia piani, province sì/no, PPR, rischi, lingue)
- [ ] STEP 1 — endpoint verificati con `curl` (WFS/ArcGIS/CKAN), `region_istat` individuato
- [ ] STEP 2 — entità aggiunte in `sources.yaml` (una per tema)
- [ ] STEP 3 — download eseguito (in background), conteggi reali riportati
- [ ] STEP 4 — recognize eseguito + dizionario esteso (regole additive), residui = solo rumore
- [ ] STEP 5 — eventuale nuova classe canonica creata e agganciata a un target
- [ ] STEP 6 — compose verificato: `out/<TARGET>/<istat>.geojson` con feature reali
- [ ] STEP 7 — regione collegata alla dashboard (SCOPE_RUNNERS + SCOPE_PIPELINES) + API riavviata
- [ ] Handoff aggiornato (`CODEX_HANDOFF_LAYER_PROCESSOR.md` / `CLAUDE_CONTINUA_QUI.md`)
- [ ] **Niente commit** salvo richiesta esplicita dell'utente
</content>
</invoke>
