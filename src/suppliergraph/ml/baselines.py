"""Non-graph baselines the embedding models must beat to justify their complexity."""
from __future__ import annotations

import numpy as np

from .dataset import R_PROCURES, R_SUPPLIES, LPDataset


class _Base:
    name = "base"

    def __init__(self, ds: LPDataset):
        self.ds = ds
        pool = ds.supplier_pool
        self.pool = pool
        self.index = {int(s): i for i, s in enumerate(pool)}
        n = len(pool)
        self.pop = np.zeros(n)
        self.hist: dict[int, np.ndarray] = {}
        r = ds.rel_id
        for h, rel, t in ds.train:
            if rel == r("contractedWith") and int(t) in self.index:
                self.pop[self.index[int(t)]] += 1
                self.hist.setdefault(int(h), np.zeros(n))[self.index[int(t)]] += 1
        # category profiles from train awards only
        self.sup_cat: dict[int, dict[int, float]] = {}
        self.buy_cat: dict[int, dict[int, float]] = {}
        for h, rel, t in ds.train:
            if rel == r(R_SUPPLIES):
                self.sup_cat.setdefault(int(h), {})[int(t)] = 1.0
            elif rel == r(R_PROCURES):
                self.buy_cat.setdefault(int(h), {})[int(t)] = 1.0

    def scores(self, buyer: int) -> np.ndarray:        # higher = better, aligned with self.pool
        raise NotImplementedError


class Popularity(_Base):
    name = "popularity"

    def scores(self, buyer):
        return self.pop.copy()


class BuyerHistory(_Base):
    """Repeat business: suppliers the buyer already used, most frequent first (popularity breaks ties)."""
    name = "buyer_history"

    def scores(self, buyer):
        h = self.hist.get(buyer, np.zeros(len(self.pool)))
        return h * 1e3 + self.pop * 1e-3


class CategoryOverlap(_Base):
    """Suppliers active in categories the buyer procures (no repeat-business signal)."""
    name = "category_overlap"

    def scores(self, buyer):
        cats = self.buy_cat.get(buyer, {})
        out = np.zeros(len(self.pool))
        for s, i in self.index.items():
            sc = self.sup_cat.get(s, {})
            out[i] = len(set(cats) & set(sc))
        return out + self.pop * 1e-3


class HistoryThenCategory(_Base):
    name = "history_then_category"

    def scores(self, buyer):
        h = self.hist.get(buyer, np.zeros(len(self.pool)))
        cat = CategoryOverlap.scores(self, buyer)
        return h * 1e3 + cat


BASELINES = [Popularity, BuyerHistory, CategoryOverlap, HistoryThenCategory]
