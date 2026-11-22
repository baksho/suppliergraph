"""Runtime configuration, all overridable through environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(os.environ.get("SG_ROOT", Path(__file__).resolve().parents[2]))


@dataclass
class Settings:
    root: Path = ROOT
    data_dir: Path = field(default_factory=lambda: ROOT / "data")
    models_dir: Path = field(default_factory=lambda: ROOT / "models")
    # Relational staging area. SQLite for local development, PostgreSQL in docker-compose.
    staging_url: str = field(
        default_factory=lambda: os.environ.get("SG_STAGING_URL", f"sqlite:///{ROOT / 'data' / 'staging.db'}")
    )
    # Knowledge-graph store: "local" (rdflib, persisted as N-Quads) or "remote" (SPARQL endpoint).
    store_mode: str = field(default_factory=lambda: os.environ.get("SG_STORE", "local"))
    local_kg_path: Path = field(default_factory=lambda: ROOT / "data" / "kg.nq")
    sparql_query_url: str = field(default_factory=lambda: os.environ.get("SG_SPARQL_QUERY_URL", ""))
    sparql_update_url: str = field(default_factory=lambda: os.environ.get("SG_SPARQL_UPDATE_URL", ""))
    sparql_statements_url: str = field(default_factory=lambda: os.environ.get("SG_SPARQL_STATEMENTS_URL", ""))
    # LLM
    llm_model: str = field(default_factory=lambda: os.environ.get("SG_LLM_MODEL", "claude-sonnet-5-5"))
    allow_raw_sparql: bool = field(default_factory=lambda: os.environ.get("SG_ALLOW_RAW_SPARQL", "0") == "1")
    # Thresholds
    er_accept: float = field(default_factory=lambda: float(os.environ.get("SG_ER_ACCEPT", "0.88")))
    er_review: float = field(default_factory=lambda: float(os.environ.get("SG_ER_REVIEW", "0.75")))
    sanction_threshold: float = field(default_factory=lambda: float(os.environ.get("SG_SANCTION_THRESHOLD", "0.90")))

    @property
    def ontology_path(self) -> Path:
        return self.root / "ontology" / "suppliergraph.ttl"

    @property
    def shapes_path(self) -> Path:
        return self.root / "shapes" / "suppliergraph.shapes.ttl"

    @property
    def mapping_path(self) -> Path:
        return self.root / "mappings" / "suppliergraph.r2rml.ttl"

    @property
    def sources_config(self) -> Path:
        return self.root / "config" / "sources.yaml"


def get_settings() -> Settings:
    return Settings()
