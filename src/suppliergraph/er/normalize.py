"""Company-name normalisation for entity resolution."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

# canonical legal-form tokens (matched after lower-casing/transliteration)
_FORM_CANON = {
    "gmbh": "gmbh", "mbh": "gmbh", "ag": "ag", "se": "se", "kg": "kg", "kgaa": "kgaa", "ug": "ug",
    "ohg": "ohg", "gbr": "gbr", "ev": "ev", "eg": "eg", "co": "co",
    "sa": "sa", "sas": "sas", "sarl": "sarl", "nv": "nv", "bv": "bv", "ltd": "ltd", "limited": "ltd",
    "llc": "llc", "inc": "inc", "corp": "corp", "plc": "plc", "spa": "spa", "srl": "srl", "oy": "oy",
    "ab": "ab", "as": "as", "aps": "aps", "oyj": "oyj", "sl": "sl", "zoo": "zoo", "sp": "sp",
}
_STOP = {"and", "und", "the", "der", "die", "das", "of", "de", "la", "le", "et"}
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class NormName:
    raw: str
    core: str                      # tokens without legal forms and stop words
    full: str                      # all tokens, normalised
    forms: frozenset[str]

    @property
    def text(self) -> str:
        return self.core or self.full


@lru_cache(maxsize=500_000)
def normalize_name(name: str) -> NormName:
    s = (name or "").translate(_UMLAUTS).lower().replace("&", " and ")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # keep dotted abbreviations together: "s.a." -> "sa", "e.v." -> "ev", "z o.o." handled below
    s = re.sub(r"\b([a-z])\.(?=[a-z]\b)", r"\1", s)
    s = s.replace(".", "")
    tokens = [t for t in _NON_ALNUM.split(s) if t]
    forms, core = set(), []
    for t in tokens:
        if t in _FORM_CANON and len(tokens) > 1:
            forms.add(_FORM_CANON[t])
        elif t in _STOP:
            continue
        else:
            core.append(t)
    return NormName(raw=name or "", core=" ".join(core), full=" ".join(tokens), forms=frozenset(forms))
