# Data sources: verify before use

Status after the Colab run of 21 Nov 2026: the loaders and column mappings in `config/sources.yaml` worked on the real GLEIF Level 1
and Level 2 (golden copy of 20 Nov 2026), CPV 2008, OpenSanctions `targets.simple.csv` and the OCDS JSONL export of publication 136
(Germany). The OCDS CSV export is NOT supported; use `full.jsonl.gz`. Licences are still unverified; the entries in
`config/data_products.yaml` say "TO BE VERIFIED" and you must check each source before reuse.

## Checklist
1. Download each file manually from the publisher (landing pages are listed in `config/sources.yaml`).
2. Read its licence and record it in `config/data_products.yaml` (currently "TO BE VERIFIED"). Sanction-list data in particular
   may have non-commercial terms.
3. Run `sg data check gleif1 <file>`, `gleif2`, `cpv`, `sanctions`, and `sg data check ocds <dir-or-file>`.
   Each reports missing columns with close-name suggestions; fix `config/sources.yaml`, not the code.
4. `make pipeline`, then `sg train` and `sg eval` (needs an LLM, see the README).

## Sources
| Source | Used for | Notes |
|---|---|---|
| GLEIF LEI level 1 / level 2 | legal entities, parent relationships | large; the loader filters by country |
| OCDS tender data (e.g. a national or TED-derived OCDS publication) | buyers, tenders, awards | any OCDS release/record package or JSONL works |
| CPV (EU Publications Office) | product categories (EN/DE labels) | prepared CSV; see `cpv.columns` |
| Sanction list in OpenSanctions "targets.simple.csv" style | sanction entries | column names unverified |
| Regulation text you choose (e.g. from EUR-Lex) | obligation extraction | add to `config/regulations.yaml` |

## Not implemented
- TED eForms XML ingestion (use an OCDS conversion or write a loader).
- Alignment to the EU eProcurement Ontology (ePO): a good next step, not done.
