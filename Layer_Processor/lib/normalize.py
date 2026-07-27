"""Normalizzazione testuale.

Due normalizzatori distinti, per non confonderli:

- ``norm_name``  : per i NOMI COMUNE. Identico a pipeline/aliases/NORMALIZATION_RULES.md
  (apostrofi → ', niente accenti, spazi collassati, UPPER, apostrofi conservati).
  Da usare per abbinare i comuni al codice_istat via gli alias esistenti.

- ``norm_match`` : per i TITOLI DEI LAYER. Minuscolo, senza accenti, ogni sequenza
  non-alfanumerica → spazio singolo. Produce la forma su cui il dizionario
  fa il match per keyword (keyword scritte già in questa forma).
"""
from __future__ import annotations

import re
import unicodedata

__all__ = ["norm_name", "norm_match", "tokens", "strip_accents"]


def strip_accents(value: str) -> str:
    value = unicodedata.normalize("NFD", value)
    return "".join(c for c in value if unicodedata.category(c) != "Mn")


def norm_name(value: str | None) -> str:
    """Canonico per i nomi comune (vedi NORMALIZATION_RULES.md §1)."""
    value = (value or "").replace("’", "'").replace("`", "'").replace("´", "'")
    value = strip_accents(value)
    return re.sub(r"\s+", " ", value).strip().upper()


def norm_match(value: str | None) -> str:
    """Forma di matching per i titoli layer: minuscolo, senza accenti,
    non-alfanumerici → spazio singolo. Gli apostrofi diventano spazio
    (``corsi d'acqua`` → ``corsi d acqua``): le keyword del dizionario
    vanno scritte di conseguenza."""
    value = strip_accents((value or "").lower())
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(value: str | None) -> list[str]:
    """Token alfanumerici della forma di matching (per overlap/proposte)."""
    return [t for t in norm_match(value).split(" ") if t]
