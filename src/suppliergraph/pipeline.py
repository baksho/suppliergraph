"""Orchestration of the batch pipeline (also used by the CLI and by the integration tests)."""
from __future__ import annotations

import logging

from .config import Settings, get_settings
from .er import resolve as er
from .ingest import cpv as cpv_mod
from .ingest import gleif as gleif_mod
from .ingest import ocds as ocds_mod
from .ingest import sanctions as sanctions_mod
from .ingest.common import load_sources, resolve_path
from .staging.db import get_engine, init_schema, table_counts

log = logging.getLogger(__name__)


def ingest_all(settings: Settings | None = None, sources: dict | None = None, *, reset: bool = True,
               gleif_countries: list[str] | None = None) -> dict:
    """Load all configured sources into the staging DB. Missing optional sources are skipped."""
    settings = settings or get_settings()
    cfg = sources or load_sources(settings.sources_config)
    engine = init_schema(get_engine(settings.staging_url), reset=reset)
    done: dict = {}

    cpv_path = resolve_path(cfg["cpv"]["path"])
    if cpv_path.exists():
        done["cpv"] = cpv_mod.load_cpv(engine, cpv_path, cfg["cpv"]["columns"])
    g = cfg["gleif"]
    l1 = resolve_path(g["level1_path"])
    if l1.exists():
        countries = gleif_countries if gleif_countries is not None else g.get("countries")
        done["gleif_entity"] = gleif_mod.load_level1(engine, l1, g["level1_columns"], countries)
        l2 = resolve_path(g["level2_path"])
        if l2.exists():
            from .staging.db import read_sql

            keep = set(read_sql(engine, "SELECT lei FROM gleif_entity")["lei"])
            done["gleif_relationship"] = gleif_mod.load_level2(
                engine, l2, g["level2_columns"], g["level2_type_map"], keep_leis=keep
            )
    paths = [resolve_path(p) for p in cfg["ocds"]["paths"] if resolve_path(p).exists()]
    if paths:
        done["ocds"] = ocds_mod.load_ocds(engine, paths, cfg["ocds"].get("source_name", "ocds"))
    s = cfg["sanctions"]
    sp = resolve_path(s["path"])
    if sp.exists():
        done["sanction_entry"] = sanctions_mod.load_sanctions(engine, sp, s["columns"], s.get("schemas", []))
    return done


def resolve_all(settings: Settings | None = None, sources: dict | None = None, scorer=None,
                prune_scope: bool = True) -> dict:
    settings = settings or get_settings()
    cfg = sources or load_sources(settings.sources_config)
    engine = get_engine(settings.staging_url)
    out: dict = {}
    res = er.resolve_parties(engine, cfg["ocds"].get("lei_scheme", "XI-LEI"), settings, scorer)
    out["parties"] = res["status"].value_counts().to_dict()
    if prune_scope:
        out["scope_entities"] = er.build_scope(engine)
    out["sanction_matches"] = er.resolve_sanctions(engine, settings, scorer)
    return out


def counts(settings: Settings | None = None) -> dict:
    return table_counts(get_engine((settings or get_settings()).staging_url))


def extract_all(settings: Settings | None = None, llm=None, regulations: list[dict] | None = None) -> dict:
    """Text extraction: CPV linking and standards (no LLM needed), obligations (LLM) per regulation file."""
    from .extract import cpv_linker, obligations, standards

    settings = settings or get_settings()
    engine = get_engine(settings.staging_url)
    out: dict = {"linked_cpv": cpv_linker.link_tenders(engine), "standards": standards.extract_all(engine)}
    for reg in regulations or []:
        path = resolve_path(reg["path"])
        if llm is None or not path.exists():
            out[reg["id"]] = "skipped (no LLM configured or file missing)"
            continue
        out[reg["id"]] = obligations.extract_regulation(
            engine, llm, reg["id"], reg["title"], path.read_text(encoding="utf-8"), reg.get("celex"), reg.get("url"))
    return out


def load_regulations(settings: Settings | None = None) -> list[dict]:
    import yaml

    settings = settings or get_settings()
    p = settings.root / "config" / "regulations.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("regulations", []) if p.exists() else []
