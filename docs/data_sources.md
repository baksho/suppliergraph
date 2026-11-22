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

## Sources (as used in the 21 Nov 2026 run)
| Source | File used | Staged as | Used for | Notes |
|---|---|---|---|---|
| GLEIF Level 1 (LEI-CDF golden copy) | `*-gleif-goldencopy-lei2-golden-copy.csv.zip` | `data/raw/gleif/level1.csv` | legal entities | about 5 GB unzipped; loaded with `usecols` and filtered to `--countries DE` (260,558 entities) |
| GLEIF Level 2 (relationship record golden copy) | `*-gleif-goldencopy-rr-golden-copy.csv.zip` | `data/raw/gleif/level2.csv` | parent relationships | 10,745 relationships kept for the loaded entities |
| OCP Data Registry, publication 136 (Germany) | `full.jsonl.gz` (also saved as `germany_full.jsonl.gz`) | `data/raw/ocds/` | buyers, tenders, awards | The JSONL export is read as a stream; the CSV export is not supported. `SG_OCDS_LIMIT` caps the number of releases (20,000 in the run) |
| CPV 2008 (EU Publications Office) | `cpv_2008_xls.zip` | `data/raw/cpv/cpv.csv` | product categories (EN/DE labels) | converted from the "CPV codes" sheet by `scripts/colab_prepare.py` (9,454 codes) |
| OpenSanctions `targets.simple.csv` | `targets.simple.csv` | `data/raw/sanctions/` | sanction entries | global list; 25,398 organisation entries loaded. **Non-commercial terms may apply** |
| EUR-Lex, Directive 2014/24/EU (German text) | `CELEX32014L0024DETXT.pdf` | `data/raw/regulation/dir_2014_24_de.txt` | obligation extraction | PDF converted with `pdftotext`; split into 94 articles. Add other texts in `config/regulations.yaml` |

`scripts/colab_prepare.py --drive <folder>` finds these files anywhere below a folder and stages them as shown. File names of newer
downloads may differ; adjust the patterns in that script or `config/sources.yaml` if `sg data check` reports missing columns.

## Not implemented
- TED eForms XML ingestion (use an OCDS conversion or write a loader).
- Alignment to the EU eProcurement Ontology (ePO): a good next step, not done.
