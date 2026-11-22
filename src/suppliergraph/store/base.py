"""Store abstraction: the same code runs against an in-process graph (dev/tests) or a SPARQL endpoint
(GraphDB, Ontop, HANA Cloud KG engine, ...). Only standard SPARQL 1.1 is used."""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from rdflib import BNode, Graph, Literal, URIRef


class IRI(str):
    """A string that is known to be an IRI (so that callers can tell IRIs from literals)."""


Row = dict[str, Any]


def term_to_py(term) -> Any:
    if term is None:
        return None
    if isinstance(term, URIRef):
        return IRI(str(term))
    if isinstance(term, BNode):
        return str(term)
    if isinstance(term, Literal):
        v = term.toPython()
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, (_dt.date, _dt.datetime)):
            return v.isoformat()
        if isinstance(v, (int, float, bool, str)):
            return v
        return str(term)
    return str(term)


class SparqlStore(Protocol):
    def select(self, query: str, timeout: float | None = None) -> list[Row]: ...
    def ask(self, query: str, timeout: float | None = None) -> bool: ...
    def construct(self, query: str, timeout: float | None = None) -> Graph: ...
    def update(self, query: str) -> None: ...
    def clear(self) -> None: ...
    def load_file(self, path: Path, fmt: str, graph: str | None = None) -> None: ...
    def insert_triples(self, g: Graph, graph: str) -> None: ...
    def triple_count(self) -> int: ...
    def as_graph(self) -> Graph: ...
