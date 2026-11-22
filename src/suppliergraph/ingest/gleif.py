"""GLEIF (LEI) loaders: Level 1 (entities) and Level 2 (consolidation relationships)."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from ..staging.db import replace_table
from .common import lei_valid


class MissingColumns(ValueError):
    pass


def _require(df_cols: Iterable[str], wanted: dict[str, str], what: str) -> None:
    missing = [f"{k} -> {v!r}" for k, v in wanted.items() if v not in set(df_cols)]
    if missing:
        raise MissingColumns(
            f"{what}: columns not found in file: {', '.join(missing)}. "
            "Fix config/sources.yaml (see `sg data check`)."
        )


def load_level1(engine, path: Path, columns: dict[str, str], countries: list[str] | None = None,
                chunksize: int = 200_000) -> int:
    """Load LEI records, optionally restricted to a set of legal-address countries."""
    parts = []
    _require(pd.read_csv(path, nrows=0).columns, columns, "GLEIF level 1")      # also reads .zip / .gz directly
    for chunk in pd.read_csv(path, dtype=str, chunksize=chunksize, keep_default_na=False, usecols=list(columns.values())):
        out = pd.DataFrame({
            "lei": chunk[columns["lei"]].str.strip().str.upper(),
            "legal_name": chunk[columns["legal_name"]].str.strip(),
            "legal_country": chunk[columns["legal_country"]].str.strip().str.upper(),
            "legal_jurisdiction": chunk[columns["legal_jurisdiction"]].str.strip(),
            "status": chunk[columns["status"]].str.strip(),
            "category": chunk[columns["category"]].str.strip(),
        })
        out = out[(out["lei"] != "") & (out["legal_name"] != "")]
        if countries:
            out = out[out["legal_country"].isin([c.upper() for c in countries])]
        parts.append(out)
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if df.empty:
        return replace_table(engine, "gleif_entity", df)
    df = df.drop_duplicates("lei")
    df["legal_country"] = df["legal_country"].replace("", None)
    return replace_table(engine, "gleif_entity", df)


def load_level2(engine, path: Path, columns: dict[str, str], type_map: dict[str, str],
                keep_leis: set[str] | None = None, chunksize: int = 500_000) -> int:
    parts = []
    _require(pd.read_csv(path, nrows=0).columns, columns, "GLEIF level 2")
    for chunk in pd.read_csv(path, dtype=str, chunksize=chunksize, keep_default_na=False, usecols=list(columns.values())):
        out = pd.DataFrame({
            "child_lei": chunk[columns["child"]].str.strip().str.upper(),
            "parent_lei": chunk[columns["parent"]].str.strip().str.upper(),
            "rel_type": chunk[columns["type"]].map(type_map),
            "status": chunk[columns["status"]].str.strip(),
        })
        out = out[out["rel_type"].notna()]
        if keep_leis is not None:
            out = out[out["child_lei"].isin(keep_leis) & out["parent_lei"].isin(keep_leis)]
        parts.append(out)
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not df.empty:
        df = df.drop_duplicates(["child_lei", "parent_lei", "rel_type"])
    return replace_table(engine, "gleif_relationship", df)


def invalid_leis(engine) -> list[str]:
    """Data-quality helper: LEIs in the staging table that fail the ISO 7064 check."""
    from ..staging.db import read_sql

    df = read_sql(engine, "SELECT lei FROM gleif_entity")
    return [x for x in df["lei"].tolist() if not lei_valid(x)]
