"""IRI namespaces. The base IRI is a reserved placeholder; see docs/design.md (IRI policy)."""
from __future__ import annotations

from rdflib import Namespace

ONT_BASE = "https://suppliergraph.example/ontology#"
DATA_BASE = "https://suppliergraph.example/id/"
GRAPH_BASE = "https://suppliergraph.example/graph/"
DP_BASE = "https://suppliergraph.example/dp/"

SG = Namespace(ONT_BASE)
ID = Namespace(DATA_BASE)
GRAPH = Namespace(GRAPH_BASE)
DP = Namespace(DP_BASE)

PREFIXES = {
    "sg": ONT_BASE,
    "id": DATA_BASE,
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "prov": "http://www.w3.org/ns/prov#",
    "org": "http://www.w3.org/ns/org#",
    "dcat": "http://www.w3.org/ns/dcat#",
    "dcterms": "http://purl.org/dc/terms/",
}

SPARQL_PREFIX_BLOCK = "\n".join(f"PREFIX {k}: <{v}>" for k, v in PREFIXES.items()) + "\n"


def entity_iri(key: str) -> str:
    """IRI of a legal entity from its key (an LEI, or 'P-...' for an unresolved party)."""
    return f"{DATA_BASE}entity/{key}"


def entity_key(iri: str) -> str:
    return iri.rsplit("/", 1)[-1]
