"""Reasoning: OWL 2 RL materialisation (owlrl) plus SPARQL CONSTRUCT rules.

Trade-off, in short (see docs/design.md): OWL RL / rules give *auditable, deterministic* facts
(typing, transitive ownership, category subsumption, exposure chains). Graph embeddings give
*ranked guesses* about facts that are not in the data. They answer different questions, so the
project keeps them in separate named graphs and never mixes derived with predicted triples.
"""
from __future__ import annotations

from pathlib import Path

from rdflib import Graph
from rdflib.namespace import OWL, RDF, RDFS

from ..config import get_settings
from ..namespaces import DATA_BASE, GRAPH_BASE
from ..store.base import SparqlStore

INFERRED_GRAPH = f"{GRAPH_BASE}inferred"
DERIVED_GRAPH = f"{GRAPH_BASE}derived"
ONTOLOGY_GRAPH = f"{GRAPH_BASE}ontology"

_NOISE_OBJECTS = {RDFS.Resource, OWL.Thing, OWL.Nothing, RDFS.Class, RDF.Property}


def rules_dir() -> Path:
    return get_settings().root / "sparql" / "rules"


def run_owlrl(store: SparqlStore) -> int:
    """Materialise OWL 2 RL consequences about *instances* into the inferred graph.

    Remote stores (GraphDB) should use the repository ruleset instead (owl2-rl-optimized); this
    function is for the in-process store.
    """
    import owlrl

    g = store.as_graph()
    before = set(g)
    owlrl.DeductiveClosure(
        owlrl.OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False
    ).expand(g)
    new = Graph()
    for s, p, o in g:
        if (s, p, o) in before:
            continue
        if not str(s).startswith(DATA_BASE):          # keep inferences about instances only
            continue
        if o in _NOISE_OBJECTS or (p == OWL.sameAs and s == o):
            continue
        new.add((s, p, o))
    store.insert_triples(new, INFERRED_GRAPH)
    return len(new)


def _hop_unions(max_hops: int) -> str:
    # SPARQL evaluates group patterns bottom-up, so hop 0 must bind ?e from the match itself
    blocks = ["{ ?m sg:matchedEntity ?e . BIND(0 AS ?h) }"]
    for n in range(1, max_hops + 1):
        path = "/".join(["sg:hasDirectParent"] * n)
        blocks.append(f"{{ ?e {path} ?v . BIND({n} AS ?h) }}")
    return " UNION ".join(blocks)


def run_rules(store: SparqlStore, threshold: float | None = None, max_hops: int = 5) -> dict[str, int]:
    """Run the SPARQL CONSTRUCT rules and store their output in the derived graph."""
    settings = get_settings()
    threshold = settings.sanction_threshold if threshold is None else threshold
    out: dict[str, int] = {}
    total = Graph()
    for name in ("derived_ultimate_parent", "contracted_with", "supplies_category", "sanction_exposure"):
        q = (rules_dir() / f"{name}.rq").read_text(encoding="utf-8")
        if name == "sanction_exposure":
            q = q.replace("{threshold}", repr(float(threshold))).replace(
                "{max_hops}", str(max_hops)
            ).replace("{hop_unions}", _hop_unions(max_hops))
        g = store.construct(q)
        out[name] = len(g)
        total += g
    store.insert_triples(total, DERIVED_GRAPH)
    return out


def clear_derived(store: SparqlStore) -> None:
    for g in (INFERRED_GRAPH, DERIVED_GRAPH):
        if hasattr(store, "drop_graph"):
            store.drop_graph(g)
