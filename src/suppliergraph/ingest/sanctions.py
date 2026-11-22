"""Sanction / watch-list loader (OpenSanctions 'simple' CSV layout, configurable)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..staging.db import replace_table


def load_sanctions(engine, path: Path, columns: dict[str, str], schemas: list[str]) -> int:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [v for k, v in columns.items() if v not in raw.columns and k != "dataset"]
    if missing:
        raise ValueError(f"sanctions file lacks columns {missing}; fix config/sources.yaml")
    if schemas:
        raw = raw[raw[columns["schema"]].isin(schemas)]
    df = pd.DataFrame({
        "entry_id": raw[columns["id"]],
        "name": raw[columns["name"]].str.strip(),
        "aliases": raw[columns["aliases"]] if columns["aliases"] in raw.columns else None,
        "countries": raw[columns["countries"]] if columns["countries"] in raw.columns else None,
        "dataset": raw[columns["dataset"]] if columns.get("dataset") in raw.columns else None,
        "schema_type": raw[columns["schema"]],
    })
    df = df[(df["name"] != "") & (df["entry_id"] != "")].drop_duplicates("entry_id")
    return replace_table(engine, "sanction_entry", df)
