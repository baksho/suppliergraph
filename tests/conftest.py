"""Shared fixtures: a fully built knowledge graph over the TEST-ONLY fixture files."""
from __future__ import annotations

from pathlib import Path

import pytest

from suppliergraph.config import Settings
from suppliergraph.ingest.common import load_sources
from suppliergraph.kg.build import build_kg
from suppliergraph.llm import ScriptedLLM
from suppliergraph.pipeline import extract_all, ingest_all, resolve_all
from suppliergraph.store.local import LocalStore

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixture_sources() -> dict:
    cfg = load_sources()
    cfg["gleif"].update(level1_path=str(FIX / "gleif/level1.csv"), level2_path=str(FIX / "gleif/level2.csv"),
                        countries=None)
    cfg["cpv"]["path"] = str(FIX / "cpv/cpv.csv")
    cfg["ocds"]["paths"] = [str(FIX / "ocds")]
    cfg["sanctions"]["path"] = str(FIX / "sanctions/targets.simple.csv")
    return cfg


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> Settings:
    tmp = tmp_path_factory.mktemp("sg")
    s = Settings()
    s.staging_url = f"sqlite:///{tmp / 'staging.db'}"
    s.local_kg_path = tmp / "kg.nq"
    s.data_dir = tmp
    s.models_dir = tmp / "models"
    return s


@pytest.fixture(scope="session")
def built(settings, fixture_sources):
    """(settings, store, stats): staging DB loaded, parties resolved, KG materialised and reasoned."""
    ingest_all(settings, fixture_sources)
    resolve_all(settings, fixture_sources)
    reg = FIX / "regulation/test_regulation.txt"
    g1 = "Contracting authorities shall publish every award notice within thirty days of the award decision."
    g2 = "Suppliers shall document the results of each assessment and make them available on request."
    import json as _json

    def script(system, prompt):
        if "Article 1 " in prompt:
            return _json.dumps({"obligations": [{"sentence": g1, "applies_to": "buyer"}]})
        if "Article 2 " in prompt:
            return _json.dumps({"obligations": [{"sentence": g2, "applies_to": "supplier"}]})
        return _json.dumps({"obligations": []})

    extract_all(settings, ScriptedLLM(script, name="scripted-fixture"),
                [{"id": "TEST-REG", "title": "Test Regulation", "path": str(reg)}])
    store = LocalStore()
    stats = build_kg(store, settings, persist=True)
    return settings, store, stats
