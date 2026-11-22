"""Entity-resolution evaluation without manual labelling.

Parties whose published identifier is an LEI (that exists in the loaded GLEIF data) carry their own
ground truth. We hide the identifier, match by name only, and compare with the published LEI.

Caveat (also in docs/evaluation.md): organisations that publish an LEI tend to be larger and have
cleaner names than the average supplier, so these numbers are an optimistic bound for the full
population. A manually labelled sample of identifier-less parties is the right complement.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..staging.db import read_sql
from .matcher import FEATURES, LogisticScorer, NameMatcher
from .resolve import MARGIN, build_gleif_matcher, decide


def labelled_parties(engine, lei_scheme: str) -> pd.DataFrame:
    df = read_sql(
        engine,
        "SELECT p.party_id, p.name, p.country, p.identifier AS true_lei FROM party p "
        "JOIN gleif_entity g ON g.lei = p.identifier WHERE p.scheme = :s",
        s=lei_scheme,
    )
    return df


def evaluate(engine, lei_scheme: str = "XI-LEI", thresholds=(0.70, 0.75, 0.80, 0.85, 0.88, 0.90, 0.95),
             matcher: NameMatcher | None = None) -> dict:
    gold = labelled_parties(engine, lei_scheme)
    if gold.empty:
        return {"n": 0, "note": "no parties with a published LEI found in the loaded GLEIF data"}
    matcher = matcher or build_gleif_matcher(engine)
    cands = matcher.candidates_batch(gold["name"].tolist(), gold["country"].tolist(), k=5)
    recall_at = {
        k: float(np.mean([g in {c.target_id for c in cs[:k]} for g, cs in zip(gold["true_lei"], cands)]))
        for k in (1, 3, 5)
    }
    curve = []
    for t in thresholds:
        tp = fp = fn = 0
        for g, cs in zip(gold["true_lei"], cands):
            d = decide(cs, accept=t, review=t, margin=MARGIN)
            if d.status == "accepted":
                tp += d.lei == g
                fp += d.lei != g
            else:
                fn += 1
        prec = tp / (tp + fp) if tp + fp else float("nan")
        rec = tp / len(gold)
        f1 = 2 * prec * rec / (prec + rec) if prec == prec and prec + rec else 0.0
        curve.append({"threshold": t, "precision": prec, "recall": rec, "f1": f1, "accepted": int(tp + fp)})
    return {"n": len(gold), "candidate_recall_at_k": recall_at, "curve": curve,
            "note": "identifier-masked evaluation; optimistic for identifier-less parties"}


def train_scorer(engine, lei_scheme: str = "XI-LEI", seed: int = 0) -> LogisticScorer | None:
    """Fit a logistic scorer on identifier-masked pairs (true match = 1, other candidates = 0)."""
    gold = labelled_parties(engine, lei_scheme)
    if len(gold) < 20:
        return None
    matcher = build_gleif_matcher(engine)
    cands = matcher.candidates_batch(gold["name"].tolist(), gold["country"].tolist(), k=8)
    X, y = [], []
    for g, cs in zip(gold["true_lei"], cands):
        for c in cs:
            X.append(c.features)
            y.append(int(c.target_id == g))
    X, y = np.array(X), np.array(y)
    if y.sum() < 5 or (1 - y).sum() < 5:
        return None
    assert X.shape[1] == len(FEATURES)
    return LogisticScorer.fit(X, y)
