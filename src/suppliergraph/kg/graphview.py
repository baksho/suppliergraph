"""Subgraph extraction for visualisation (Cytoscape elements) and for evidence in answers."""
from __future__ import annotations

from ..namespaces import ONT_BASE, SPARQL_PREFIX_BLOCK
from ..store.base import SparqlStore

# Show asserted relations only (inferred shortcuts such as sg:hasCategory or sg:hasAncestor would
# draw every fact twice).
SHOWN_PREDICATES = [
    "sg:issuedBy", "sg:awardOf", "sg:awardedTo", "sg:hasDirectParent", "sg:hasUltimateParent",
    "sg:hasDeclaredCategory", "sg:hasLinkedCategory", "sg:registeredIn", "sg:matchedEntity", "sg:matchedEntry",
    "sg:flaggedEntity", "sg:viaEntity", "sg:extractedFrom", "skos:broader",
]
TYPE_PRIORITY = ["ExposureFlag", "SanctionMatch", "Award", "Tender", "Obligation", "ProductCategory",
                 "SanctionEntry", "Regulation", "Country", "Supplier", "Buyer", "LegalEntity"]


def _values(iris: list[str]) -> str:
    return " ".join(f"<{i}>" for i in iris)


def neighborhood(store: SparqlStore, seeds: list[str], hops: int = 1, max_nodes: int = 80) -> dict:
    """Cytoscape-style {nodes, edges} around the seed IRIs (outgoing and incoming shown relations)."""
    seeds = [s for s in dict.fromkeys(seeds) if s.startswith("http")][:40]
    if not seeds:
        return {"nodes": [], "edges": []}
    preds = " ".join(SHOWN_PREDICATES)
    frontier, seen_edges, nodes = list(seeds), set(), set(seeds)
    for _ in range(hops):
        if not frontier:
            break
        rows = store.select(SPARQL_PREFIX_BLOCK + f"""
            SELECT DISTINCT ?s ?p ?o WHERE {{
              {{ VALUES ?s {{ {_values(frontier)} }} ?s ?p ?o }} UNION {{ VALUES ?o {{ {_values(frontier)} }} ?s ?p ?o }}
              VALUES ?p {{ {preds} }}
              FILTER(isIRI(?o))
            }} LIMIT {max_nodes * 6}""")
        nxt = []
        for r in rows:
            e = (str(r["s"]), str(r["p"]), str(r["o"]))
            if e in seen_edges:
                continue
            if len(nodes | {e[0], e[2]}) > max_nodes:
                continue
            seen_edges.add(e)
            for n in (e[0], e[2]):
                if n not in nodes:
                    nodes.add(n)
                    nxt.append(n)
        frontier = nxt
    info = {n: {"label": None, "type": None} for n in nodes}
    if nodes:
        rows = store.select(SPARQL_PREFIX_BLOCK + f"""
            SELECT ?n ?label ?type WHERE {{
              VALUES ?n {{ {_values(sorted(nodes))} }}
              OPTIONAL {{ ?n (sg:legalName|sg:title|skos:prefLabel|rdfs:label|sg:isoCode) ?label }}
              OPTIONAL {{ ?n a ?type . FILTER(STRSTARTS(STR(?type), "{ONT_BASE}")) }}
            }}""")
        types: dict[str, set[str]] = {}
        for r in rows:
            n = str(r["n"])
            if r["label"] and not info[n]["label"]:
                info[n]["label"] = str(r["label"])
            if r["type"]:
                types.setdefault(n, set()).add(str(r["type"]).rsplit("#", 1)[-1])
        for n, ts in types.items():
            info[n]["type"] = next((t for t in TYPE_PRIORITY if t in ts), sorted(ts)[0])
    return {
        "nodes": [{"id": n, "label": (v["label"] or n.rsplit("/", 1)[-1])[:48], "type": v["type"] or "Resource",
                   "seed": n in seeds} for n, v in info.items()],
        "edges": [{"source": s, "target": o, "label": p.rsplit("#", 1)[-1].rsplit("/", 1)[-1]} for s, p, o in sorted(seen_edges)],
    }
