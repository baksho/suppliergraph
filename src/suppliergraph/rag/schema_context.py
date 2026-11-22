"""Ontology -> compact schema description for prompts, plus the set of terms a query may use."""
from __future__ import annotations

import re
from functools import lru_cache

from rdflib import Graph, Namespace
from rdflib.namespace import OWL, RDF, RDFS

from ..config import get_settings
from ..namespaces import ONT_BASE

ONT_NS = Namespace(ONT_BASE)


@lru_cache(maxsize=1)
def _ontology() -> Graph:
    return Graph().parse(get_settings().ontology_path)


def known_terms() -> set[str]:
    g = _ontology()
    out = set()
    for kind in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty):
        for s in g.subjects(RDF.type, kind):
            if str(s).startswith(ONT_BASE):
                out.add(str(s)[len(ONT_BASE):])
    return out


def _local(iri) -> str:
    s = str(iri)
    return "sg:" + s[len(ONT_BASE):] if s.startswith(ONT_BASE) else s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


# Worked examples. They are deliberately NOT the questions in eval/competency.yaml, so the evaluation stays a fair test.
EXAMPLES = """EXAMPLES (question -> query; adapt, do not copy values)
Q: Which buyers contracted with the most distinct suppliers?
SELECT ?buyerName (COUNT(DISTINCT ?s) AS ?suppliers) WHERE { ?b sg:contractedWith ?s ; sg:legalName ?buyerName } GROUP BY ?buyerName ORDER BY DESC(?suppliers) LIMIT 10

Q: How many exposure flags exist for each number of hops?
SELECT ?hops (COUNT(DISTINCT ?f) AS ?flags) WHERE { ?f a sg:ExposureFlag ; sg:hops ?hops } GROUP BY ?hops ORDER BY ?hops

Q: Which entities have a sanction match with a score above 0.95?
SELECT ?name ?score WHERE { ?m a sg:SanctionMatch ; sg:matchedEntity ?e ; sg:matchScore ?score . ?e sg:legalName ?name . FILTER(?score > 0.95) } ORDER BY DESC(?score)

Q: Which product categories does the supplier Acme supply?
SELECT DISTINCT ?cat WHERE { ?s sg:legalName ?n ; sg:suppliesCategory ?c . ?c skos:prefLabel ?cat . FILTER(CONTAINS(LCASE(STR(?n)), "acme")) }

Q: Which entities are owned, directly or indirectly, by Acme?
SELECT DISTINCT ?name WHERE { ?e sg:hasAncestor ?p ; sg:legalName ?name . ?p sg:legalName ?pn . FILTER(CONTAINS(LCASE(STR(?pn)), "acme")) }"""


def direction_hints(query: str) -> str:
    """For each object property used in the query: which class must be the subject and which the object."""
    g = _ontology()
    out = []
    for name in dict.fromkeys(re.findall(r"\bsg:([A-Za-z_][A-Za-z0-9_]*)", query)):
        p = ONT_NS[name]
        if (p, RDF.type, OWL.ObjectProperty) not in g:
            continue
        d, r = next(g.objects(p, RDFS.domain), None), next(g.objects(p, RDFS.range), None)
        if d is not None and r is not None:
            out.append(f"sg:{name} goes FROM a {_local(d)} (subject) TO a {_local(r)} (object)")
    return "; ".join(out)


def schema_text() -> str:
    g = _ontology()
    lines = ["CLASSES"]
    for c in sorted(g.subjects(RDF.type, OWL.Class), key=str):
        if str(c).startswith(ONT_BASE):
            comment = next(g.objects(c, RDFS.comment), "")
            lines.append(f"- {_local(c)}: {comment}")
    lines.append("\nOBJECT PROPERTIES (domain -> range)")
    for p in sorted(g.subjects(RDF.type, OWL.ObjectProperty), key=str):
        if str(p).startswith(ONT_BASE):
            d = next(g.objects(p, RDFS.domain), None)
            r = next(g.objects(p, RDFS.range), None)
            comment = next(g.objects(p, RDFS.comment), "")
            lines.append(f"- {_local(p)} ({_local(d) if d else '?'} -> {_local(r) if r else '?'}): {comment}")
    lines.append("\nDATATYPE PROPERTIES")
    for p in sorted(g.subjects(RDF.type, OWL.DatatypeProperty), key=str):
        if str(p).startswith(ONT_BASE):
            d = next(g.objects(p, RDFS.domain), None)
            r = next(g.objects(p, RDFS.range), None)
            comment = next(g.objects(p, RDFS.comment), "")
            lines.append(f"- {_local(p)} ({_local(d) if d else 'any'} -> {_local(r) if r else 'literal'}): {comment}")
    lines.append(
        "\nOTHER VOCABULARY: skos:prefLabel / skos:notation / skos:broader (CPV categories; the 8-digit code is "
        "skos:notation), skos:altLabel, rdfs:label, prov:wasGeneratedBy."
        "\nNOTES: Entities are identified by IRIs you cannot guess. Only when the question names a specific entity, find it with "
        "?e sg:legalName ?n FILTER(CONTAINS(LCASE(STR(?n)), \"<one distinctive lower-case word from the question>\")); "
        "never put placeholder text in a filter, and add no name filter when the question names no entity. "
        "Alternative recorded names are sg:recordedName. Cardinalities are not guaranteed; use DISTINCT. "
        "Keep queries short (at most about 8 triple patterns). Ownership chains: use the transitive sg:hasAncestor, "
        "never a repeated chain of sg:hasDirectParent. Sanction exposure is an sg:ExposureFlag node "
        "(sg:flaggedEntity, sg:viaEntity, sg:hops), not a property of the entity; sg:hops = 0 means the entity itself carries "
        "the sanction match, sg:hops > 0 means a parent company further up its ownership chain does (sg:viaEntity is that "
        "parent). Ordinary words from the question (such as 'parent company' or 'suppliers') are never entity names."
        "\n\n" + EXAMPLES
    )
    return "\n".join(lines)
