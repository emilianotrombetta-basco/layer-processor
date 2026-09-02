#!/usr/bin/env bash
# Esegue le 29 composizioni di Livello 1 (dati riconosciuti, composizione mancante).
# Una regione alla volta, un target alla volta, con timeout di 10 minuti per job.
set -euo pipefail
cd "$(dirname "$0")/.."

TIMEOUT=600  # 10 minuti per composizione
OK=0
FAIL=0
SKIP=0

compose() {
  local target="$1" region="$2"
  local outfile="out/${target}/${region}.geojson"
  if [ -f "$outfile" ]; then
    echo "SKIP  $target r$region (già presente)"
    SKIP=$((SKIP + 1))
    return 0
  fi
  echo "---"
  echo "RUN   $target r$region"
  if timeout "$TIMEOUT" python3 run.py compose \
      --targets "$target" \
      --scope-level region --scope-key "$region" 2>&1 | tail -5; then
    if [ -f "$outfile" ]; then
      echo "OK    $target r$region"
      OK=$((OK + 1))
    else
      echo "WARN  $target r$region (nessun output prodotto)"
      FAIL=$((FAIL + 1))
    fi
  else
    echo "FAIL  $target r$region (timeout o errore)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Livello 1: composizioni mancanti ==="
echo "Inizio: $(date)"
echo ""

# Regione 01 - Piemonte
compose RISCHI_PERICOLOSITA 01
compose SERVIZI_POLARITA 01
compose MOBILITA_ACCESSIBILITA 01
compose ENERGIA_RETI 01
compose COMMERCIO_PRODUTTIVO 01

# Regione 02 - VdA
compose ENERGIA_RETI 02

# Regione 03 - Lombardia
compose TUTELE_AMBIENTALI_PAESAGGISTICHE 03
compose RISCHI_PERICOLOSITA 03
compose VINCOLI_COMUNALI 03
compose RETE_VIABILITA 03
compose MOBILITA_ACCESSIBILITA 03
compose SERVIZI_POLARITA 03
compose COMMERCIO_PRODUTTIVO 03

# Regione 05 - Veneto
compose TUTELE_AMBIENTALI_PAESAGGISTICHE 05
compose RISCHI_PERICOLOSITA 05
compose RETE_VIABILITA 05
compose MOBILITA_ACCESSIBILITA 05
compose SERVIZI_POLARITA 05
compose COMMERCIO_PRODUTTIVO 05

# Regione 07 - Liguria
compose TUTELE_AMBIENTALI_PAESAGGISTICHE 07
compose RISCHI_PERICOLOSITA 07
compose VINCOLI_COMUNALI 07
compose SERVIZI_POLARITA 07

# Regione 08 - Emilia-Romagna
compose RISCHI_PERICOLOSITA 08
compose VINCOLI_COMUNALI 08  # nota: ha PTCP provinciali
compose RETE_VIABILITA 08
compose SERVIZI_POLARITA 08

# Regione 12 - Lazio
compose VINCOLI_COMUNALI 12

# Regione 17 - Basilicata
compose VINCOLI_COMUNALI 17

# Regione 20 - Sardegna
compose VINCOLI_COMUNALI 20

echo ""
echo "=== RIEPILOGO ==="
echo "OK: $OK  FAIL: $FAIL  SKIP: $SKIP"
echo "Fine: $(date)"
