"""In-process store on rdflib (development, tests, small demos). Persisted as N-Quads."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

from rdflib import Dataset, Graph, URIRef

from .base import Row, term_to_py

_POOL = ThreadPoolExecutor(max_workers=4)
# rdflib's SPARQL parser (pyparsing) is not safe to run from several threads at once: concurrent first parses can fail with
# "TypeError: <lambda>() missing 1 required positional argument". Every parse and query goes through this one lock.
RDFLIB_LOCK = threading.RLock()


class QueryTimeout(TimeoutError):
    pass


class LocalStore:
    def __init__(self, persist_path: Path | None = None):
        self.ds = Dataset(default_union=True)
        self.persist_path = persist_path
        self._lock = RDFLIB_LOCK
        if persist_path and Path(persist_path).exists():
            self.ds.parse(str(persist_path), format="nquads")

    # -- querying ---------------------------------------------------------------------------
    def _run(self, fn, timeout):
        if timeout is None:
            with self._lock:
                return fn()
        fut = _POOL.submit(lambda: self._locked(fn))
        try:
            return fut.result(timeout=timeout)
        except FutureTimeout as exc:   # the worker thread cannot be interrupted; document in docs/design.md
            raise QueryTimeout(f"query exceeded {timeout}s") from exc

    def _locked(self, fn):
        with self._lock:
            return fn()

    def select(self, query: str, timeout: float | None = None) -> list[Row]:
        def go():
            res = self.ds.query(query)
            names = [str(v) for v in res.vars]
            return [{n: term_to_py(row[i]) for i, n in enumerate(names)} for row in res]

        return self._run(go, timeout)

    def ask(self, query: str, timeout: float | None = None) -> bool:
        return bool(self._run(lambda: self.ds.query(query).askAnswer, timeout))

    def construct(self, query: str, timeout: float | None = None) -> Graph:
        def go():
            g = Graph()
            for t in self.ds.query(query):
                g.add(t)
            return g

        return self._run(go, timeout)

    def update(self, query: str) -> None:
        with self._lock:
            self.ds.update(query)

    # -- loading ----------------------------------------------------------------------------
    def clear(self) -> None:
        with self._lock:
            self.ds = Dataset(default_union=True)

    def load_file(self, path: Path, fmt: str, graph: str | None = None) -> None:
        with self._lock:
            if graph:
                self.ds.graph(URIRef(graph)).parse(str(path), format=fmt)
            else:
                self.ds.parse(str(path), format=fmt)

    def insert_triples(self, g: Graph, graph: str) -> None:
        with self._lock:
            target = self.ds.graph(URIRef(graph))
            for t in g:
                target.add(t)

    def drop_graph(self, graph: str) -> None:
        with self._lock:
            self.ds.remove_graph(self.ds.graph(URIRef(graph)))

    def triple_count(self) -> int:
        with self._lock:
            return sum(len(g) for g in self.ds.graphs())

    def as_graph(self) -> Graph:
        """A plain graph holding the union of all named graphs."""
        g = Graph()
        with self._lock:
            for s, p, o, _ in self.ds.quads((None, None, None, None)):
                g.add((s, p, o))
        return g

    def save(self, path: Path | None = None) -> None:
        path = Path(path or self.persist_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.ds.serialize(destination=str(path), format="nquads")
