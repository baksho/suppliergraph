"""Mechanics test for the link-prediction code on a SYNTHETIC graph with planted structure.

This checks that the implementation can learn a signal that exists (ownership groups decide which
buyers buy from which suppliers). It says nothing about performance on real procurement data.
"""
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from suppliergraph.ml.dataset import Ablation, build_dataset
from suppliergraph.ml.train import run_experiment


def synthetic(seed=0):
    rng = np.random.default_rng(seed)
    n_groups, per_group, n_buyers = 10, 12, 6
    groups = [f"urn:g{g}" for g in range(n_groups)]
    sups = [(f"urn:s{g}_{i}", groups[g]) for g in range(n_groups) for i in range(per_group)]
    prefs = {b: rng.choice(n_groups, 3, replace=False) for b in range(n_buyers)}
    awards = []
    for k in range(260):
        b = int(rng.integers(n_buyers))
        g = int(rng.choice(prefs[b]))
        s, _ = sups[g * per_group + int(rng.integers(per_group))]
        awards.append({"award": f"a{k}", "buyer": f"urn:b{b}", "supplier": s,
                       "date": f"{2020 + k // 52}-{(k % 12) + 1:02d}-{(k % 27) + 1:02d}", "cat": None})
    parents = [(s, g) for s, g in sups]
    return awards, parents


@pytest.mark.parametrize("model", ["transe", "rotate"])
def test_model_learns_planted_ownership_signal(model):
    awards, parents = synthetic()
    ds = build_dataset(awards, parents)
    res = run_experiment(ds=ds, model_name=model, dim=32, epochs=120, lr=5e-3, seed=1)
    m = res["test"][model]["new_pairs"]
    pop = res["test"]["popularity"]["new_pairs"]
    assert m["n"] >= 8
    n_pool = len(ds.supplier_pool)
    assert m["mrr"] > 3 * (1 / n_pool * np.log(n_pool))      # far above random ranking
    assert m["mrr"] > pop["mrr"]
    # ablation changes the graph: without ownership edges the signal disappears
    ds2 = build_dataset(awards, parents, ablation=Ablation(ownership=False))
    assert len(ds2.train) < len(ds.train)


def test_temporal_split_has_no_leakage():
    awards, parents = synthetic()
    ds = build_dataset(awards, parents)
    t1, t2 = ds.split_dates
    assert t1 < t2
    # every train contractedWith edge must come from an award dated <= t1
    train_pairs = {(ds.entities[b], ds.entities[s]) for b, s in ds.train_pairs}
    early = {(a["buyer"], a["supplier"]) for a in awards if a["date"] <= t1}
    assert train_pairs == early
    assert ds.meta["n_test"] > 0 and ds.meta["n_valid"] > 0
