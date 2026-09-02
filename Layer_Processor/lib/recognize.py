"""Matcher: formulazione layer → classe canonica.

Legge registry/layer_dictionary.yaml + registry/canonical_taxonomy.yaml e classifica
un layer in ingresso descritto da (title, topic). Restituisce la classe canonica con
confidence e MOTIVO (tracciabilità), oppure una lista di PROPOSTE se nessuna regola
scatta. Non decide da solo: propone. La governance (estensione del dizionario) resta umana.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .normalize import norm_match, tokens

CONF_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}
REGISTRY = Path(__file__).resolve().parents[1] / "registry"

_TOPIC_ALIASES: dict[str, str] = {
    "INFORMAZIONI GEOSCIENTIFICHE": "geoscientificInformation",
    "ACQUE INTERNE": "inlandWaters",
    "ACQUE MARINE": "oceans",
    "AMBIENTE": "environment",
    "BIOLOGIA": "biota",
    "ECONOMIA": "economy",
    "PIANIFICAZIONE DEL TERRITORIO E CATASTO": "planningCadastre",
    "RETI, INFRASTRUTTURE E SERVIZI DI COMUNICAZIONE": "utilitiesCommunication",
    "SALUTE": "health",
    "SOCIETA": "society",
    "STRUTTURE": "structure",
    "TRASPORTO": "transportation",
    "AGRICOLTURA": "farming",
    "PIANO PAESAGGISTICO REGIONALE": "planningCadastre",
}

# stopword italiane: escluse dall'overlap delle proposte (rumore su 'di','del','e',...)
STOP = {"di", "del", "della", "dei", "delle", "degli", "e", "a", "al", "alla", "ai",
        "il", "la", "lo", "le", "i", "gli", "un", "una", "con", "per", "su", "da",
        "in", "the", "of", "tav", "p1", "p2", "p3", "p4", "p5", "p6", "n", "l"}


@dataclass
class Match:
    canonical: str | None
    confidence: str | None
    score: float
    matched: list[str] = field(default_factory=list)
    reason: str = ""
    proposals: list[dict] = field(default_factory=list)

    @property
    def recognized(self) -> bool:
        return self.canonical is not None


class Recognizer:
    def __init__(self, registry_dir: Path = REGISTRY):
        self.taxonomy = yaml.safe_load((registry_dir / "canonical_taxonomy.yaml").read_text("utf-8"))
        self.dictionary = yaml.safe_load((registry_dir / "layer_dictionary.yaml").read_text("utf-8"))
        self.rules = self.dictionary.get("rules", [])
        self.classes = self.taxonomy.get("classes", {})
        self._validate()
        # indice keyword→classi per le proposte
        self._class_keywords: dict[str, set[str]] = collections.defaultdict(set)
        for rule in self.rules:
            c = rule["canonical"]
            for kw in rule.get("any", []) + rule.get("all", []):
                self._class_keywords[c].update(tokens(kw))
        for key, meta in self.classes.items():
            self._class_keywords[key].update(tokens(meta.get("description", "")))

    def _validate(self) -> None:
        """Guard-rail: ogni regola punta a una classe esistente."""
        unknown = sorted({r["canonical"] for r in self.rules if r["canonical"] not in self.classes})
        if unknown:
            raise ValueError(f"layer_dictionary.yaml: classi canoniche inesistenti: {unknown}")

    # -- matching ----------------------------------------------------------
    def match(self, title: str, topic: str | None = None) -> Match:
        nt = f" {norm_match(title)} "
        topic = _TOPIC_ALIASES.get((topic or "").strip(), (topic or "").strip())
        best: Match | None = None
        for rule in self.rules:
            topics = rule.get("topic_in")
            if topics and topic and topic not in topics:
                continue  # gate di categoria (solo se il topic è noto)
            if any(f" {norm_match(k)} " in nt or norm_match(k) in nt for k in rule.get("not_any", [])):
                continue
            need_all = [k for k in rule.get("all", [])]
            if need_all and not all(norm_match(k) in nt for k in need_all):
                continue
            hits = [k for k in rule.get("any", []) if norm_match(k) in nt]
            if not rule.get("any"):
                hits = need_all  # regola basata solo su 'all'
            elif not hits:
                continue
            conf = rule.get("confidence", "low")
            # punteggio: confidence * (specificità: lunghezza keyword + bonus topic/all)
            spec = max((len(norm_match(k)) for k in hits + need_all), default=1)
            score = CONF_WEIGHT.get(conf, 1.0) * spec
            if topics and topic and topic in topics:
                score += 5
            if need_all:
                score += 3
            if best is None or score > best.score:
                reason = f"keyword {hits + need_all}"
                if topics and topic in (topics or []):
                    reason += f" · topic={topic}"
                best = Match(rule["canonical"], conf, score, hits + need_all, reason)
        if best:
            return best
        return Match(None, None, 0.0, reason="nessuna regola", proposals=self._propose(title, topic))

    def _propose(self, title: str, topic: str | None) -> list[dict]:
        """Top-3 classi candidate per overlap di token + affinità di topic."""
        tset = set(tokens(title)) - STOP
        scored = []
        for key, kws in self._class_keywords.items():
            overlap = (tset & kws) - STOP
            if not overlap:
                continue
            s = len(overlap)
            if topic and topic in (self.classes.get(key, {}).get("topics") or []):
                s += 2
            scored.append({"canonical": key, "score": s, "shared": sorted(overlap)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:3]
