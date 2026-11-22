"""Open Contracting Data Standard (OCDS) loader: releases -> party / tender / award / tender_cpv."""
from __future__ import annotations

import gzip
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd

from ..staging.db import replace_table
from .common import norm_country, stable_id
from .cpv import normalize_code


def _open(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def _docs(path: Path) -> Iterator[Any]:
    """Yield JSON documents from a file, streaming line by line when it is JSONL (the registry's bulk files are ~0.5 GB)."""
    with _open(path) as fh:
        first = None
        for line in fh:
            if not line.strip():
                continue
            if first is None:
                try:
                    first = json.loads(line)
                except json.JSONDecodeError:         # pretty-printed single document: parse the whole file
                    fh.seek(0)
                    yield json.loads(fh.read())
                    return
                yield first
                continue
            yield json.loads(line)


def iter_releases(path: Path) -> Iterator[dict]:
    """Yield OCDS releases from release packages, record packages, single releases or JSONL (optionally .gz).

    Set SG_OCDS_LIMIT=<n> to stop after n releases (quick dry runs).
    """
    limit = int(os.environ.get("SG_OCDS_LIMIT", "0") or 0)
    n = 0
    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*") if p.is_file() and (p.suffix in {".json", ".jsonl"} or p.name.endswith((".json.gz", ".jsonl.gz")))
    )
    for f in files:
        for doc in _docs(f):
            if isinstance(doc, dict) and "releases" in doc:
                found = doc["releases"]
            elif isinstance(doc, dict) and "records" in doc:
                found = [r["compiledRelease"] if "compiledRelease" in r else r["releases"][-1]
                         for r in doc["records"] if "compiledRelease" in r or r.get("releases")]
            elif isinstance(doc, dict) and "ocid" in doc:
                found = [doc]
            else:
                found = []
            for rel in found:
                yield rel
                n += 1
                if limit and n >= limit:
                    return


def _norm_name(name: str) -> str:
    return " ".join((name or "").casefold().split())


def _date(value: Any) -> str | None:
    return str(value)[:10] if value else None


def _cpvs(node: dict | None) -> set[str]:
    out: set[str] = set()
    if not node:
        return out
    cands = []
    if node.get("classification"):
        cands.append(node["classification"])
    cands.extend(node.get("additionalClassifications") or [])
    for it in node.get("items") or []:
        if it.get("classification"):
            cands.append(it["classification"])
        cands.extend(it.get("additionalClassifications") or [])
    for c in cands:
        if str(c.get("scheme", "")).upper() == "CPV":
            code = normalize_code(c.get("id"))
            if code:
                out.add(code)
    return out


class _Parties:
    def __init__(self, source: str):
        self.source = source
        self.rows: dict[str, dict] = {}

    def register(self, party: dict | None, fallback_name: str | None = None) -> str | None:
        party = party or {}
        ident = party.get("identifier") or {}
        name = party.get("name") or ident.get("legalName") or fallback_name
        if not name:
            return None
        scheme, ident_id = ident.get("scheme"), ident.get("id")
        country = norm_country((party.get("address") or {}).get("countryName"))
        if scheme and ident_id:
            pid = stable_id(self.source, scheme, ident_id)
        else:
            pid = stable_id(self.source, "name", _norm_name(name), country)
        if pid not in self.rows:
            self.rows[pid] = {
                "party_id": pid, "source": self.source, "scheme": scheme,
                "identifier": str(ident_id) if ident_id else None, "name": name.strip(), "country": country,
            }
        return pid


def load_ocds(engine, paths: list[Path], source_name: str = "ocds") -> dict[str, int]:
    parties = _Parties(source_name)
    tenders, awards, tender_cpv = [], [], []
    for path in paths:
        for rel in iter_releases(path):
            ocid = rel.get("ocid")
            if not ocid:
                continue
            by_id = {p.get("id"): p for p in rel.get("parties") or [] if p.get("id") is not None}

            def lookup(ref: dict | None):
                if not ref:
                    return None
                full = by_id.get(ref.get("id"), {})  # noqa: B023 (called within the same iteration)
                merged = {**ref, **full}
                return parties.register(merged, ref.get("name"))

            buyer_pid = lookup(rel.get("buyer"))
            if buyer_pid is None:
                for p in rel.get("parties") or []:
                    if "buyer" in (p.get("roles") or []):
                        buyer_pid = parties.register(p)
                        break
            tender = rel.get("tender") or {}
            tenders.append({
                "tender_id": ocid, "title": tender.get("title"), "description": tender.get("description"),
                "buyer_party_id": buyer_pid, "publication_date": _date(rel.get("date")), "source": source_name,
            })
            codes = _cpvs(tender)
            for award in rel.get("awards") or []:
                codes |= _cpvs(award)
                val = award.get("value") or {}
                for sup in award.get("suppliers") or []:
                    spid = lookup(sup)
                    if spid is None:
                        continue
                    awards.append({
                        "award_id": stable_id(ocid, award.get("id"), spid, prefix="A-"),
                        "tender_id": ocid, "supplier_party_id": spid,
                        "value_amount": val.get("amount"), "currency": val.get("currency"),
                        "award_date": _date(award.get("date") or rel.get("date")),
                    })
            for c in sorted(codes):
                tender_cpv.append({"tender_id": ocid, "cpv_code": c, "source": "declared", "score": None})

    tdf = pd.DataFrame(tenders).drop_duplicates("tender_id") if tenders else pd.DataFrame()
    counts = {
        "party": replace_table(engine, "party", pd.DataFrame(list(parties.rows.values()))),
        "tender": replace_table(engine, "tender", tdf),
        "award": replace_table(engine, "award", pd.DataFrame(awards).drop_duplicates("award_id") if awards else pd.DataFrame()),
    }
    # declared CPV codes only; linked ones are written by the extraction step
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tender_cpv WHERE source = 'declared'"))
    if tender_cpv:
        df = pd.DataFrame(tender_cpv).drop_duplicates(["tender_id", "cpv_code", "source"])
        counts["tender_cpv"] = replace_table(engine, "tender_cpv", df, truncate=False)
    return counts


def lei_hints(engine, lei_scheme: str) -> pd.DataFrame:
    """Parties that carry an LEI in their published identifier (used as labels for ER evaluation)."""
    from ..staging.db import read_sql

    return read_sql(
        engine,
        "SELECT party_id, identifier AS lei FROM party WHERE scheme = :s AND identifier IS NOT NULL",
        s=lei_scheme,
    )
