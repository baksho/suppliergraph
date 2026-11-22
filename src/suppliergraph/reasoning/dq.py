"""Data-quality checks expressed as SPARQL, complementing SHACL (which validates single nodes)."""
from __future__ import annotations

from ..namespaces import SPARQL_PREFIX_BLOCK
from ..store.base import SparqlStore

CHECKS: dict[str, str] = {
    "ultimate_parent_mismatch": """
        SELECT ?entity ?published ?derived WHERE {
          ?entity sg:hasUltimateParent ?published ; sg:derivedUltimateParent ?derived .
          FILTER(?published != ?derived)
        } LIMIT 200""",
    "ownership_cycles": """
        SELECT DISTINCT ?entity WHERE { ?entity sg:hasDirectParent+ ?entity } LIMIT 200""",
    "multiple_ultimate_parents": """
        SELECT ?entity (COUNT(DISTINCT ?p) AS ?n) WHERE { ?entity sg:hasUltimateParent ?p }
        GROUP BY ?entity HAVING (COUNT(DISTINCT ?p) > 1) LIMIT 200""",
    "tenders_without_category": """
        SELECT ?tender WHERE { ?tender a sg:Tender . FILTER NOT EXISTS { ?tender sg:hasCategory ?c } } LIMIT 200""",
    "unresolved_entities_with_awards": """
        SELECT ?entity ?name WHERE {
          ?a sg:awardedTo ?entity . ?entity sg:legalName ?name .
          FILTER NOT EXISTS { ?entity sg:lei ?lei }
        } GROUP BY ?entity ?name LIMIT 200""",
}


def run_checks(store: SparqlStore) -> dict[str, list[dict]]:
    return {name: store.select(SPARQL_PREFIX_BLOCK + q) for name, q in CHECKS.items()}


def summary(store: SparqlStore) -> dict:
    counts = store.select(SPARQL_PREFIX_BLOCK + """
        SELECT
          (COUNT(DISTINCT ?e) AS ?entities)
          (COUNT(DISTINCT ?lei) AS ?with_lei)
        WHERE { ?e a sg:LegalEntity . OPTIONAL { ?e sg:lei ?lei } }""")[0]
    res = {"entities": counts["entities"], "entities_with_lei": counts["with_lei"]}
    res["resolution_rate"] = (counts["with_lei"] / counts["entities"]) if counts["entities"] else None
    return res
