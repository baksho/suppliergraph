"""Build the knowledge graph: R2RML materialisation -> store -> SHACL -> reasoning -> rules."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml
from rdflib import Graph, Literal
from rdflib.namespace import DCTERMS, RDF, XSD

from ..config import Settings, get_settings
from ..namespaces import DP, GRAPH_BASE, SG
from ..reasoning import rules as rules_mod
from ..store.base import SparqlStore

log = logging.getLogger(__name__)
METADATA_GRAPH = f"{GRAPH_BASE}metadata"


def materialize_nquads(settings: Settings, out_file: Path) -> int:
    """Run the R2RML mapping over the staging database with Morph-KGC and write N-Quads."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    config = (
        "[CONFIGURATION]\n"
        "output_format = N-QUADS\n"
        f"output_file = {out_file}\n"
        "logging_level = WARNING\n"
        "[staging]\n"
        f"mappings = {settings.mapping_path}\n"
        f"db_url = {settings.staging_url}\n"
    )
    ini = out_file.with_suffix(".ini")
    ini.write_text(config, encoding="utf-8")
    # the library call returns an in-memory graph; the CLI entry point is the one that writes N-Quads
    proc = subprocess.run([sys.executable, "-W", "ignore", "-m", "morph_kgc", str(ini)],
                          capture_output=True, text=True)
    if proc.returncode != 0 or not out_file.exists():
        raise RuntimeError(f"Morph-KGC failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    with open(out_file, encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def data_product_metadata(settings: Settings) -> Graph:
    cfg = yaml.safe_load((settings.root / "config" / "data_products.yaml").read_text(encoding="utf-8"))
    g = Graph()
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    for p in cfg["products"]:
        iri = DP[p["id"]]
        g.add((iri, RDF.type, SG.DataProduct))
        g.add((iri, DCTERMS.title, Literal(p["title"])))
        g.add((iri, DCTERMS.description, Literal(p["description"])))
        g.add((iri, SG.sourceNote, Literal(p["source_note"])))
        g.add((iri, DCTERMS.modified, Literal(now, datatype=XSD.dateTime)))
    return g


def build_kg(store: SparqlStore, settings: Settings | None = None, *, reason: bool = True,
             run_rules: bool = True, persist: bool = True) -> dict:
    settings = settings or get_settings()
    stats: dict = {}
    store.clear()
    store.load_file(settings.ontology_path, "turtle", graph=rules_mod.ONTOLOGY_GRAPH)
    with tempfile.TemporaryDirectory() as tmp:
        nq = Path(tmp) / "kg.nq"
        stats["quads_materialized"] = materialize_nquads(settings, nq)
        store.load_file(nq, "nquads")
    store.insert_triples(data_product_metadata(settings), METADATA_GRAPH)
    if reason:
        stats["inferred_triples"] = rules_mod.run_owlrl(store)
    if run_rules:
        stats["rules"] = rules_mod.run_rules(store, settings.sanction_threshold)
    stats["triples_total"] = store.triple_count()
    if persist and hasattr(store, "save"):
        store.save(settings.local_kg_path)
    (settings.data_dir).mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "build_stats.json").write_text(json.dumps(stats, indent=2))
    return stats
