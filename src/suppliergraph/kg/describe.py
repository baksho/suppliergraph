"""Read-side queries used by the API: entity search, 'Supplier 360', contracts, lineage, JSON-LD."""
from __future__ import annotations

import re

from rdflib import Graph

from ..namespaces import ONT_BASE, PREFIXES, SPARQL_PREFIX_BLOCK, entity_iri
from ..store.base import SparqlStore

_KEY = re.compile(r"^[A-Za-z0-9\-]{3,40}$")


def safe_key(key: str) -> str:
    if not _KEY.match(key):
        raise ValueError("invalid entity key")
    return key


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def search_entities(store: SparqlStore, q: str, limit: int = 15) -> list[dict]:
    q = _esc(q.strip().lower())
    if len(q) < 2:
        return []
    rows = store.select(SPARQL_PREFIX_BLOCK + f"""
        SELECT ?e ?name (SAMPLE(?lei) AS ?lei) (SAMPLE(?cc) AS ?country) (COUNT(DISTINCT ?a) AS ?awards) WHERE {{
          ?e a sg:LegalEntity ; sg:legalName ?name .
          FILTER(CONTAINS(LCASE(STR(?name)), "{q}"))
          OPTIONAL {{ ?e sg:lei ?lei }}
          OPTIONAL {{ ?e sg:registeredIn/sg:isoCode ?cc }}
          OPTIONAL {{ ?a sg:awardedTo ?e }}
        }} GROUP BY ?e ?name ORDER BY DESC(?awards) ?name LIMIT {int(limit)}""")
    return [{"key": str(r["e"]).rsplit("/", 1)[-1], "iri": str(r["e"]), "name": r["name"], "lei": r["lei"],
             "country": r["country"], "awards": r["awards"]} for r in rows]


def entity_detail(store: SparqlStore, key: str) -> dict | None:
    iri = entity_iri(safe_key(key))
    head = store.select(SPARQL_PREFIX_BLOCK + f"""
        SELECT ?name ?lei ?cc WHERE {{ <{iri}> sg:legalName ?name .
          OPTIONAL {{ <{iri}> sg:lei ?lei }} OPTIONAL {{ <{iri}> sg:registeredIn/sg:isoCode ?cc }} }} LIMIT 1""")
    if not head:
        return None

    def col(q, *names):
        return [{n: r[n] for n in names} for r in store.select(SPARQL_PREFIX_BLOCK + q)]

    types = [r["t"].rsplit("#", 1)[-1] for r in store.select(SPARQL_PREFIX_BLOCK + f"""
        SELECT DISTINCT ?t WHERE {{ <{iri}> a ?t . FILTER(STRSTARTS(STR(?t), "{ONT_BASE}")) }}""")]
    recorded = [r["n"] for r in store.select(SPARQL_PREFIX_BLOCK + f"SELECT DISTINCT ?n WHERE {{ <{iri}> sg:recordedName ?n }}")]
    parents = col(f"SELECT ?p ?name ?kind WHERE {{ {{ <{iri}> sg:hasDirectParent ?p BIND('direct' AS ?kind) }} UNION "
                  f"{{ <{iri}> sg:hasUltimateParent ?p BIND('published ultimate' AS ?kind) }} UNION "
                  f"{{ <{iri}> sg:derivedUltimateParent ?p BIND('derived ultimate' AS ?kind) }} ?p sg:legalName ?name }}",
                  "p", "name", "kind")
    children = col(f"SELECT ?c ?name WHERE {{ ?c sg:hasDirectParent <{iri}> ; sg:legalName ?name }} LIMIT 50", "c", "name")
    summary = store.select(SPARQL_PREFIX_BLOCK + f"""
        SELECT (COUNT(DISTINCT ?a) AS ?n_awards) (SUM(?v) AS ?total) (MIN(?d) AS ?first) (MAX(?d) AS ?last) WHERE {{
          ?a sg:awardedTo <{iri}> . OPTIONAL {{ ?a sg:valueAmount ?v }} OPTIONAL {{ ?a sg:awardDate ?d }} }}""")[0]
    issued = store.select(SPARQL_PREFIX_BLOCK + f"SELECT (COUNT(DISTINCT ?t) AS ?n) WHERE {{ ?t sg:issuedBy <{iri}> }}")[0]["n"]
    categories = col(f"""SELECT ?c ?code ?label (COUNT(DISTINCT ?a) AS ?n) WHERE {{
        ?a sg:awardedTo <{iri}> ; sg:awardOf ?t . ?t sg:hasCategory ?c . ?c skos:notation ?code .
        OPTIONAL {{ ?c skos:prefLabel ?label . FILTER(LANG(?label) = "en") }} }}
        GROUP BY ?c ?code ?label ORDER BY DESC(?n) LIMIT 20""", "code", "label", "n")
    buyers = col(f"""SELECT ?b ?name (COUNT(DISTINCT ?a) AS ?n) WHERE {{
        ?a sg:awardedTo <{iri}> ; sg:awardOf ?t . ?t sg:issuedBy ?b . ?b sg:legalName ?name }}
        GROUP BY ?b ?name ORDER BY DESC(?n) LIMIT 20""", "b", "name", "n")
    flags = col(f"""SELECT ?f ?via ?vname ?hops ?score ?entry ?ename ?status WHERE {{
        ?f a sg:ExposureFlag ; sg:flaggedEntity <{iri}> ; sg:viaEntity ?via ; sg:viaMatch ?m ; sg:hops ?hops ;
           sg:reviewStatus ?status .
        ?via sg:legalName ?vname . ?m sg:matchScore ?score ; sg:matchedEntry ?entry . ?entry sg:legalName ?ename }}
        ORDER BY ?hops""", "via", "vname", "hops", "score", "entry", "ename", "status")
    return {
        "key": key, "iri": iri, "name": head[0]["name"], "lei": head[0]["lei"], "country": head[0]["cc"],
        "types": sorted(types), "recorded_names": recorded, "parents": parents, "children": children,
        "awards": {"count": summary["n_awards"], "total_value": summary["total"], "first": summary["first"],
                   "last": summary["last"]},
        "tenders_issued": issued, "categories": categories, "buyers": buyers, "exposure_flags": flags,
        "note": "Exposure flags are leads for human review based on fuzzy name matching, not findings.",
    }


