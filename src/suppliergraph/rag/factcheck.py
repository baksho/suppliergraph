"""Deterministic grounding checks for generated answers.

What this catches: invalid citations, uncited sentences, numbers that are not in the evidence, and
mentions of *known* graph entities that are not in the evidence (e.g. a plausible but wrong supplier).
What it does NOT catch: invented organisations that are not in the graph, or a correct number
attached to the wrong claim. It is a floor for hallucination control, not a proof of correctness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..er.normalize import normalize_name
from ..namespaces import SPARQL_PREFIX_BLOCK
from ..store.base import SparqlStore

_CITE = re.compile(r"\[([RFD]\d+)\]")
_NUM = re.compile(r"(?<![\w.])\d[\d.,]*\d|\d")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[])")


@dataclass
class GroundingReport:
    citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    uncited_sentences: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)
    unsupported_entities: list[str] = field(default_factory=list)
    n_sentences: int = 0

    @property
    def citation_coverage(self) -> float:
        return 1.0 if self.n_sentences == 0 else 1 - len(self.uncited_sentences) / self.n_sentences

    @property
    def grounded(self) -> bool:
        return not (self.invalid_citations or self.unsupported_numbers or self.unsupported_entities)

    def as_dict(self) -> dict:
        return {
            "grounded": self.grounded, "citations": self.citations, "invalid_citations": self.invalid_citations,
            "uncited_sentences": self.uncited_sentences, "unsupported_numbers": self.unsupported_numbers,
            "unsupported_entities": self.unsupported_entities, "citation_coverage": round(self.citation_coverage, 3),
        }


def _canon_number(s: str) -> str | None:
    s = s.strip(".,")
    if not s:
        return None
    if "," in s and "." in s:                 # 1,234.56 or 1.234,56
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif "," in s:
        s = s.replace(",", ".") if re.fullmatch(r"\d+,\d{1,2}", s) else s.replace(",", "")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return f"{v:.2f}".rstrip("0").rstrip(".")


def numbers_in(text: str) -> set[str]:
    return {c for m in _NUM.findall(text) if (c := _canon_number(m)) is not None}


class LabelIndex:
    """Normalised names of all entities in the graph, for detecting mentions in answers."""

    def __init__(self, names: list[str], min_len: int = 4):
        self.names = {normalize_name(n).core: n for n in names if n and len(normalize_name(n).core) >= min_len}

    @classmethod
    def from_store(cls, store: SparqlStore) -> LabelIndex:
        rows = store.select(SPARQL_PREFIX_BLOCK + """
            SELECT DISTINCT ?n WHERE { ?e a sg:LegalEntity . { ?e sg:legalName ?n } UNION { ?e sg:recordedName ?n } }""")
        return cls([str(r["n"]) for r in rows])

    def mentions(self, text: str) -> set[str]:
        hay = " " + normalize_name(text).full + " "
        return {orig for core, orig in self.names.items() if f" {core} " in hay}


def check(answer: str, evidence: dict[str, str], labels: LabelIndex | None = None) -> GroundingReport:
    """evidence: id (R1/F2/D3) -> text shown to the model."""
    rep = GroundingReport()
    sentences = [s for s in _SENT.split(answer.strip()) if s.strip()]
    rep.n_sentences = len(sentences)
    for s in sentences:
        cites = _CITE.findall(s)
        rep.citations += cites
        if not cites:
            rep.uncited_sentences.append(s.strip())
    rep.citations = list(dict.fromkeys(rep.citations))
    rep.invalid_citations = [c for c in rep.citations if c not in evidence]
    body = _CITE.sub("", answer)
    ev_text = "\n".join(evidence.values())
    ev_numbers = numbers_in(ev_text)
    rep.unsupported_numbers = sorted(n for n in numbers_in(body) if n not in ev_numbers)
    if labels is not None:
        ev_norm = " " + normalize_name(ev_text).full + " "
        rep.unsupported_entities = sorted(
            m for m in labels.mentions(body) if f" {normalize_name(m).core} " not in ev_norm
        )
    return rep
