import json

from suppliergraph.er.evaluate import evaluate
from suppliergraph.er.matcher import NameMatcher
from suppliergraph.er.normalize import normalize_name
from suppliergraph.extract import cpv_linker
from suppliergraph.extract.obligations import extract_regulation, split_articles
from suppliergraph.extract.standards import extract_standards
from suppliergraph.ingest.common import lei_valid, norm_country
from suppliergraph.ingest.cpv import normalize_code, parent_code
from suppliergraph.llm import ScriptedLLM
from suppliergraph.staging.db import get_engine, read_sql


def test_normalize_name():
    a = normalize_name("Müller & Söhne GmbH & Co. KG")
    assert a.core == "mueller soehne"
    assert {"gmbh", "kg"} <= set(a.forms)
    assert normalize_name("MUELLER UND SOEHNE GMBH").core == "mueller soehne"


def test_lei_and_country_helpers():
    assert lei_valid("TEST00RW000000000005")
    assert not lei_valid("TEST00RW000000000006")
    assert norm_country("Deutschland") == "DE" and norm_country("fr") == "FR" and norm_country("Atlantis") is None


def test_cpv_hierarchy():
    assert normalize_code("30200000-1") == "30200000"
    assert parent_code("72200000") == "72000000"
    assert parent_code("72000000") is None
    assert parent_code("45233120") == "45233100"


def test_matcher_fuzzy_and_country_block():
    m = NameMatcher(["1", "2", "3"], ["Alster Logistik AG", "Alster Logistik Ltd", "Isar Digital SE"],
                    [{"DE"}, {"GB"}, {"DE"}])
    best = m.best("ALSTER LOGISTIK Aktiengesellschaft", "DE")
    assert best[0].target_id == "1"
    # country block: a GB-registered twin is not a candidate for a DE query
    assert all(c.target_id != "2" for c in best)


def test_er_resolved_fixture_parties(built):
    settings, store, _ = built
    eng = get_engine(settings.staging_url)
    df = read_sql(eng, "SELECT status, method, COUNT(*) AS n FROM party_resolution GROUP BY status, method")
    got = {(r.status, r.method): r.n for r in df.itertuples()}
    assert got.get(("accepted", "identifier"), 0) > 0
    assert got.get(("accepted", "fuzzy"), 0) > 0       # identifier-less variants matched by name


def test_er_identifier_masked_evaluation(built):
    settings, _, _ = built
    rep = evaluate(get_engine(settings.staging_url))
    assert rep["n"] >= 3
    best = max(rep["curve"], key=lambda r: r["f1"])
    assert best["precision"] >= 0.9 and best["recall"] >= 0.8


def test_cpv_linker_and_evaluation(built):
    settings, _, _ = built
    eng = get_engine(settings.staging_url)
    rep = cpv_linker.evaluate_linker(eng, k=3, level=3)
    assert rep["n"] > 0 and rep["top3"] >= 0.7
    n = cpv_linker.link_tenders(eng)
    assert n >= 0


def test_standards_regex():
    found = dict(extract_standards("Nachweis nach ISO 9001 und ISO/IEC 27001:2022 sowie DIN EN 1090 erforderlich"))
    assert {"ISO 9001", "ISO/IEC 27001:2022", "DIN EN 1090"} <= set(found)


REG = open(__file__.replace("test_er_extract.py", "fixtures/regulation/test_regulation.txt"), encoding="utf-8").read()


def test_obligation_extraction_keeps_only_verbatim_sentences(built):
    settings, _, _ = built
    eng = get_engine(settings.staging_url)
    arts = dict(split_articles(REG))
    assert set(arts) == {"1", "2", "3"}
    good1 = "Contracting authorities shall publish every award notice within thirty days of the award decision."
    good2 = "Suppliers shall document the results of each assessment and make them available on request."

    def script(system, prompt):
        if 'Article 1 ' in prompt:
            return json.dumps({"obligations": [
                {"sentence": good1, "applies_to": "buyer"},
                {"sentence": "Authorities must always publish within a week.", "applies_to": "buyer"},   # hallucinated
            ]})
        if 'Article 2 ' in prompt:
            return "Sure! " + json.dumps({"obligations": [{"sentence": good2, "applies_to": "supplier"}]})
        return json.dumps({"obligations": []})

    llm = ScriptedLLM(script, name="scripted-test")
    res = extract_regulation(eng, llm, "TEST-REG", "Test Regulation", REG)
    assert res["kept"] == 2 and res["rejected"] == 1
    rows = read_sql(eng, "SELECT text, applies_to_role FROM obligation WHERE reg_id='TEST-REG'")
    assert set(rows["applies_to_role"]) == {"buyer", "supplier"}
