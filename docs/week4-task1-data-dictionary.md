# Week 4 Task 1: DataDictionaryGenerator

## What this task means

A data dictionary is a guide to our unified data. A reviewer should be able to
answer: What does this field mean? Where did it come from? What changes are
applied? Is anything still uncertain?

The generator produces that guide from the project files, so we do not have to
manually maintain a separate document that can drift away from the code.

## Files created

- `src/data_dictionary_generator.py`: reusable generator and Markdown renderer.
- `scripts/data_dictionary_generator.py`: command-line entry point.
- `scripts/test_data_dictionary_generator.py`: 23 self-contained offline tests.
- `outputs/data-dictionary.md`: human-readable dictionary.
- `outputs/data-dictionary.json`: structured companion for later integration.
- `outputs/data-dictionary.md.diagnostics.json`: review warnings and errors.

## Inputs and how they are used

| Input | Its responsibility |
|---|---|
| `outputs/unified-schema.json` | Target table/field names, data types, nullable settings, business meanings, rationale, and expected coverage |
| `outputs/customer-a-field-analysis.json` | Customer A source-field interpretations, confidence, and evidence |
| `outputs/multilingual-field-analysis.json` | Customer B/C source-field interpretations, confidence, and evidence |
| Six files in `outputs/mappings/` | Actual source-to-target relationships, exact transformations, example inputs/outputs, and review reasons |

The schema is authoritative for target definitions. For example, `full_name`
remains one field; this task does not split names or redesign tables. Analysis
helps explain the source field but cannot overwrite the schema definition.

The generator reads structured inputs locally. It uses no LLM, no API key,
and no database. No new Python dependency was needed.

## How I built it

1. Read and validate the schema and field-analysis JSON.
2. Match each mapping to its analysis using the CSV filename and table type.
3. Check that every mapped target exists in the schema and every source field
   exists in the corresponding analysis. Reject duplicate or inconsistent rules.
4. Walk through every schema field, preserving its order, type, nullability,
   and business description exactly.
5. Attach each customer's source fields, source interpretation, transformation,
   examples, and review notes. Keep nullable unmapped fields visible.
6. Render the same result as JSON and Markdown, including warnings and input
   hashes. Fully render both before replacing existing dictionary files.

## What a dictionary entry explains

For `unified_customers.source_customer_id`:

- Type: `string`; nullable: `false`.
- Meaning: customer identifier exactly as represented by the source.
- Sources: A `cust_id`, B `id_pelanggan`, C `Kundennummer`.
- Transformation: copy/rename according to each YAML rule.
- Examples: copied directly from the mapping's example input and output.
- Comments: preserve original identifiers for traceability and source joins.

For `phone`, the dictionary shows the original phone fields and the deferred
normalization rule. It does not claim that phone numbers have been normalized.
For generated keys, a null example is a placeholder in a review draft, not
permission to load null into a required field.

## Results

The current generation covers:

- 2 unified tables: `unified_customers` and `unified_orders`.
- 20 unique target fields: 9 customer fields and 11 order fields.
- All 6 mapping YAML files for Customers A, B, and C.
- 15 mapping lineages requiring review, retained with their reasons.
- 3 explicitly unmapped nullable lineages: A's `customer_segment` and B/C's
  `loyalty_tier`. No examples or source columns are invented for them.

"Lineage" means one customer's relationship to one target field. It is not
the same as a count of unique target fields. There are 57 mapped rules and
3 unmapped entries across the three customers.

Examples are documentation, not test results. This task does not read mapping
validation reports, so an accepted mapping is not described as runtime-approved.
The existing validation report and disabled ETL drafts remain the place to
check execution findings, including missing required customer IDs.

## Tests and consistency checks

All 23 dictionary tests passed. They cover exact schema metadata/order, linked
analysis, unchanged leading-zero IDs, defaults, proposed examples, review
flags, unmapped fields, partial coverage, invalid references, duplicate YAML
keys/targets, malformed analysis, incorrect nullable settings, unsupported
transformations, escaping Markdown, repeatable generation, CLI diagnostics,
and preserving previous outputs when inputs are invalid. Three reuse checks
use fictional Maple Store and Pearl Retail exports, different customer/order
filenames and fields (including Japanese names), and an added schema field.
They verify both bundled and separate analysis files, and show that a new
output folder leaves earlier dictionaries unchanged. These are offline
software tests, not a real unseen-customer LLM accuracy evaluation.

The tests create their own small fixtures in temporary folders. They do not
need API access or previously generated project outputs.

The existing 23 transformation tests and 12 ETL configuration tests also
passed (58 tests total). A direct check of the generated project dictionary
confirmed exact schema metadata for all 20 fields and unchanged source fields,
expressions, and examples for all 57 mapped rules. JSON and Markdown agree.

## How to run it

From the project folder:

```bash
source .venv/bin/activate
python scripts/data_dictionary_generator.py
python scripts/test_data_dictionary_generator.py
```

Open `outputs/data-dictionary.md` to review the result. To use custom inputs:

```bash
python scripts/data_dictionary_generator.py \
  --schema outputs/unified-schema.json \
  --analysis outputs/customer-a-field-analysis.json outputs/multilingual-field-analysis.json \
  --mapping-dir outputs/mappings \
  --output-dir outputs
```

Warnings produce a review draft with exit code 0. Invalid inputs produce exit
code 1 and an error sidecar without overwriting the previous dictionaries.
Regenerate after updating the schema, analyses, or mappings.

## Contract update

Contract version 1.5 records the implementation, required field-analysis input,
and additional review/documentation fields. Dictionary version is 1.0. Existing
schema, mappings, validation results, and ETL configs were not changed.

## Reusing it for another customer

The generator is not restricted to Customers A, B, and C. Those are just the
default example inputs. The customer name is read from `source_system` in the
mapping, and source field names and transformations are read from the supplied
analyses and YAML rules. Schema fields and definitions are read dynamically.

For Customer D, once its analysis and mapping files exist, run:

```bash
python scripts/data_dictionary_generator.py \
  --schema outputs/unified-schema.json \
  --analysis outputs/customer_d-field-analysis.json \
  --mappings outputs/mappings/customer_d-customer-mapping.yaml outputs/mappings/customer_d-order-mapping.yaml \
  --output-dir outputs/customer_d
```

These paths are an example, not files this task has created. The command will
produce `data-dictionary.md`, `data-dictionary.json`, and diagnostics inside
`outputs/customer_d/`, without replacing the existing A/B/C dictionary.
Multiple customers can be documented together by passing their analyses and
mappings in the same invocation. No Python edits are needed.

The reusable function for OnboardingAgent is:

```python
from src.data_dictionary_generator import generate_data_dictionary, render_markdown

dictionary = generate_data_dictionary(schema_path, analysis_paths, mapping_paths)
markdown = render_markdown(dictionary)
```

Requirements and boundaries:

- The customer must already have field analysis and mapping files matching
  the project contracts. This generator does not infer mappings from raw CSVs.
- Analysis `file_name` must match the source CSV basename in its mapping.
  Filenames must be unique across the analyses in a combined run. If customers
  use identical CSV names, run each customer separately, or give their exports
  distinct filenames and regenerate matching upstream artifacts.
- The current MVP supports customer and order tables, not unrelated domains.
- If the shared schema still lists only A/B/C in its source coverage, a D-only
  run can report missing old coverage. It will not fabricate those lineages.
  Review/update the schema coverage as part of onboarding, or supply all
  customers' artifacts when building a combined dictionary.
