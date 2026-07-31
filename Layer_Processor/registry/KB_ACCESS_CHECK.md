# KB nazionale — verifica accessibilità endpoint (2026-07-31)

Verifica leggera (HEAD / range-GET, nessun download completo) delle 27 fonti KB
aggiunte a `registry/sources.yaml`. Legenda: ✅ dato reale servito · 🟡 portale/SPA
raggiungibile (dati dietro API/JS da mappare) · ⚠️ nota.

| Fonte | Endpoint testato | HTTP | Esito |
|---|---|---|---|
| n_catasto_inspire | GetDataset.php?dataset=ITALIA.zip | 403 | ⚠️ hotlink bloccato ma **già scaricato in locale** (ITALIA/) |
| n_catasto_inspire (backup) | dati.gov.it id 9d74351a | 200 | ✅ |
| n_toponimi_italia | dati.gov.it id c4e7e889 | 200 | ✅ pagina dataset |
| n_anncsu | getds.php?STRAD_ITA | 206 | ✅ octet-stream (download reale) |
| n_anncsu | getds.php?INDIR_ITA | 206 | ✅ octet-stream |
| n_catasto_tn | catastotn.tndigit.it | 206 | 🟡 sito su, meccanismo scarico da mappare |
| n_agcom_connettivita | geo.agcom.it/reportistica/ | 206 | 🟡 portale |
| n_arco_beni_culturali | wit.istc.cnr.it/arco/ | 200 | 🟡 hub RDF/SPARQL |
| n_cultura_dataset_locali | dati.cultura.gov.it/dataset_locali/ | 200 | 🟡 |
| n_cultura_on | dati.cultura.gov.it/cultural_on/ | 200 | 🟡 |
| n_istat_censimento_sezioni | Comuni_2023.zip | 206 | ✅ zip reale |
| n_istat_censimento_sezioni | Dati_regionali_2023.zip | 206 | ✅ zip reale |
| n_istat_basi_territoriali | notizia basi-territoriali | 200 | 🟡 pagina indice |
| n_anac_opendata | opendata/ocds_it | 200 | 🟡 SPA (API OCDS a parte) |
| n_anac_opendata | opendata/dataset | 200 | 🟡 SPA |
| n_istat_posas | demo.istat.it | 200 | ✅ |
| n_mimit_carburanti | prezzo_alle_8.csv | 206 | ✅ text/csv reale |
| n_mimit_carburanti | anagrafica_impianti_attivi.csv | 206 | ✅ text/csv reale |
| n_mef_immobili_pubblici | open_data_immobili/ | 200 | 🟡 pagina |
| n_colonnine_ricarica | piattaformaunicanazionale.it/idr | 206 | 🟡 SPA (export da verificare) |
| n_mef_irpef | finanze.gov.it opendata | 200 | 🟡 elenco DB |
| n_salute_presidi | dati.salute.gov.it/.../farmacie | 206 | ✅ raggiungibile |
| n_miur_scuole | dati.istruzione.it catalogo | 200 | ✅ catalogo |
| n_siope | siope.it dispatchHome | 200 | 🟡 |
| n_ispra_suolo | isprambiente consumo-suolo | 206 | 🟡 |
| n_ispra_idrogeo | idrogeo.isprambiente.it/app/ | 206 | 🟡 SPA (API IdroGEO) |
| n_ispra_rifiuti | catasto-rifiuti.isprambiente.it | 200 | 🟡 |
| n_runts | servizi.lavoro.gov.it/runts | 200 | ✅ |
| n_aci_opendata | aci.gov.it open-data | 200 | ✅ |

**Sintesi:** tutti gli endpoint rispondono. Dati diretti confermati (download reale):
ANNCSU STRAD/INDIR, ISTAT zip censimento, MIMIT CSV. I portali/SPA sono raggiungibili
ma richiederanno un adapter dedicato per estrarre i dati (API/SDMX/SPARQL). L'unico
"errore" (ITALIA.zip 403) è ininfluente perché il dato è già in locale.
