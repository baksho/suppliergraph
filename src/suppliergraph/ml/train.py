"""Training, filtered ranking evaluation and experiment runner for link prediction."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .baselines import BASELINES
from .dataset import Ablation, LPDataset, load_from_store
from .models import make_model


def _neg_pools(ds: LPDataset):
    """Type-constrained negative sampling: corrupt with entities seen in the same relation slot."""
    heads, tails = {}, {}
    for h, r, t in ds.train:
        heads.setdefault(int(r), set()).add(int(h))
        tails.setdefault(int(r), set()).add(int(t))
    return ({r: np.array(sorted(v)) for r, v in heads.items()}, {r: np.array(sorted(v)) for r, v in tails.items()})


def train(ds: LPDataset, model_name: str = "rotate", dim: int = 64, epochs: int = 200, batch: int = 512,
          n_neg: int = 16, lr: float = 1e-3, gamma: float = 4.0, adv_temp: float = 1.0, seed: int = 0,
          verbose: bool = False, device: str = "cpu"):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = make_model(model_name, ds.n_entities, ds.n_relations, dim, gamma).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    data = ds.train
    head_pool, tail_pool = _neg_pools(ds)
    n = len(data)
    for ep in range(epochs):
        perm = rng.permutation(n)
        total = 0.0
        for s in range(0, n, batch):
            idx = perm[s: s + batch]
            pos = data[idx]
            B = len(pos)
            h, r, t = (torch.as_tensor(pos[:, i], device=device) for i in range(3))
            # negatives: corrupt tail or head with equal probability, from the relation's own pool
            corrupt_tail = rng.random(B) < 0.5
            neg_h = np.repeat(pos[:, 0][:, None], n_neg, axis=1)
            neg_t = np.repeat(pos[:, 2][:, None], n_neg, axis=1)
            for i in range(B):
                rel = int(pos[i, 1])
                if corrupt_tail[i]:
                    neg_t[i] = rng.choice(tail_pool[rel], n_neg)
                else:
                    neg_h[i] = rng.choice(head_pool[rel], n_neg)
            nh = torch.as_tensor(neg_h, device=device)
            nt = torch.as_tensor(neg_t, device=device)
            rr = r.unsqueeze(1).expand(-1, n_neg)
            d_pos = model.dist(h, r, t)
            d_neg = model.dist(nh, rr, nt)                       # (B, n_neg)
            w = torch.softmax(-d_neg * adv_temp, dim=1).detach()   # self-adversarial weights
            loss = -nn.functional.logsigmoid(gamma - d_pos).mean() \
                   - (w * nn.functional.logsigmoid(d_neg - gamma)).sum(dim=1).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            model.normalize()
            total += float(loss) * B
        if verbose and (ep % max(1, epochs // 10) == 0 or ep == epochs - 1):
            print(f"epoch {ep:4d} loss {total / n:.4f}")
    model.eval()
    return model


class ModelScorer:
    """Adapter: scores for all pool suppliers given a buyer (higher = better)."""

    def __init__(self, model, ds: LPDataset, name: str):
        self.model, self.ds, self.name = model, ds, name
        self.r = ds.rel_id("contractedWith")
        self.pool = torch.as_tensor(ds.supplier_pool)

    @torch.no_grad()
    def scores(self, buyer: int) -> np.ndarray:
        d = self.model.dist_all_tails(torch.tensor([buyer]), torch.tensor([self.r]))[0]
        return (-d[self.pool]).numpy()


def evaluate(scorer, ds: LPDataset, split: str = "test") -> dict:
    pairs = ds.test_pairs if split == "test" else ds.valid_pairs
    index = {int(s): i for i, s in enumerate(ds.supplier_pool)}
    rows = []
    seen_buyer_sup: set[tuple[int, int]] = set()
    for b, s, _ in pairs:
        if (b, s) in seen_buyer_sup:
            continue
        seen_buyer_sup.add((b, s))
        sc = scorer.scores(b).astype(np.float64)
        target = sc[index[s]]
        mask = np.ones(len(sc), dtype=bool)
        for other in ds.all_true.get(b, ()):
            if other != s and other in index:
                mask[index[other]] = False        # filtered protocol
        mask[index[s]] = False
        greater = float((sc[mask] > target).sum())
        equal = float((sc[mask] == target).sum())
        rank = 1.0 + greater + 0.5 * equal
        rows.append({"rank": rank, "new": (b, s) not in ds.train_pairs, "seen": s in ds.train_supplier_set})

    def agg(sel):
        r = np.array([x["rank"] for x in sel]) if sel else np.array([])
        if len(r) == 0:
            return {"n": 0}
        return {"n": len(r), "mrr": float((1 / r).mean()), "hits@1": float((r <= 1).mean()),
                "hits@3": float((r <= 3).mean()), "hits@10": float((r <= 10).mean())}

    return {
        "all": agg(rows),
        "new_pairs": agg([x for x in rows if x["new"]]),
        "repeat_pairs": agg([x for x in rows if not x["new"]]),
        "new_pairs_seen_supplier": agg([x for x in rows if x["new"] and x["seen"]]),
        "cold_start_supplier": agg([x for x in rows if not x["seen"]]),
    }


def run_experiment(store=None, ds: LPDataset | None = None, model_name: str = "rotate", ablation: Ablation | None = None,
                   out_dir: Path | None = None, seed: int = 0, **train_kw) -> dict:
    ds = ds or load_from_store(store, ablation)
    t0 = time.time()
    model = train(ds, model_name, seed=seed, **train_kw)
    result = {
        "dataset": ds.meta | {"split_dates": list(ds.split_dates), "n_entities": ds.n_entities,
                              "n_train_triples": len(ds.train), "n_suppliers": len(ds.supplier_pool)},
        "model": {"name": model_name, "seed": seed, **{k: v for k, v in train_kw.items()}},
        "valid": {model_name: evaluate(ModelScorer(model, ds, model_name), ds, "valid")},
        "test": {model_name: evaluate(ModelScorer(model, ds, model_name), ds, "test")},
        "train_seconds": round(time.time() - t0, 1),
    }
    for B in BASELINES:
        b = B(ds)
        result["valid"][b.name] = evaluate(b, ds, "valid")
        result["test"][b.name] = evaluate(b, ds, "test")
    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        torch.save({"state": model.state_dict(), "name": model_name, "dim": train_kw.get("dim", 64),
                    "gamma": train_kw.get("gamma", 4.0)}, out_dir / "model.pt")
        (out_dir / "vocab.json").write_text(json.dumps({"entities": ds.entities, "relations": ds.relations,
                                                         "supplier_pool": ds.supplier_pool.tolist()}))
        (out_dir / "metrics.json").write_text(json.dumps(result, indent=2))
    return result


def train_final(store, model_name: str = "rotate", out_dir: Path | None = None, **train_kw) -> dict:
    """Retrain on ALL awards for serving (no held-out data; use run_experiment for honest metrics)."""
    ds = load_from_store(store, fractions=None)
    model = train(ds, model_name, **train_kw)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"state": model.state_dict(), "name": model_name, "dim": train_kw.get("dim", 64),
                "gamma": train_kw.get("gamma", 4.0)}, out_dir / "model.pt")
    (out_dir / "vocab.json").write_text(json.dumps({"entities": ds.entities, "relations": ds.relations,
                                                     "supplier_pool": ds.supplier_pool.tolist()}))
    return {"entities": ds.n_entities, "train_triples": len(ds.train), "model": model_name}
