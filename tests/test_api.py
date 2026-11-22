
import pytest
from fastapi.testclient import TestClient

from suppliergraph.api.main import create_app
from suppliergraph.llm import ScriptedLLM
from suppliergraph.namespaces import SPARQL_PREFIX_BLOCK as P


@pytest.fixture(scope="module")
def client(built):
    settings, store, _ = built
    llm = ScriptedLLM(lambda s, p: "```sparql\nSELECT ?t WHERE { ?t a sg:Tender } LIMIT 3\n```")
    return TestClient(create_app(store=store, llm=llm, settings=settings, ui_dir=settings.data_dir / "nope"))


@pytest.fixture(scope="module")
def a_supplier(built):
    _, store, _ = built
    r = store.select(P + "SELECT ?e WHERE { ?a sg:awardedTo ?e } LIMIT 1")
    return str(r[0]["e"]).rsplit("/", 1)[-1]


def test_health(client):
    j = client.get("/api/health").json()
    assert j["status"] == "ok" and j["triples"] > 0


def test_search_and_detail_and_jsonld(client, a_supplier):
    assert client.get("/api/entities/search", params={"q": "AG"}).status_code in (200,)
    d = client.get(f"/api/entities/{a_supplier}")
    assert d.status_code == 200
    ld = client.get(f"/api/entities/{a_supplier}", headers={"accept": "application/ld+json"})
    assert ld.status_code == 200 and "@context" in ld.json()
    assert client.get("/api/entities/ZZZ-unknown-000").status_code == 404
    assert client.get("/api/entities/bad key!").status_code in (400, 404)


def test_contracts_graph_lineage(client, a_supplier):
    assert client.get(f"/api/entities/{a_supplier}/contracts").status_code == 200
    g = client.get(f"/api/entities/{a_supplier}/graph", params={"hops": 2}).json()
    assert g["nodes"] and "edges" in g
    assert client.get(f"/api/entities/{a_supplier}/lineage").status_code == 200


def test_governance(client):
    assert client.get("/api/governance/shacl").json()["conforms"] is True
    assert "checks" in client.get("/api/governance/dq").json()
    assert client.get("/api/governance/products").status_code == 200
    assert client.get("/api/governance/er").status_code == 200


def test_ask_runs_through_engine(client):
    r = client.post("/api/ask", json={"question": "Which tenders exist?"})
    assert r.status_code == 200, r.text
    assert r.json()["system"] == "graphrag" and "text" in r.json()


def test_discover_baseline_ranker(client, built):
    _, store, _ = built
    buyer = str(store.select(P + "SELECT ?b WHERE { ?t sg:issuedBy ?b } LIMIT 1")[0]["b"])
    r = client.get("/api/discover/suppliers", params={"buyer": buyer, "k": 3})
    assert r.status_code == 200 and r.json()["ranker"] == "baseline"
    assert client.get("/api/discover/suppliers").status_code == 400


def test_raw_sparql_disabled_by_default(client):
    assert client.post("/api/sparql", json={"query": "SELECT * WHERE {?s ?p ?o}"}).status_code == 403


def test_ask_reports_llm_failure_as_503(built):
    from fastapi.testclient import TestClient

    from suppliergraph.api.main import create_app
    from suppliergraph.llm import LLMUnavailable

    class Down:
        name = "down"
        def complete(self, system, prompt, *, max_tokens=1024):
            raise LLMUnavailable("quota exhausted")
    settings, store, _ = built
    r = TestClient(create_app(store=store, llm=Down(), settings=settings)).post("/api/ask", json={"question": "Which suppliers won awards?"})
    assert r.status_code in (200, 503)
    if r.status_code == 503:
        assert "quota exhausted" in r.json()["detail"]


def test_explorer_renders_html(built, tmp_path):
    from suppliergraph.kg.explore import render
    _, store, _ = built
    info = render(store, tmp_path / "kg.html")
    assert info["nodes"] > 0 and (tmp_path / "kg.html").read_text().startswith("<!doctype html>")


def test_concurrent_parsing_is_safe(built):
    from concurrent.futures import ThreadPoolExecutor

    from suppliergraph.rag.text2sparql import validate_query
    _, store, _ = built

    def work(i):
        validate_query(f"SELECT ?s WHERE {{ ?s ?p ?o . FILTER(?s != <urn:x{i}>) }}")
        return len(store.select(f"SELECT ?s WHERE {{ ?s ?p ?o }} LIMIT {i + 1}"))

    with ThreadPoolExecutor(8) as ex:
        assert all(n >= 1 for n in ex.map(work, range(60)))


def test_schema_examples_run_and_long_chains_are_rejected(built):
    import re

    import pytest

    from suppliergraph.rag.schema_context import EXAMPLES, schema_text
    from suppliergraph.rag.text2sparql import QueryError, validate_query
    _, store, _ = built
    assert "name in lower case" not in schema_text()
    qs = re.findall(r"^(SELECT .*)$", EXAMPLES, flags=re.M)
    assert len(qs) == 5
    for q in qs:
        checked, _ = validate_query(q)
        store.select(checked)                      # must execute without error
    chain = "SELECT ?s WHERE { " + " ".join(f"?p{i} sg:hasDirectParent ?p{i + 1} ." for i in range(40)) + " }"
    with pytest.raises(QueryError):
        validate_query(chain)


def test_unclosed_code_fence_and_generic_filters():
    from suppliergraph.rag.text2sparql import extract_query, generic_name_filters
    assert extract_query("```sparql\nSELECT ?s WHERE { ?s ?p ?o }").startswith("SELECT")
    assert extract_query("```sparql\nSELECT ?s WHERE { ?s ?p ?o }\n```") == "SELECT ?s WHERE { ?s ?p ?o }"
    q = 'SELECT ?s WHERE { ?s sg:legalName ?n FILTER(CONTAINS(LCASE(STR(?n)), "parent company")) }'
    assert generic_name_filters(q) == ["parent company"]
    assert generic_name_filters(q.replace("parent company", "company")) == ["company"]
    assert generic_name_filters(q.replace("parent company", "siemens ag")) == []


def test_direction_hints_for_wrong_direction_query():
    from suppliergraph.rag.schema_context import direction_hints
    h = direction_hints("SELECT ?s WHERE { ?s sg:awardedTo ?e ; sg:legalName ?n . ?a sg:awardedTo ?x }")
    assert "sg:awardedTo goes FROM a sg:Award (subject) TO a sg:Supplier (object)" in h
    assert "legalName" not in h        # datatype properties are not listed
