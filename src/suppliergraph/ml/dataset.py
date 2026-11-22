"""Link-prediction dataset with a TEMPORAL split.

Task: given a buyer, rank suppliers that will receive an award from that buyer in a later period.
Awards are split by date (train < valid < test). Everything derived from awards (buyer->supplier,
supplier->category, buyer->category) is built from the TRAIN period only, so no information about
future awards leaks into the training graph. Static structure (ownership, registration country,
CPV hierarchy) is available at all times.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..namespaces import SPARQL_PREFIX_BLOCK
from ..store.base import SparqlStore

R_CONTRACT = "contractedWith"
R_SUPPLIES = "suppliesCategory"
R_PROCURES = "procuresCategory"
R_PARENT = "hasDirectParent"
R_COUNTRY = "registeredIn"
R_BROADER = "broader"
RELATIONS = [R_CONTRACT, R_SUPPLIES, R_PROCURES, R_PARENT, R_COUNTRY, R_BROADER]

AWARDS_Q = SPARQL_PREFIX_BLOCK + """
SELECT ?award ?buyer ?supplier ?date ?cat WHERE {
  ?award sg:awardOf ?t ; sg:awardedTo ?supplier ; sg:awardDate ?date .
  ?t sg:issuedBy ?buyer .
  OPTIONAL { ?t (sg:hasCategory|sg:hasDeclaredCategory|sg:hasLinkedCategory) ?cat }
}"""
PARENT_Q = SPARQL_PREFIX_BLOCK + "SELECT ?c ?p WHERE { ?c sg:hasDirectParent ?p }"
COUNTRY_Q = SPARQL_PREFIX_BLOCK + "SELECT ?e ?c WHERE { ?e sg:registeredIn ?c }"
BROADER_Q = SPARQL_PREFIX_BLOCK + "SELECT ?c ?p WHERE { ?c skos:broader ?p }"


@dataclass
class Ablation:
    ownership: bool = True
    country: bool = True
    category: bool = True

    def tag(self) -> str:
        off = [k for k, v in vars(self).items() if not v]
        return "full" if not off else "no_" + "_".join(off)


@dataclass
class LPDataset:
    entities: list[str]
    relations: list[str]
    train: np.ndarray                 # (n,3) int triples h,r,t used for training (aux + train awards)
    valid_pairs: list[tuple[int, int, int]]      # (buyer, supplier, award index) from the valid period
    test_pairs: list[tuple[int, int, int]]
    train_pairs: set[tuple[int, int]]
    supplier_pool: np.ndarray         # entity ids eligible as ranking candidates
    all_true: dict[int, set[int]]     # buyer -> every supplier it contracted with in any split (for filtering)
    train_supplier_set: set[int]
    split_dates: tuple[str, str]
    meta: dict = field(default_factory=dict)

    @property
    def n_entities(self) -> int:
        return len(self.entities)

    @property
    def n_relations(self) -> int:
        return len(self.relations)

    def rel_id(self, name: str) -> int:
        return self.relations.index(name)


def build_dataset(awards: list[dict], parents=(), countries=(), broader=(), *, ablation: Ablation | None = None,
                  fractions=(0.70, 0.85)) -> LPDataset:
    """awards: dicts with award, buyer, supplier, date, cat (cat may be None; one row per category)."""
    ab = ablation or Ablation()
    by_award: dict[str, dict] = {}
    for r in awards:
        a = by_award.setdefault(r["award"], {"buyer": r["buyer"], "supplier": r["supplier"], "date": str(r["date"])[:10], "cats": set()})
        if r.get("cat"):
            a["cats"].add(r["cat"])
    rows = sorted(by_award.values(), key=lambda a: a["date"])
    if len(rows) < 10:
        raise ValueError("need at least 10 dated awards for a temporal split")
    dates = [a["date"] for a in rows]
    if fractions is None:               # final model for serving: every award is training data
        t1 = t2 = dates[-1]
    else:
        t1 = dates[int(len(dates) * fractions[0]) - 1]
        t2 = dates[int(len(dates) * fractions[1]) - 1]

    ents: dict[str, int] = {}

    def eid(iri: str) -> int:
        return ents.setdefault(iri, len(ents))

    for a in rows:                      # register entities in a deterministic order
        eid(a["buyer"]); eid(a["supplier"])
    rel_ids = {r: i for i, r in enumerate(RELATIONS)}
    triples: set[tuple[int, int, int]] = set()
    train_pairs: set[tuple[int, int]] = set()
    train_awards = [a for a in rows if a["date"] <= t1]
    valid, test = [], []
    all_true: dict[int, set[int]] = {}
    for i, a in enumerate(rows):
        b, s = eid(a["buyer"]), eid(a["supplier"])
        all_true.setdefault(b, set()).add(s)
        if a["date"] <= t1:
            triples.add((b, rel_ids[R_CONTRACT], s))
            train_pairs.add((b, s))
            if ab.category:
                for c in a["cats"]:
                    triples.add((s, rel_ids[R_SUPPLIES], eid(c)))
                    triples.add((b, rel_ids[R_PROCURES], eid(c)))
        elif a["date"] <= t2:
            valid.append((b, s, i))
        else:
            test.append((b, s, i))
    if ab.ownership:
        for c, p in parents:
            triples.add((eid(c), rel_ids[R_PARENT], eid(p)))
    if ab.country:
        for e, c in countries:
            triples.add((eid(e), rel_ids[R_COUNTRY], eid(c)))
    if ab.category:
        for c, p in broader:
            triples.add((eid(c), rel_ids[R_BROADER], eid(p)))
    suppliers = sorted({eid(a["supplier"]) for a in rows})
    entities = [None] * len(ents)
    for iri, i in ents.items():
        entities[i] = iri
    return LPDataset(
        entities=entities, relations=list(RELATIONS), train=np.array(sorted(triples), dtype=np.int64),
        valid_pairs=valid, test_pairs=test, train_pairs=train_pairs,
        supplier_pool=np.array(suppliers, dtype=np.int64), all_true=all_true,
        train_supplier_set={s for _, s in train_pairs}, split_dates=(t1, t2),
        meta={"n_awards": len(rows), "n_train_awards": len(train_awards), "n_valid": len(valid), "n_test": len(test),
              "ablation": ab.tag()},
    )


def load_from_store(store: SparqlStore, ablation: Ablation | None = None, fractions=(0.70, 0.85)) -> LPDataset:
    awards = store.select(AWARDS_Q)
    parents = [(r["c"], r["p"]) for r in store.select(PARENT_Q)]
    countries = [(r["e"], r["c"]) for r in store.select(COUNTRY_Q)]
    broader = [(r["c"], r["p"]) for r in store.select(BROADER_Q)]
    return build_dataset(awards, parents, countries, broader, ablation=ablation, fractions=fractions)
