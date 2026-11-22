# Virtual mode with Ontop (optional, UNTESTED)

The R2RML mapping in `mappings/suppliergraph.r2rml.ttl` is plain R2RML, so Ontop can answer SPARQL over the
staging database without materialising triples (the "virtual KG" pattern). Caveats found while writing this:

- The mapping targets named graphs (one per data product). Check your Ontop version's R2RML named-graph support.
- Derived triples (OWL RL inference, SPARQL rules, exposure flags) exist only in materialised mode.
- Ontop needs a JDBC driver for PostgreSQL; the views in `src/suppliergraph/staging/schema.sql` are the mapping sources.

Sketch: `ontop endpoint -m mappings/suppliergraph.r2rml.ttl -t ontology/suppliergraph.ttl -p ontop.properties`
with `jdbc.url`, `jdbc.user`, `jdbc.password`, `jdbc.driver` in `ontop.properties`.
