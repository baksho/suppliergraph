"""`sg data check`: compare a real file's header with the configured column names."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .common import load_sources, resolve_path


def check_csv(source: str, path: Path | None = None) -> dict:
    cfg = load_sources()
    if source == "gleif1":
        path = path or resolve_path(cfg["gleif"]["level1_path"])
        wanted = cfg["gleif"]["level1_columns"]
    elif source == "gleif2":
        path = path or resolve_path(cfg["gleif"]["level2_path"])
        wanted = cfg["gleif"]["level2_columns"]
    elif source == "cpv":
        path = path or resolve_path(cfg["cpv"]["path"])
        wanted = {k: v for k, v in cfg["cpv"]["columns"].items() if v}
    elif source == "sanctions":
        path = path or resolve_path(cfg["sanctions"]["path"])
        wanted = cfg["sanctions"]["columns"]
    else:
        raise ValueError("source must be one of gleif1, gleif2, cpv, sanctions")
    if not Path(path).exists():
        return {"file": str(path), "exists": False, "missing": list(wanted.values()), "found": []}
    header = pd.read_csv(path, nrows=0, dtype=str).columns.tolist()
    missing = {k: v for k, v in wanted.items() if v not in header}
    close = {}
    for k, v in missing.items():
        cands = [h for h in header if v.lower().split(".")[-1] in h.lower()]
        if cands:
            close[k] = cands[:5]
    return {"file": str(path), "exists": True, "n_columns": len(header), "missing": missing, "suggestions": close}


def check_ocds(path: Path, sample: int = 200) -> dict:
    """Run the real loader's reader over the first releases and report which fields it will find."""
    from itertools import islice

    from .ocds import iter_releases

    rels = list(islice(iter_releases(Path(path)), sample))
    if not rels:
        return {"ok": False, "reason": "no releases found; is this OCDS (release package, record package, JSONL)?"}

    def frac(f):
        return round(sum(1 for r in rels if f(r)) / len(rels), 2)

    return {"ok": True, "sampled_releases": len(rels), "ocid": frac(lambda r: "ocid" in r),
            "buyer": frac(lambda r: "buyer" in r), "parties": frac(lambda r: bool(r.get("parties"))),
            "awards": frac(lambda r: bool(r.get("awards"))),
            "tender_items": frac(lambda r: bool((r.get("tender") or {}).get("items"))),
            "award_suppliers": frac(lambda r: any(a.get("suppliers") for a in r.get("awards", [])))}
