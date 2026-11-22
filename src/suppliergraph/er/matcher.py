"""Blocking + scoring for name-based entity matching.

Blocking: character-n-gram TF-IDF cosine nearest neighbours inside a country bucket.
Scoring: a handful of string-similarity features combined by a heuristic scorer or by a
logistic-regression scorer trained on labelled pairs (see evaluate.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler
from sklearn.feature_extraction.text import TfidfVectorizer

from .normalize import NormName, normalize_name

FEATURES = ["cos", "wratio", "jw", "token_set", "ratio", "form", "country"]


def pair_features(q: NormName, t: NormName, q_country: str | None, t_countries: set[str], cos: float) -> list[float]:
    a, b = q.text, t.text
    if q.forms and t.forms:
        form = 1.0 if q.forms & t.forms else -1.0
    else:
        form = 0.0
    if not q_country or not t_countries:
        country = 0.0
    else:
        country = 1.0 if q_country in t_countries else -1.0
    return [
        float(cos),
        fuzz.WRatio(a, b) / 100.0,
        JaroWinkler.similarity(a, b),
        fuzz.token_set_ratio(a, b) / 100.0,
        fuzz.ratio(a, b) / 100.0,
        form,
        country,
    ]


class Scorer(Protocol):
    def score(self, feats: list[float]) -> float: ...


class HeuristicScorer:
    """Transparent default: weighted similarity with small legal-form and country adjustments."""

    W = {"cos": 0.30, "wratio": 0.20, "jw": 0.15, "token_set": 0.15, "ratio": 0.20}

    def score(self, feats: list[float]) -> float:
        f = dict(zip(FEATURES, feats))
        s = sum(self.W[k] * f[k] for k in self.W)
        if f["form"] < 0:
            s -= 0.05
        elif f["form"] > 0:
            s += 0.02
        if f["country"] < 0:
            s -= 0.10
        elif f["country"] > 0:
            s += 0.02
        return float(min(1.0, max(0.0, s)))


@dataclass
class LogisticScorer:
    coef: list[float]
    intercept: float

    def score(self, feats: list[float]) -> float:
        z = float(np.dot(self.coef, feats) + self.intercept)
        return 1.0 / (1.0 + np.exp(-z))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"features": FEATURES, "coef": self.coef, "intercept": self.intercept}))

    @classmethod
    def load(cls, path: Path) -> LogisticScorer:
        d = json.loads(path.read_text())
        return cls(d["coef"], d["intercept"])

    @classmethod
    def fit(cls, X: np.ndarray, y: np.ndarray) -> LogisticScorer:
        from sklearn.linear_model import LogisticRegression

        m = LogisticRegression(max_iter=1000, class_weight="balanced").fit(X, y)
        return cls(m.coef_[0].tolist(), float(m.intercept_[0]))


@dataclass
class Candidate:
    target_id: str
    target_name: str
    score: float
    cos: float
    features: list[float] = field(default_factory=list)


class NameMatcher:
    """Index of target names (e.g. GLEIF legal names or sanction names/aliases)."""

    def __init__(self, ids: list[str], names: list[str], countries: list[set[str]] | None = None,
                 scorer: Scorer | None = None):
        self.ids, self.names = list(ids), list(names)
        self.countries = countries or [set() for _ in ids]
        self.norm = [normalize_name(n) for n in self.names]
        self.scorer = scorer or HeuristicScorer()
        # Very large indexes: drop n-grams present in >1% of names (legal-form fragments), otherwise Q @ T.T becomes near-dense.
        max_df = 0.01 if len(self.ids) > 50_000 else 1.0
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), sublinear_tf=True, dtype=np.float32, max_df=max_df)
        self.T = self.vec.fit_transform([n.text for n in self.norm]) if self.ids else None
        self._by_country: dict[str, list[int]] = {}
        self._unknown: list[int] = []
        for i, cs in enumerate(self.countries):
            if not cs:
                self._unknown.append(i)
            for c in cs:
                self._by_country.setdefault(c, []).append(i)

    def _bucket(self, country: str | None) -> np.ndarray:
        if not country:
            return np.arange(len(self.ids))
        idx = self._by_country.get(country, []) + self._unknown
        return np.array(sorted(set(idx)), dtype=np.int64)

    def candidates_batch(self, names: list[str], countries: list[str | None], k: int = 5,
                         chunk: int = 2000) -> list[list[Candidate]]:
        out: list[list[Candidate]] = [[] for _ in names]
        if not self.ids:
            return out
        groups: dict[str | None, list[int]] = {}
        for i, c in enumerate(countries):
            groups.setdefault(c, []).append(i)
        for country, qidx in groups.items():
            bucket = self._bucket(country)
            if len(bucket) == 0:
                continue
            Tsub = self.T[bucket]
            step = 200 if len(bucket) > 50_000 else chunk
            for s in range(0, len(qidx), step):
                part = qidx[s: s + step]
                norms = [normalize_name(names[i]) for i in part]
                Q = self.vec.transform([n.text for n in norms])
                S = (Q @ Tsub.T).tocsr()
                for row, qi in enumerate(part):
                    lo, hi = S.indptr[row], S.indptr[row + 1]
                    data, cols = S.data[lo:hi], S.indices[lo:hi]
                    if len(data) == 0:
                        continue
                    if len(data) > k * 3:
                        sel = np.argpartition(-data, k * 3)[: k * 3]
                        data, cols = data[sel], cols[sel]
                    cands = []
                    for cos, col in zip(data, cols):
                        ti = int(bucket[col])
                        feats = pair_features(norms[row], self.norm[ti], country, self.countries[ti], float(cos))
                        cands.append(Candidate(self.ids[ti], self.names[ti], self.scorer.score(feats), float(cos), feats))
                    cands.sort(key=lambda c: -c.score)
                    out[qi] = cands[:k]
        return out

    def best(self, name: str, country: str | None = None, k: int = 5) -> list[Candidate]:
        return self.candidates_batch([name], [country], k=k)[0]
