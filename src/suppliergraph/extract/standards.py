"""Pattern-based extraction of required standards/certifications from tender text (rule-based NER)."""
from __future__ import annotations

import re

import pandas as pd
from sqlalchemy import text

from ..staging.db import read_sql, replace_table

_PATTERNS = [
    re.compile(r"\bISO(?:/IEC)?\s?\d{3,6}(?:[:\-]\d{1,4})?\b"),
    re.compile(r"\bDIN(?:\s?EN)?(?:\s?ISO)?\s?\d{2,6}(?:[:\-]\d{1,4})?\b"),
    re.compile(r"\bEN\s?\d{3,6}(?:[:\-]\d{1,4})?\b"),
    re.compile(r"\bEMAS\b"),
    re.compile(r"\bSA\s?8000\b"),
]


def normalize_standard(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip())
    return re.sub(r"^(ISO|DIN|EN)(?=\d)", r"\1 ", s)


def extract_standards(text_: str) -> list[tuple[str, str]]:
    """Return (normalised standard, matched span)."""
    out: dict[str, str] = {}
    for pat in _PATTERNS:
        for m in pat.finditer(text_ or ""):
            out.setdefault(normalize_standard(m.group(0)), m.group(0))
    return list(out.items())


def extract_all(engine) -> int:
    tenders = read_sql(engine, "SELECT tender_id, title, description FROM tender")
    rows = []
    for t in tenders.itertuples(index=False):
        for std, span in extract_standards(f"{t.title or ''}. {t.description or ''}"):
            rows.append({"tender_id": t.tender_id, "standard": std, "span": span, "method": "regex"})
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tender_requirement"))
    return replace_table(engine, "tender_requirement", pd.DataFrame(rows), truncate=False) if rows else 0
