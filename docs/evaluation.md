# Evaluation: what the numbers mean

All outputs of the evaluation code, on the shipped fixtures, are **plumbing checks** (the fixtures are tiny fictional data).
They say nothing about real-world performance. Run on real data before quoting any figure.

- **Entity resolution** (`sg er-eval`): identifier-masked. Parties that publish an LEI are matched by name only and compared with
  the LEI truth. This is optimistic: parties with an LEI are larger and better documented than the typical unlabeled party.
  Report it as an upper bound.
- **CPV linking**: TF-IDF over EN/DE labels, evaluated on tenders that already carry a CPV code (top-k recall at a CPV level).
- **Link prediction** (`sg train`): temporal split with leakage control; filtered ranking metrics (MRR, Hits@k) split into
  new buyer-supplier pairs, repeat pairs and cold-start suppliers. Four baselines are reported next to the embedding model;
  `history_then_category` is the one to beat. Repeat awards dominate procurement data, so overall metrics look good even for
  a history lookup. Judge the model on the *new pair* numbers.
  `sg train --final` retrains on all awards for serving and produces no honest metrics.
- **Text-to-SPARQL / GraphRAG** (`sg eval`): 14 competency questions with gold SPARQL; systems llm_only, vector_rag and graphrag.
  Metrics: execution accuracy of generated queries, answer recall of gold values, grounding checks. Gold answers come from the same
  graph the system queries, so this measures retrieval and query generation, not whether the graph is true.
- **Grounding checker**: deterministic (citations exist, numbers and known entity names appear in the evidence). It can miss
  wrong claims that use supported numbers and names in the wrong way. It is not a correctness proof.

## Known limitations
- Name matching for sanctions will produce false positives (common names) and false negatives (transliteration, aliases).
- Contract values are summed across currencies without conversion in the UI.
- The obligation extractor keeps only sentences found verbatim in the article text; this reduces fabricated quotes but does not
  guarantee the sentence is a real obligation or correctly attributed.
