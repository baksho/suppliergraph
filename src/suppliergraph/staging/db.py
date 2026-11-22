"""Relational staging database helpers (SQLite for dev, PostgreSQL in docker-compose)."""
from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from importlib import resources

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from ..config import get_settings

TABLES = [
    "gleif_entity", "gleif_relationship", "cpv_code", "party", "tender", "award", "tender_cpv",
    "tender_requirement", "sanction_entry", "party_resolution", "sanction_match", "regulation",
    "extraction_run", "obligation", "kg_scope",
]
VIEWS = [
    "v_sanction_match", "v_award", "v_tender", "v_parent", "v_country", "v_alias", "v_entity",
    "v_entity_party", "v_entity_gleif", "v_resolution",
]


@lru_cache(maxsize=4)
def _engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        from pathlib import Path

        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, future=True)


def get_engine(url: str | None = None) -> Engine:
    return _engine(url or get_settings().staging_url)


def _statements(sql: str) -> Iterable[str]:
    # strip comments first: they may contain ';'
    sql = "\n".join(ln.split("--", 1)[0] for ln in sql.splitlines())
    for stmt in sql.split(";"):
        body = stmt.strip()
        if body:
            yield body


def init_schema(engine: Engine | None = None, reset: bool = False) -> Engine:
    engine = engine or get_engine()
    sql = resources.files("suppliergraph.staging").joinpath("schema.sql").read_text(encoding="utf-8")
    with engine.begin() as conn:
        if reset:
            for v in VIEWS:
                conn.execute(text(f"DROP VIEW IF EXISTS {v}"))
            for t in reversed(TABLES):
                conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
        # views are recreated every time so that mapping changes take effect
        for v in VIEWS:
            conn.execute(text(f"DROP VIEW IF EXISTS {v}"))
        for stmt in _statements(sql):
            conn.execute(text(stmt))
    return engine


def replace_table(engine: Engine, table: str, df: pd.DataFrame, *, truncate: bool = True) -> int:
    """Bulk-load a dataframe into a staging table (columns must match the table)."""
    if df.empty:
        if truncate:
            with engine.begin() as conn:
                conn.execute(text(f"DELETE FROM {table}"))
        return 0
    df = df.astype(object).where(df.notna(), None)
    with engine.begin() as conn:
        if truncate:
            conn.execute(text(f"DELETE FROM {table}"))
        df.to_sql(table, conn, if_exists="append", index=False, method="multi", chunksize=500)
    return len(df)


def read_sql(engine: Engine, sql: str, **params) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or None)


def table_counts(engine: Engine) -> dict[str, int]:
    out = {}
    with engine.connect() as conn:
        for t in TABLES:
            out[t] = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one()
    return out
