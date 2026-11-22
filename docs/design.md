# Design notes

## Why RDF/OWL (and not a property graph) here
- Open-world integration of independently published sources (GLEIF, tenders, CPV, sanction lists, regulation text) is the
  core problem; global IRIs, named graphs per data product and SHACL fit it directly.
- Standard schema languages: OWL 2 RL for light reasoning, SHACL for closed-world validation, R2RML for relational mapping,
  JSON-LD for API output.
- Trade-off: path-heavy analytics and some graph algorithms are easier in a property graph. A Neo4j mirror was considered and cut
  to keep the project focused; nothing in the design prevents adding one.

## Layers
1. **Staging DB** (SQLAlchemy; SQLite dev, PostgreSQL in docker-compose) holds cleaned source tables, ER results and extractions.
2. **R2RML mapping** (`mappings/`) turns staging *views* into RDF, one named graph per data product. Morph-KGC materialises it.
3. **Reasoning**: owlrl (OWL 2 RL) into an inferred graph; SPARQL CONSTRUCT rules (`sparql/rules/`) into a derived graph.
   Keeping asserted, inferred and derived triples in separate graphs is deliberate: derived facts can be dropped and rebuilt.
4. **Validation**: SHACL shapes (`shapes/`) plus SPARQL data-quality checks (`reasoning/dq.py`).
5. **Serving**: FastAPI + React/Cytoscape UI; GraphRAG over the same store.

## Virtual vs materialised
Materialised (default): simple, fast to query, supports inference and derived rules. Virtual (Ontop over the staging DB, see
`deploy/ontop`): no copy of the data, but no derived triples. Untested here.

## IRI policy
`https://suppliergraph.example/...` is a placeholder namespace; replace it with one you control before publishing. Entity IRIs use
the LEI when known, otherwise a stable hash of source and source identifier. Hashes are not secret and not collision-proof in theory.

## Modelling choices that matter
- Names are kept per source (`recordedName`) next to the preferred `legalName`; no destructive merging.
- Entity resolution output is a scored link with a review status (accept / review / none), never a silent merge.
- A sanction **match** is a scored lead between a company name and a list entry. An **ExposureFlag** is derived from a match
  plus ownership hops. Both are leads for human review, not findings about anyone.
- Functional properties were intentionally not declared (see the comment in the ontology), because source data can disagree.

## Terminology mapping to SAP's public material
Based on public SAP pages read while planning (verify against current SAP documentation before quoting this in an application):
SAP HANA Cloud's knowledge graph engine (RDF store, SPARQL, SPARQL_TABLE for mixed SQL/SPARQL, OWL 2 RL inference) and the
Business Data Cloud ontology tooling (OWL/RDF/SHACL, OBDA-style mapping to relational data).

| This project | SAP-side concept (as described publicly) |
|---|---|
| Materialised KG in rdflib/GraphDB | Knowledge graph engine in HANA Cloud |
| R2RML over staging views, virtual mode via Ontop | Mapping relational data to ontology concepts without copying data |
| Data product = named graph + DCAT metadata | Data products |
| Grounding checks in the Ask tab | Grounding LLM answers in business data |

This table is a conceptual mapping, not a claim that the code runs on SAP products. Nothing here was tested against HANA Cloud.

## What was and was not verified
Verified (on fictional test fixtures only): the whole pipeline, SHACL (0 violations), reasoning, rules, ER and CPV evaluation code,
embedding training and temporal-split evaluation, text-to-SPARQL validation and repair loop, grounding checker, the API (34 tests),
CLI run, UI production build.
Not verified: real GLEIF / OCDS / CPV / sanctions file formats and URLs, `sg download`, GraphDB and `RemoteStore`, Ontop,
docker-compose, GitHub Actions, any LLM call against the real Anthropic API, and every metric on real data.
