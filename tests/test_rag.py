import re

import pytest

from suppliergraph.eval.run import load_questions, resolve_slots, run_eval
from suppliergraph.llm import ScriptedLLM
from suppliergraph.namespaces import SPARQL_PREFIX_BLOCK as P
from suppliergraph.rag import factcheck
from suppliergraph.rag.answer import AnswerEngine
from suppliergraph.rag.text2sparql import QueryError, extract_query, validate_query


def test_validate_query_rejects_updates_unknown_terms_and_bad_syntax():
    with pytest.raises(QueryError):
        validate_query("DELETE WHERE { ?s ?p ?o }")
    with pytest.raises(QueryError, match="Unknown schema term"):
        validate_query("SELECT ?x WHERE { ?x sg:buyerOf ?y }")
    with pytest.raises(QueryError, match="syntax"):
        validate_query("SELECT ?x WHERE { ?x sg:awardedTo }")
    q, kind = validate_query("SELECT ?x WHERE { ?x a sg:Tender }")
    assert kind == "select" and "LIMIT" in q
    assert extract_query("blah ```sparql\nSELECT * WHERE {?s ?p ?o}\n``` bye") == "SELECT * WHERE {?s ?p ?o}"


def test_factcheck_flags_unsupported_numbers_entities_and_bad_citations():
    ev = {"R1": "name=Alster Logistik AG; total=125,000.50", "R2": "name=Isar Digital SE"}
    labels = factcheck.LabelIndex(["Alster Logistik AG", "Isar Digital SE", "Spree Reinigung GmbH"])
    good = factcheck.check("Alster Logistik AG received 125,000.50 [R1].", ev, labels)
    assert good.grounded and good.citation_coverage == 1.0
    bad = factcheck.check("Spree Reinigung GmbH received 999 [R9]. Isar Digital SE also.", ev, labels)
    assert not bad.grounded
    assert "R9" in bad.invalid_citations and "999" in bad.unsupported_numbers
    assert "Spree Reinigung GmbH" in bad.unsupported_entities
    assert len(bad.uncited_sentences) == 1


def _engine(store, script):
    return AnswerEngine(ScriptedLLM(script), store)


def test_repair_loop_fixes_hallucinated_property(built):
    _, store, _ = built
    attempts = []

    def script(system, prompt):
        if "SCHEMA" in prompt:
            attempts.append(prompt)
            if len(attempts) == 1:
                return "```sparql\nSELECT ?b WHERE { ?b sg:buyerOf ?t }\n```"
            assert "Unknown schema term" in prompt          # the error is fed back to the model
            return "```sparql\nSELECT (COUNT(DISTINCT ?t) AS ?n) WHERE { ?t a sg:Tender }\n```"
        n = re.search(r"n=(\d+)", prompt).group(1)
        return f"There are {n} tenders [R1]."

    eng = _engine(store, script)
    ans = eng.graphrag("How many tenders are there?")
    assert ans.query_ok and len(ans.attempts) == 2 and ans.attempts[0]["error"]
    assert ans.grounding["grounded"], ans.grounding


def test_graphrag_flags_hallucinated_number(built):
    _, store, _ = built

    def script(system, prompt):
        if "SCHEMA" in prompt:
            return "```sparql\nSELECT (COUNT(DISTINCT ?t) AS ?n) WHERE { ?t a sg:Tender }\n```"
        return "There are 12345 tenders [R1]."          # wrong number, right citation

    ans = _engine(store, script).graphrag("How many tenders are there?")
    assert not ans.grounding["grounded"] and "12345" in ans.grounding["unsupported_numbers"]


def test_llm_only_has_no_evidence_and_is_flagged(built):
    _, store, _ = built
    ans = _engine(store, lambda s, p: "Alster Logistik AG won 3 contracts.").llm_only("Who won contracts?")
    assert not ans.grounding["grounded"]


def test_all_gold_queries_execute_and_slots_resolve(built):
    _, store, _ = built
    spec = load_questions()
    slots = resolve_slots(store, spec)
    assert all(v for v in slots.values()), slots
    for q in spec["questions"]:
        gold = q["gold"]
        for s in q.get("slots", []):
            gold = gold.replace(f"{{{s}}}", slots[s])
        rows = store.select(P + gold)               # must at least execute
        assert isinstance(rows, list), q["id"]


def test_eval_harness_end_to_end_with_oracle_llm(built):
    """An 'oracle' LLM that returns the gold query: the harness must report perfect execution accuracy."""
    _, store, _ = built
    spec = load_questions()
    slots = resolve_slots(store, spec)
    by_question = {}
    for q in spec["questions"]:
        text, gold = q["question"], q["gold"]
        for s in q.get("slots", []):
            text, gold = text.replace(f"{{{s}}}", slots[s]), gold.replace(f"{{{s}}}", slots[s])
        by_question[text] = gold

    def oracle(system, prompt):
        if "SCHEMA" in prompt:
            question = prompt.split("QUESTION\n", 1)[1].split("\n")[0]
            return f"```sparql\n{by_question[question]}\n```"
        ev = prompt.split("EVIDENCE\n", 1)[1].split("\n\nQUESTION", 1)[0] if "EVIDENCE" in prompt else ""
        lines = re.findall(r"\[([RFD]\d+)\] (.*)", ev)
        return " ".join(f"{t}. [{i}]" for i, t in lines[:6]) or "I do not know."

    report = run_eval(AnswerEngine(ScriptedLLM(oracle), store))
    g = report["summary"]["graphrag"]
    assert g["valid_query_rate"] == 1.0
    assert g["exec_accuracy"] == 1.0, [r for r in report["results"] if r["system"] == "graphrag" and not r["metrics"]["exec_accuracy"]]
    assert report["summary"]["llm_only"]["grounded_rate"] <= g["grounded_rate"]
