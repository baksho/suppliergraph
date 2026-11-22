"""CPV (Common Procurement Vocabulary) loader. The hierarchy is derived from the code structure."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..staging.db import replace_table


def normalize_code(raw: str) -> str | None:
    """'30200000-1' -> '30200000'; returns None if not 8 digits."""
    if raw is None:
        return None
    s = str(raw).strip().split("-")[0].strip()
    return s if len(s) == 8 and s.isdigit() else None


def parent_code(code: str) -> str | None:
    """CPV levels: division XX000000, group XXX00000, class XXXX0000, category XXXXX000, then deeper.

    The parent is obtained by zeroing the last non-zero digit, repeatedly, until it differs.
    Divisions (two significant digits) have no parent.
    """
    digits = list(code)
    # position of the last non-zero digit
    last = max((i for i, c in enumerate(digits) if c != "0"), default=-1)
    if last <= 1:
        return None
    digits[last] = "0"
    return "".join(digits)


def load_cpv(engine, path: Path, columns: dict[str, str]) -> int:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    for key in ("code", "label_en"):
        if columns[key] not in raw.columns:
            raise ValueError(f"CPV file lacks column {columns[key]!r} (configure config/sources.yaml)")
    df = pd.DataFrame({
        "code": raw[columns["code"]].map(normalize_code),
        "label_en": raw[columns["label_en"]].str.strip(),
        "label_de": raw[columns["label_de"]].str.strip() if columns.get("label_de") in raw.columns else None,
    })
    df = df[df["code"].notna()].drop_duplicates("code").reset_index(drop=True)
    known = set(df["code"])
    parents = []
    for c in df["code"]:
        p = parent_code(c)
        # climb until an existing code is found (a few intermediate levels are not listed)
        while p is not None and p not in known:
            p = parent_code(p)
        parents.append(p)
    df["parent_code"] = parents
    df["label_de"] = df["label_de"].replace("", None) if df["label_de"] is not None else None
    return replace_table(engine, "cpv_code", df)
