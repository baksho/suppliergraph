"""FastAPI service: Ask (GraphRAG), Supplier 360, Discover, Governance, JSON-LD linked data."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..kg import describe
from ..kg.graphview import neighborhood
from ..kg.validate import validate as shacl_validate
from ..llm import LLM, LLMUnavailable, get_llm
from ..namespaces import SPARQL_PREFIX_BLOCK, entity_iri
from ..rag.answer import AnswerEngine
from ..reasoning import dq
from ..store import SparqlStore, open_store

log = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    mode: Literal["graphrag", "vector_rag", "llm_only"] = "graphrag"


class SparqlRequest(BaseModel):
    query: str = Field(max_length=5000)


def create_app(store: SparqlStore | None = None, llm: LLM | None = None, settings: Settings | None = None,
               ui_dir: Path | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="SupplierGraph API", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])
    state: dict = {"store": store, "llm": llm, "engine": None, "recommender": None, "shacl": None}

    def get_store() -> SparqlStore:
        if state["store"] is None:
            state["store"] = open_store(settings)
        return state["store"]

    def get_engine(st: SparqlStore = Depends(get_store)) -> AnswerEngine:
        if state["engine"] is None:
            try:
                state["llm"] = state["llm"] or get_llm()
            except LLMUnavailable as exc:
                raise HTTPException(503, f"LLM not configured: {exc}") from exc
            state["engine"] = AnswerEngine(state["llm"], st)
        return state["engine"]

    def get_recommender(st: SparqlStore = Depends(get_store)):
        if state["recommender"] is None:
            from ..ml.recommend import Recommender

            state["recommender"] = Recommender(st, settings.models_dir / "current")
        return state["recommender"]

    # ------------------------------------------------------------------------- health
    @app.get("/api/health")
    def health(st: SparqlStore = Depends(get_store)):
        try:
            n = st.triple_count()
        except Exception as exc:
            raise HTTPException(503, f"store unavailable: {exc}") from exc
        return {"status": "ok", "triples": n, "store": settings.store_mode,
                "model_artifact": (settings.models_dir / "current" / "model.pt").exists(),
                "llm_configured": state["llm"] is not None or any(__import__("os").environ.get(k) for k in ("ANTHROPIC_API_KEY", "HF_TOKEN", "SG_LLM_BASE_URL"))}

    # --------------------------------------------------------------------------- ask
    @app.post("/api/ask")
    def ask(req: AskRequest, engine: AnswerEngine = Depends(get_engine)):
        t0 = time.time()
        try:
            a = engine.ask(req.question, req.mode)
        except LLMUnavailable as exc:      # provider errors (quota, timeout, bad model id) are not server bugs
            raise HTTPException(503, f"LLM call failed: {exc}") from exc
        except Exception as exc:
            log.exception("ask failed")
            raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc
        out = a.as_dict()
        out["seconds"] = round(time.time() - t0, 2)
        return out

    # ------------------------------------------------------------------- entities
    @app.get("/api/entities/search")
    def search(q: str = Query(min_length=2, max_length=100), limit: int = Query(15, le=50),
               st: SparqlStore = Depends(get_store)):
        return describe.search_entities(st, q, limit)

    @app.get("/api/entities/{key}")
    def entity(key: str, request: Request, st: SparqlStore = Depends(get_store), format: str | None = None):
        try:
            if format == "jsonld" or "application/ld+json" in request.headers.get("accept", ""):
                doc = describe.entity_jsonld(st, key)
                if doc is None:
                    raise HTTPException(404, "unknown entity")
                return JSONResponse(doc, media_type="application/ld+json")
            detail = describe.entity_detail(st, key)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if detail is None:
            raise HTTPException(404, "unknown entity")
        return detail

    @app.get("/api/entities/{key}/contracts")
    def entity_contracts(key: str, st: SparqlStore = Depends(get_store)):
        try:
            return describe.contracts(st, key)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/entities/{key}/graph")
    def entity_graph(key: str, hops: int = Query(2, ge=1, le=3), st: SparqlStore = Depends(get_store)):
        try:
            return neighborhood(st, [entity_iri(describe.safe_key(key))], hops=hops)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/entities/{key}/lineage")
    def entity_lineage(key: str, st: SparqlStore = Depends(get_store)):
        try:
            return describe.lineage(st, key)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ------------------------------------------------------------------- discover
    @app.get("/api/discover/buyers")
    def buyers(st: SparqlStore = Depends(get_store)):
        return st.select(SPARQL_PREFIX_BLOCK + """
            SELECT ?e ?name (COUNT(DISTINCT ?t) AS ?tenders) WHERE { ?t sg:issuedBy ?e . ?e sg:legalName ?name }
            GROUP BY ?e ?name ORDER BY DESC(?tenders) LIMIT 100""")

    @app.get("/api/discover/categories")
    def categories(st: SparqlStore = Depends(get_store)):
        return st.select(SPARQL_PREFIX_BLOCK + """
            SELECT ?c ?code ?label (COUNT(DISTINCT ?t) AS ?tenders) WHERE { ?t sg:hasCategory ?c . ?c skos:notation ?code .
              OPTIONAL { ?c skos:prefLabel ?label . FILTER(LANG(?label) = "en") } }
            GROUP BY ?c ?code ?label ORDER BY DESC(?tenders) LIMIT 100""")

    @app.get("/api/discover/suppliers")
    def discover(buyer: str | None = None, category: str | None = None, k: int = Query(10, le=50),
                 rec=Depends(get_recommender)):
        if bool(buyer) == bool(category):
            raise HTTPException(400, "give exactly one of buyer or category (IRIs)")
        return rec.for_buyer(buyer, k) if buyer else rec.for_category(category, k)

    # ----------------------------------------------------------------- governance
    @app.get("/api/governance/shacl")
    def shacl(refresh: bool = False, st: SparqlStore = Depends(get_store)):
        if refresh or state["shacl"] is None:
            state["shacl"] = shacl_validate(st)
        return state["shacl"]

    @app.get("/api/governance/dq")
    def dq_checks(st: SparqlStore = Depends(get_store)):
        return {"summary": dq.summary(st), "checks": dq.run_checks(st)}

    @app.get("/api/governance/er")
    def er_stats():
        from ..staging.db import get_engine, read_sql

        out: dict = {}
        try:
            eng = get_engine(settings.staging_url)
            df = read_sql(eng, "SELECT status, method, COUNT(*) AS n FROM party_resolution GROUP BY status, method")
            out["parties"] = df.to_dict("records")
            out["sanction_matches"] = read_sql(
                eng, "SELECT review_status, COUNT(*) AS n FROM sanction_match GROUP BY review_status").to_dict("records")
        except Exception as exc:
            out["staging_unavailable"] = str(exc)[:200]
        for name in ("er_eval", "cpv_eval"):
            p = settings.data_dir / f"{name}.json"
            if p.exists():
                out[name] = json.loads(p.read_text())
        return out

    @app.get("/api/governance/products")
    def products(st: SparqlStore = Depends(get_store)):
        return st.select(SPARQL_PREFIX_BLOCK + """
            SELECT ?dp ?title ?description ?note ?modified WHERE { ?dp a sg:DataProduct ; dcterms:title ?title .
              OPTIONAL { ?dp dcterms:description ?description } OPTIONAL { ?dp sg:sourceNote ?note }
              OPTIONAL { ?dp dcterms:modified ?modified } } ORDER BY ?title""")

    @app.get("/api/models")
    def model_metrics():
        for p in (settings.models_dir / "current" / "metrics.json", settings.models_dir / "metrics.json"):
            if p.exists():
                return json.loads(p.read_text())
        raise HTTPException(404, "no metrics yet: run `sg train`")

    @app.post("/api/sparql")
    def raw_sparql(req: SparqlRequest, st: SparqlStore = Depends(get_store)):
        if not settings.allow_raw_sparql:
            raise HTTPException(403, "raw SPARQL is disabled (set SG_ALLOW_RAW_SPARQL=1 for trusted deployments)")
        from ..rag.text2sparql import QueryError, validate_query

        try:
            q, kind = validate_query(req.query)
        except QueryError as exc:
            raise HTTPException(400, str(exc)) from exc
        if kind != "select":
            raise HTTPException(400, "only SELECT is supported here")
        return {"rows": st.select(q, timeout=30)}

    # ------------------------------------------------------------------ static UI
    ui_dist = ui_dir or settings.root / "ui" / "dist"
    if ui_dist.exists():
        app.mount("/assets", StaticFiles(directory=ui_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = ui_dist / path
            return FileResponse(f if f.is_file() else ui_dist / "index.html")

    return app


def app_factory() -> FastAPI:        # uvicorn --factory suppliergraph.api.main:app_factory
    return create_app()
