"""SPARQL 1.1 protocol client (GraphDB / RDF4J-style endpoints, also works read-only with Ontop).

NOT verified against a running GraphDB in the build sandbox (no Docker daemon / network); see
docs/design.md "What was and was not verified".
"""
from __future__ import annotations

from pathlib import Path

import httpx
from rdflib import Graph

from .base import IRI, Row

_MIME = {"nquads": "text/x-nquads", "turtle": "text/turtle", "nt": "application/n-triples"}


def _bind_value(b: dict):
    t, v = b["type"], b["value"]
    if t == "uri":
        return IRI(v)
    if t == "bnode":
        return v
    dt = b.get("datatype", "")
    try:
        if dt.endswith("#integer") or dt.endswith("#int") or dt.endswith("#long"):
            return int(v)
        if dt.endswith("#decimal") or dt.endswith("#double") or dt.endswith("#float"):
            return float(v)
        if dt.endswith("#boolean"):
            return v == "true"
    except ValueError:
        pass
    return v


class RemoteStore:
    def __init__(self, query_url: str, update_url: str | None = None, statements_url: str | None = None,
                 auth: tuple[str, str] | None = None, timeout: float = 60.0):
        self.query_url = query_url
        self.update_url = update_url or statements_url
        self.statements_url = statements_url or update_url
        self.client = httpx.Client(auth=auth, timeout=timeout)

    def select(self, query: str, timeout: float | None = None) -> list[Row]:
        r = self.client.post(
            self.query_url, data={"query": query}, headers={"Accept": "application/sparql-results+json"},
            timeout=timeout or self.client.timeout,
        )
        r.raise_for_status()
        js = r.json()
        names = js["head"]["vars"]
        return [{n: (_bind_value(b[n]) if n in b else None) for n in names} for b in js["results"]["bindings"]]

    def ask(self, query: str, timeout: float | None = None) -> bool:
        r = self.client.post(
            self.query_url, data={"query": query}, headers={"Accept": "application/sparql-results+json"},
            timeout=timeout or self.client.timeout,
        )
        r.raise_for_status()
        return bool(r.json()["boolean"])

    def construct(self, query: str, timeout: float | None = None) -> Graph:
        r = self.client.post(
            self.query_url, data={"query": query}, headers={"Accept": "text/turtle"},
            timeout=timeout or self.client.timeout,
        )
        r.raise_for_status()
        g = Graph()
        g.parse(data=r.text, format="turtle")
        return g

    def update(self, query: str) -> None:
        r = self.client.post(self.update_url, data={"update": query})
        r.raise_for_status()

    def clear(self) -> None:
        self.update("CLEAR ALL")

    def load_file(self, path: Path, fmt: str, graph: str | None = None) -> None:
        params = {"context": f"<{graph}>"} if graph else None
        with open(path, "rb") as fh:
            r = self.client.post(
                self.statements_url, params=params, content=fh.read(),
                headers={"Content-Type": _MIME.get(fmt, "text/turtle")}, timeout=600.0,
            )
        r.raise_for_status()

    def insert_triples(self, g: Graph, graph: str) -> None:
        r = self.client.post(
            self.statements_url, params={"context": f"<{graph}>"}, content=g.serialize(format="nt").encode(),
            headers={"Content-Type": "application/n-triples"}, timeout=600.0,
        )
        r.raise_for_status()

    def drop_graph(self, graph: str) -> None:
        self.update(f"DROP SILENT GRAPH <{graph}>")

    def triple_count(self) -> int:
        return int(self.select("SELECT (COUNT(*) AS ?n) WHERE { { ?s ?p ?o } UNION { GRAPH ?g { ?s ?p ?o } } }")[0]["n"])

    def as_graph(self) -> Graph:
        return self.construct("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
