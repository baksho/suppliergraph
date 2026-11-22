"""Text retrieval over tender descriptions and extracted obligations, with graph expansion.

The default index is TF-IDF (no model download, deterministic). The `Embedder` protocol lets you
swap in a multilingual sentence-embedding model; see docs/evaluation.md for how to compare them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from ..er.normalize import normalize_name
from ..namespaces import SPARQL_PREFIX_BLOCK
from ..store.base import SparqlStore

DOCS_Q = SPARQL_PREFIX_BLOCK + """
SELECT ?doc ?kind ?text WHERE {
  { ?doc a sg:Tender . OPTIONAL { ?doc sg:title ?title } OPTIONAL { ?doc sg:description ?desc }
    BIND(CONCAT(COALESCE(?title, ""), ". ", COALESCE(?desc, "")) AS ?text) BIND("tender" AS ?kind) }
  UNION
  { ?doc a sg:Obligation ; sg:obligationText ?text . BIND("obligation" AS ?kind) }
  FILTER(STRLEN(?text) > 3)
}"""


@dataclass
class Doc:
    iri: str
    kind: str
    text: str
    score: float = 0.0


class Embedder(Protocol):
    def fit_transform(self, texts: list[str]): ...
    def transform(self, texts: list[str]): ...


class DocIndex:
    def __init__(self, docs: list[Doc], embedder: Embedder | None = None):
        self.docs = docs
        self.emb = embedder or TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1, dtype=np.float32)
        self._prep = lambda t: normalize_name(t).full
        self.M = self.emb.fit_transform([self._prep(d.text) for d in docs]) if docs else None

    @classmethod
    def from_store(cls, store: SparqlStore, embedder: Embedder | None = None) -> DocIndex:
        rows = store.select(DOCS_Q)
        return cls([Doc(str(r["doc"]), r["kind"], str(r["text"])) for r in rows], embedder)

    def search(self, query: str, k: int = 4, min_score: float = 0.05) -> list[Doc]:
        if not self.docs:
            return []
        q = self.emb.transform([self._prep(query)])
        sims = np.asarray((q @ self.M.T).todense()).ravel() if hasattr(q, "todense") else np.asarray(q @ self.M.T).ravel()
        order = np.argsort(-sims)[:k]
        return [Doc(self.docs[i].iri, self.docs[i].kind, self.docs[i].text, float(sims[i]))
                for i in order if sims[i] >= min_score]


FACTS_Q = SPARQL_PREFIX_BLOCK + """
SELECT ?s ?p ?o ?sl ?ol WHERE {{
  VALUES ?s {{ <{iri}> }}
  ?s ?p ?o .
  VALUES ?p {{ sg:issuedBy sg:awardOf sg:awardedTo sg:valueAmount sg:valueCurrency sg:awardDate sg:publicationDate
              sg:hasDeclaredCategory sg:hasLinkedCategory sg:requiresStandard sg:extractedFrom sg:article
              sg:appliesToRole }}
  OPTIONAL {{ ?s (sg:legalName|sg:title|skos:prefLabel|rdfs:label) ?sl }}
  OPTIONAL {{ ?o (sg:legalName|sg:title|skos:prefLabel|rdfs:label) ?ol }}
}} LIMIT 40"""
INCOMING_Q = SPARQL_PREFIX_BLOCK + """
SELECT ?s ?p ?o ?sl ?ol WHERE {{
  VALUES ?o {{ <{iri}> }}
  ?s ?p ?o . VALUES ?p {{ sg:awardOf }}
  OPTIONAL {{ ?s sg:legalName ?sl }}
  OPTIONAL {{ ?o (sg:legalName|sg:title) ?ol }}
}} LIMIT 20"""


@dataclass
class Fact:
    text: str
    triple: tuple[str, str, str]


def expand_doc(store: SparqlStore, iri: str) -> list[Fact]:
    """1-hop facts around a retrieved document node (tender/obligation) from the graph."""
    out: list[Fact] = []
    rows = store.select(FACTS_Q.format(iri=iri))
    awards = store.select(INCOMING_Q.format(iri=iri))
    label = None
    for r in rows:
        label = label or r.get("sl")
        p = str(r["p"]).rsplit("#", 1)[-1]
        obj = r.get("ol") or r["o"]
        out.append(Fact(f"{r.get('sl') or iri.rsplit('/', 1)[-1]} {p} {obj}", (str(r["s"]), str(r["p"]), str(r["o"]))))
    for a in awards:
        # one hop further: supplier and value of each award on this tender
        det = store.select(SPARQL_PREFIX_BLOCK + f"""
            SELECT ?name ?amount ?cur ?sup WHERE {{ <{a['s']}> sg:awardedTo ?sup . ?sup sg:legalName ?name .
              OPTIONAL {{ <{a['s']}> sg:valueAmount ?amount }} OPTIONAL {{ <{a['s']}> sg:valueCurrency ?cur }} }} LIMIT 3""")
        for d in det:
            amt = f" for {d['amount']:,.2f} {d.get('cur') or ''}".rstrip() if d.get("amount") is not None else ""
            out.append(Fact(f"{label or 'tender'} was awarded to {d['name']}{amt}",
                            (str(a["s"]), "https://suppliergraph.example/ontology#awardedTo", str(d["sup"]))))
    return out
