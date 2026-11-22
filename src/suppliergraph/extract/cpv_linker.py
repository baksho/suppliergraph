"""Entity linking of tender text to CPV categories (TF-IDF retrieval over multilingual CPV labels).

This is a deliberately transparent baseline: character n-grams cope with German compounds
("Bueromoebel" ~ "Moebel"). A multilingual embedding model can be plugged in through the same
`link()` interface; evaluate it with `evaluate_linker` before trusting it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from ..er.normalize import normalize_name
from ..staging.db import read_sql, replace_table


def _prep(text: str) -> str:
    return normalize_name(text or "").full


@dataclass
class CpvHit:
    code: str
    score: float
    label: str


class CpvLinker:
    def __init__(self, codes: pd.DataFrame, min_depth_digits: int = 3):
        """codes: columns code, label_en, label_de. Division-level codes are kept (they are real CPV)."""
        self.codes = codes.reset_index(drop=True)
        self.docs = [
            _prep(f"{r.label_en or ''} {r.label_de or ''}") for r in self.codes.itertuples(index=False)
        ]
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, dtype=np.float32)
        self.M = self.vec.fit_transform(self.docs)

    def link(self, text: str, k: int = 3, threshold: float = 0.20) -> list[CpvHit]:
        q = self.vec.transform([_prep(text)])
        sims = (q @ self.M.T).toarray()[0]
        order = np.argsort(-sims)[:k]
        return [
            CpvHit(self.codes.code[i], float(sims[i]), self.codes.label_en[i] or "")
            for i in order if sims[i] >= threshold
        ]


def load_linker(engine) -> CpvLinker:
    return CpvLinker(read_sql(engine, "SELECT code, label_en, label_de FROM cpv_code"))


def link_tenders(engine, k: int = 2, threshold: float = 0.20) -> int:
    """Predict CPV links for tenders that have no declared category; stored with source='linked'."""
    linker = load_linker(engine)
    tenders = read_sql(
        engine,
        "SELECT t.tender_id, t.title, t.description FROM tender t "
        "WHERE t.tender_id NOT IN (SELECT tender_id FROM tender_cpv WHERE source = 'declared')",
    )
    rows = []
    for t in tenders.itertuples(index=False):
        for h in linker.link(f"{t.title or ''}. {t.description or ''}", k=k, threshold=threshold):
            rows.append({"tender_id": t.tender_id, "cpv_code": h.code, "source": "linked", "score": round(h.score, 4)})
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tender_cpv WHERE source = 'linked'"))
    return replace_table(engine, "tender_cpv", pd.DataFrame(rows), truncate=False) if rows else 0


def evaluate_linker(engine, k: int = 3, threshold: float = 0.0, level: int = 3) -> dict:
    """Hide declared CPV codes, predict from text, score at CPV-prefix level (default: 3-digit group)."""
    linker = load_linker(engine)
    gold = read_sql(
        engine,
        "SELECT t.tender_id, t.title, t.description, c.cpv_code FROM tender t "
        "JOIN tender_cpv c ON c.tender_id = t.tender_id AND c.source = 'declared'",
    )
    if gold.empty:
        return {"n": 0}
    by_tender = gold.groupby("tender_id").agg(
        text=("title", lambda s: s.iloc[0] or ""), desc=("description", lambda s: s.iloc[0] or ""),
        codes=("cpv_code", lambda s: {c[:level] for c in s}),
    )
    top1 = topk = 0
    for r in by_tender.itertuples():
        hits = linker.link(f"{r.text}. {r.desc}", k=k, threshold=threshold)
        pred = [h.code[:level] for h in hits]
        top1 += bool(pred) and pred[0] in r.codes
        topk += any(p in r.codes for p in pred)
    n = len(by_tender)
    return {"n": n, "level_digits": level, "top1": top1 / n, f"top{k}": topk / n}
