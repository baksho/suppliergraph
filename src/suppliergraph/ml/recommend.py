"""Supplier recommendation for the 'Discover' tab: embedding model when available, transparent baseline otherwise.

Scores are *ranking signals*, not probabilities, and the evidence listed next to each candidate is
the graph context that makes the suggestion plausible. It is NOT a causal attribution of the model's score.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ..namespaces import SPARQL_PREFIX_BLOCK
from ..store.base import SparqlStore

Q_AWARDS = SPARQL_PREFIX_BLOCK + """
SELECT ?buyer ?supplier ?cat WHERE {
  ?a sg:awardOf ?t ; sg:awardedTo ?supplier . ?t sg:issuedBy ?buyer .
  OPTIONAL { ?t sg:hasCategory ?cat } }"""
Q_NAMES = SPARQL_PREFIX_BLOCK + "SELECT ?e ?name ?cc WHERE { ?e sg:legalName ?name . OPTIONAL { ?e sg:registeredIn/sg:isoCode ?cc } }"
Q_GROUP = SPARQL_PREFIX_BLOCK + "SELECT ?e ?top WHERE { ?e sg:derivedUltimateParent ?top }"
Q_CATS = SPARQL_PREFIX_BLOCK + """
SELECT ?c ?label ?code ?parent WHERE { ?c skos:notation ?code . OPTIONAL { ?c skos:prefLabel ?label . FILTER(LANG(?label)="en") }
  OPTIONAL { ?c skos:broader ?parent } }"""


class Recommender:
    def __init__(self, store: SparqlStore, artifact_dir: Path | None = None):
        self.names, self.country = {}, {}
        for r in store.select(Q_NAMES):
            self.names.setdefault(str(r["e"]), r["name"])
            self.country[str(r["e"])] = r["cc"]
        self.cat_label, self.cat_code, self.cat_parent = {}, {}, {}
        for r in store.select(Q_CATS):
            c = str(r["c"])
            self.cat_label[c] = r["label"] or r["code"]
            self.cat_code[c] = r["code"]
            if r["parent"]:
                self.cat_parent[c] = str(r["parent"])
        self.group = {str(r["e"]): str(r["top"]) for r in store.select(Q_GROUP)}
        self.hist: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.sup_cats: dict[str, set[str]] = defaultdict(set)
        self.buy_cats: dict[str, set[str]] = defaultdict(set)
        self.pop: dict[str, int] = defaultdict(int)
        for r in store.select(Q_AWARDS):
            b, s = str(r["buyer"]), str(r["supplier"])
            self.hist[b][s] += 1
            self.pop[s] += 1
            if r["cat"]:
                self.sup_cats[s].add(str(r["cat"]))
                self.buy_cats[b].add(str(r["cat"]))
        self.suppliers = sorted(self.pop)
        self.model = None
        self.ent_id: dict[str, int] = {}
        self._load_model(artifact_dir)

    # -- model ------------------------------------------------------------------------------
    def _load_model(self, d: Path | None):
        if not d or not (Path(d) / "model.pt").exists():
            return
        try:
            import torch

            from .models import make_model

            ck = torch.load(Path(d) / "model.pt", map_location="cpu")
            vocab = json.loads((Path(d) / "vocab.json").read_text())
            self.model = make_model(ck["name"], len(vocab["entities"]), len(vocab["relations"]), ck["dim"], ck["gamma"])
            self.model.load_state_dict(ck["state"])
            self.model.eval()
            self.ent_id = {e: i for i, e in enumerate(vocab["entities"])}
            self.rel_id = {r: i for i, r in enumerate(vocab["relations"])}
            self.model_name = ck["name"]
        except Exception:                                    # a broken artifact must not break the API
            self.model = None

    @property
    def ranker(self) -> str:
        return f"embedding:{self.model_name}" if self.model is not None else "baseline"

    def _model_scores(self, head: str, rel: str, tails: list[str]) -> dict[str, float]:
        import torch

        if self.model is None or head not in self.ent_id:
            return {}
        ids = [(t, self.ent_id[t]) for t in tails if t in self.ent_id]
        if not ids:
            return {}
        with torch.no_grad():
            h = torch.full((len(ids),), self.ent_id[head])
            r = torch.full((len(ids),), self.rel_id[rel])
            t = torch.tensor([i for _, i in ids])
            d = self.model.dist(h, r, t)
        return {iri: float(-x) for (iri, _), x in zip(ids, d)}

    def _grp(self, e: str) -> str:
        return self.group.get(e, e)

    # -- recommendations --------------------------------------------------------------------
    def for_buyer(self, buyer: str, k: int = 10, include_incumbents: bool = False) -> dict:
        incumbents = set(self.hist.get(buyer, {}))
        inc_groups: dict[str, list[str]] = defaultdict(list)
        for s in incumbents:
            inc_groups[self._grp(s)].append(self.names.get(s, s))
        mine = self.buy_cats.get(buyer, set())
        cands = [s for s in self.suppliers if include_incumbents or s not in incumbents]
        ms = self._model_scores(buyer, "contractedWith", cands)
        rows = []
        for s in cands:
            shared = mine & self.sup_cats.get(s, set())
            peers = [n for n in inc_groups.get(self._grp(s), []) if s not in incumbents]
            base = len(shared) + 0.5 * bool(peers) + 0.001 * self.pop[s]
            score = ms.get(s, -1e9) if self.model is not None and ms else base
            rows.append((s, score, base, shared, peers))
        rows.sort(key=lambda r: (-r[1], -r[2]))
        return {"ranker": self.ranker, "buyer": buyer, "buyer_name": self.names.get(buyer), "candidates": [
            {"iri": s, "key": s.rsplit("/", 1)[-1], "name": self.names.get(s, s), "country": self.country.get(s),
             "score": round(float(score), 4), "incumbent": s in incumbents,
             "evidence": {"shared_categories": sorted(self.cat_label.get(c, c) for c in shared),
                          "group_peers_already_used": peers, "awards_total": self.pop[s],
                          "past_awards_from_buyer": self.hist.get(buyer, {}).get(s, 0)}}
            for s, score, _b, shared, peers in rows[:k]]}

    def for_category(self, category: str, k: int = 10) -> dict:
        siblings = {c for c, p in self.cat_parent.items() if p == self.cat_parent.get(category) and c != category}
        cands = [s for s in self.suppliers if category not in self.sup_cats.get(s, set())]
        ms = self._model_scores_cat(category, cands)
        rows = []
        for s in cands:
            sib = self.sup_cats.get(s, set()) & siblings
            base = len(sib) + 0.001 * self.pop[s]
            score = ms.get(s, -1e9) if self.model is not None and ms else base
            rows.append((s, score, base, sib))
        rows.sort(key=lambda r: (-r[1], -r[2]))
        return {"ranker": self.ranker, "category": category, "category_label": self.cat_label.get(category),
                "candidates": [{"iri": s, "key": s.rsplit("/", 1)[-1], "name": self.names.get(s, s),
                                "country": self.country.get(s), "score": round(float(score), 4), "incumbent": False,
                                "evidence": {"sibling_categories_supplied": sorted(self.cat_label.get(c, c) for c in sib),
                                             "awards_total": self.pop[s]}}
                               for s, score, _b, sib in rows[:k]]}

    def _model_scores_cat(self, category: str, suppliers: list[str]) -> dict[str, float]:
        import torch

        if self.model is None or category not in self.ent_id:
            return {}
        ids = [(s, self.ent_id[s]) for s in suppliers if s in self.ent_id]
        if not ids:
            return {}
        with torch.no_grad():
            h = torch.tensor([i for _, i in ids])
            r = torch.full((len(ids),), self.rel_id["suppliesCategory"])
            t = torch.full((len(ids),), self.ent_id[category])
            d = self.model.dist(h, r, t)
        return {s: float(-x) for (s, _), x in zip(ids, d)}