def contracts(store: SparqlStore, key: str, limit: int = 100) -> list[dict]:
    iri = entity_iri(safe_key(key))
    return store.select(SPARQL_PREFIX_BLOCK + f"""
        SELECT ?award ?title ?date ?amount ?currency ?buyer ?bname ?supplier ?sname WHERE {{
          ?award sg:awardOf ?t ; sg:awardedTo ?supplier . ?t sg:issuedBy ?buyer .
          FILTER(?buyer = <{iri}> || ?supplier = <{iri}>)
          ?buyer sg:legalName ?bname . ?supplier sg:legalName ?sname .
          OPTIONAL {{ ?t sg:title ?title }} OPTIONAL {{ ?award sg:awardDate ?date }}
          OPTIONAL {{ ?award sg:valueAmount ?amount }} OPTIONAL {{ ?award sg:valueCurrency ?currency }}
        }} ORDER BY DESC(?date) LIMIT {int(limit)}""")


def lineage(store: SparqlStore, key: str) -> list[dict]:
    """Which data products (named graphs) contributed which predicates about this entity."""
    iri = entity_iri(safe_key(key))
    rows = store.select(SPARQL_PREFIX_BLOCK + f"""
        SELECT ?g ?p (COUNT(*) AS ?n) WHERE {{ GRAPH ?g {{ <{iri}> ?p ?o }} }} GROUP BY ?g ?p ORDER BY ?g ?p""")
    meta = {r["dp"]: r for r in store.select(SPARQL_PREFIX_BLOCK + """
        SELECT ?dp ?title ?note WHERE { ?dp a sg:DataProduct ; dcterms:title ?title . OPTIONAL { ?dp sg:sourceNote ?note } }""")}
    out = []
    for r in rows:
        m = meta.get(r["g"], {})
        out.append({"graph": r["g"], "product": m.get("title") or r["g"].rsplit("/", 1)[-1], "source_note": m.get("note"),
                    "predicate": str(r["p"]).rsplit("#", 1)[-1].rsplit("/", 1)[-1], "triples": r["n"]})
    return out


JSONLD_CONTEXT = {k: v for k, v in PREFIXES.items() if k not in ("id", "rdf", "owl")} | {
    "name": "sg:legalName", "lei": "sg:lei"}


def entity_jsonld(store: SparqlStore, key: str) -> dict | None:
    import json

    iri = entity_iri(safe_key(key))
    g: Graph = store.construct(SPARQL_PREFIX_BLOCK + f"""
        CONSTRUCT {{ <{iri}> ?p ?o . ?o rdfs:label ?l }} WHERE {{
          <{iri}> ?p ?o . FILTER(?p NOT IN (sg:hasAncestor, sg:wonAward))
          OPTIONAL {{ ?o (sg:legalName|skos:prefLabel) ?l }} }}""")
    if len(g) == 0:
        return None
    return json.loads(g.serialize(format="json-ld", context=JSONLD_CONTEXT, indent=2))
