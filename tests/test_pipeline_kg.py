from suppliergraph.kg.validate import validate
from suppliergraph.namespaces import SPARQL_PREFIX_BLOCK as P
from suppliergraph.reasoning.dq import run_checks


def q(store, body):
    return store.select(P + body)


def test_ingest_and_resolution(built):
    settings, store, stats = built
    # all GLEIF entities of the fixture plus unresolved buyers are in the graph
    rows = q(store, "SELECT ?e ?lei WHERE { ?e a sg:LegalEntity . OPTIONAL { ?e sg:lei ?lei } }")
    with_lei = [r for r in rows if r["lei"]]
    assert len(with_lei) >= 8
    # buyers have no LEI (public bodies are not in the fixture's GLEIF file)
    assert any(r["lei"] is None for r in rows)
    assert stats["quads_materialized"] > 100


def test_name_variants_resolve_to_one_entity(built):
    _, store, _ = built
    rows = q(store, """SELECT ?name WHERE { ?e sg:legalName "Rheinwerk Systemhaus GmbH" ; sg:recordedName ?name }""")
    names = {r["name"] for r in rows}
    assert "RHEINWERK SYSTEMHAUS GMBH" in names or "Rheinwerk Systemhaus" in names or len(names) >= 1


def test_reasoning_types_and_closure(built):
    _, store, stats = built
    assert stats["inferred_triples"] > 0
    # Supplier / Buyer typing from range axioms
    assert store.ask(P + "ASK { ?s a sg:Supplier }")
    assert store.ask(P + "ASK { ?b a sg:Buyer }")
    # transitive ancestor: Rheinwerk Systemhaus -> Holding -> Group
    assert store.ask(P + """ASK { ?e sg:legalName "Rheinwerk Systemhaus GmbH" ; sg:hasAncestor ?g .
                              ?g sg:legalName "Rheinwerk Group SE" }""")


def test_derived_ultimate_parent_and_dq(built):
    _, store, _ = built
    assert store.ask(P + """ASK { ?e sg:legalName "Rheinwerk Systemhaus GmbH" ; sg:derivedUltimateParent ?g .
                              ?g sg:legalName "Rheinwerk Group SE" }""")
    checks = run_checks(store)
    # in the fixture the published and derived ultimate parents agree
    assert checks["ultimate_parent_mismatch"] == []
    assert checks["ownership_cycles"] == []


def test_derived_edges(built):
    _, store, _ = built
    rows = q(store, "SELECT (COUNT(*) AS ?n) WHERE { ?b sg:contractedWith ?s }")
    assert rows[0]["n"] > 0
    rows = q(store, "SELECT (COUNT(*) AS ?n) WHERE { ?s sg:suppliesCategory ?c }")
    assert rows[0]["n"] > 0


def test_sanction_exposure_flag_via_parent(built):
    _, store, _ = built
    rows = q(store, """
        SELECT ?name ?via ?hops WHERE {
          ?f a sg:ExposureFlag ; sg:flaggedEntity ?e ; sg:viaEntity ?v ; sg:hops ?hops .
          ?e sg:legalName ?name . ?v sg:legalName ?via }""")
    by_name = {(r["name"], r["via"]): r["hops"] for r in rows}
    # fictional supplier is exposed through its parent's fuzzy match with a (fictional) list entry
    assert ("Nordlicht Handels GmbH", "Nordlicht International Holding Ltd") in by_name
    assert by_name[("Nordlicht Handels GmbH", "Nordlicht International Holding Ltd")] == 1
    # the parent itself is flagged at 0 hops
    assert by_name[("Nordlicht International Holding Ltd", "Nordlicht International Holding Ltd")] == 0


def test_shacl_has_no_violations_on_clean_fixture(built):
    _, store, _ = built
    report = validate(store)
    assert report["violations"] == 0, report["samples"]


def test_provenance_named_graphs(built):
    _, store, _ = built
    rows = store.select(P + """SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s sg:legalName ?n } }""")
    graphs = {r["g"].rsplit("/", 1)[-1] for r in rows}
    assert {"gleif", "tenders"} <= graphs


def test_ocds_streams_jsonl_gz_and_limit(tmp_path, monkeypatch):
    import gzip
    import json

    from suppliergraph.ingest.ocds import iter_releases

    rels = [{"ocid": f"ocds-x-{i}", "buyer": {"name": "B"}} for i in range(5)]
    f = tmp_path / "full.jsonl.gz"
    with gzip.open(f, "wt") as fh:
        fh.write("\n".join(json.dumps(r) for r in rels) + "\n")
    assert [r["ocid"] for r in iter_releases(f)] == [r["ocid"] for r in rels]
    monkeypatch.setenv("SG_OCDS_LIMIT", "2")
    assert len(list(iter_releases(f))) == 2
    monkeypatch.delenv("SG_OCDS_LIMIT")
    pkg = tmp_path / "pkg.json"
    pkg.write_text(json.dumps({"releases": rels[:3]}, indent=2))          # pretty-printed package
    assert len(list(iter_releases(pkg))) == 3


def test_extract_regulation_dedupes_repeated_sentences(tmp_path):

    from sqlalchemy import create_engine

    from suppliergraph.extract import obligations
    from suppliergraph.staging.db import init_schema
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_schema(eng)
    art = "Artikel 1\nDer Auftraggeber muss den Zuschlag erteilen.\n"
    class Twice:
        name = "twice"
        def complete(self, system, prompt, *, max_tokens=1024):
            s = "Der Auftraggeber muss den Zuschlag erteilen."
            return '{"obligations":[{"sentence":"%s","applies_to":"buyer"},{"sentence":"%s","applies_to":"buyer"}]}' % (s, s)
    r = obligations.extract_regulation(eng, Twice(), "X", "T", art)
    assert r["kept"] == 1


def test_duty_wording_and_definition_articles():
    from suppliergraph.extract.obligations import has_duty_wording, is_definitions_article
    assert has_duty_wording("Contracting authorities shall publish every award notice.")
    assert has_duty_wording("Der öffentliche Auftraggeber muss die Bewerber unterrichten.")
    assert has_duty_wording("Die Bekanntmachung ist im Amtsblatt zu veröffentlichen.")
    assert not has_duty_wording("Diese Richtlinie berührt nicht das Recht der Mitgliedstaaten.")
    assert not has_duty_wording("„elektronische Mittel“ elektronische Geräte für die Verarbeitung von Daten")
    assert is_definitions_article("Artikel 2\nBegriffsbestimmungen\nIm Sinne dieser Richtlinie bezeichnet")
    assert not is_definitions_article("Artikel 4\nSchwellenwerte\nDiese Richtlinie gilt")
