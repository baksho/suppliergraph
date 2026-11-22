from __future__ import annotations

from functools import lru_cache

from ..config import Settings, get_settings
from .base import IRI, SparqlStore, term_to_py
from .local import LocalStore, QueryTimeout
from .remote import RemoteStore

__all__ = ["IRI", "LocalStore", "QueryTimeout", "RemoteStore", "SparqlStore", "get_store", "open_store", "term_to_py"]


def open_store(settings: Settings | None = None) -> SparqlStore:
    s = settings or get_settings()
    if s.store_mode == "remote":
        if not s.sparql_query_url:
            raise RuntimeError("SG_STORE=remote requires SG_SPARQL_QUERY_URL")
        return RemoteStore(s.sparql_query_url, s.sparql_update_url or None, s.sparql_statements_url or None)
    return LocalStore(s.local_kg_path)


@lru_cache(maxsize=1)
def get_store() -> SparqlStore:
    """Process-wide store used by the API."""
    return open_store()
