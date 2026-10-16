# Week 4 Task 2: OnboardingAgent Controller

## In plain English

The controller is the coordinator. Instead of running seven scripts manually,
one command sends each module's output into the next module. Python determines
the order. It is not an LLM deciding which tools to call, and it does not load
anything into a production database.

## Files

- `onboarding_agent.py`: command-line entry point.
- `src/onboarding_agent.py`: reusable `OnboardingAgent` class.
- `scripts/test_onboarding_agent.py`: 17 offline controller tests.
- `outputs/controller-tests/customer_a-controller-v1/run_log.json`: Customer A
  integration-check evidence using existing analyses/mappings, without API calls.
- `outputs/controller-tests/controller-test-results.json`: machine-readable
  controller test counts and implementation hashes.

## Workflow

```text
Select customer and order CSVs
  → profile CSVs locally
  → analyze fields with the existing LLM module (or explicitly reuse analysis)
  → reuse reviewed schema, or explicitly recommend a new schema
  → generate mappings with the existing LLM module (or explicitly reuse mappings)
  → validate mappings on CSV samples
  → draft ETL configuration, with loading disabled
  → generate the data dictionary
  → export an artifact manifest
```

Existing modules are called through Python functions; their logic is not
duplicated into a separate implementation. The existing Python stack and
credential configuration are retained; no new agent framework is installed.
The LLM modules retain their structured-output validation. Reference:
[official OpenAI Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

## Run a fresh Customer A workflow

From the project folder:

```bash
source .venv/bin/activate
python onboarding_agent.py \
  --source-system "Customer A" \
  --input-dir data/examples/week1 \
  --schema outputs/unified-schema.json \
  --output-dir outputs/customer_a_run_01
```

This uses API credits for two field analyses and two mapping generations
(mapping validation retries may require additional API requests). It sends
compact profiles to FieldAnalyzer, not whole CSV files. The existing
MappingGenerator also includes its existing observed-value checks.

The default schema is `outputs/unified-schema.json` even if `--schema` is
omitted. The controller copies the reviewed schema exactly into the run folder;
it does not overwrite the original. Use `--recommend-schema` only when a new
draft is wanted. A single-customer draft is not a replacement for a schema
reviewed across all customers.

`--input-dir data/generated` selects synthetic stress data instead. Existing
original-example mappings cannot be reused silently against those different
paths; generate mappings for the selected inputs.

## What gets saved

```text
output directory/
  profiles/                  Compact CSV profiles
  analyses/                  Individual field analyses
  field-analysis.json        Combined analysis bundle
  unified-schema.json        Reviewed copy or explicitly generated draft
  schema-checks.json         Schema policy/coverage checks
  mappings/                  Customer and order YAMLs
  validation/                New sample execution reports
  etl-configs/               Customer ETL draft, loading disabled
  data-dictionary.json
  data-dictionary.md
  output-manifest.json       Artifact paths and SHA-256 hashes
  run_log.json               Step status, errors, warnings, final paths
```

The controller consolidates diagnostics in `run_log.json`. The independent
module CLIs continue to use their existing diagnostic sidecars.

Every run needs a new or empty output folder. This prevents mixing results
or overwriting an earlier run. Rerunning a previous command with the same
nonempty folder is rejected; choose a new output directory.

## Failures and review cases are different

- **Module exception:** for example, an API outage, invalid analysis, missing
  CSV, or bad schema. The step is marked `failed`, the reason is logged,
  downstream steps are `skipped`, and CLI exit code is 1. Already completed
  artifacts stay on disk, including the first analysis/mapping if the second
  fails. There is no automatic resume or retry of the entire run.
- **Validation finding:** a mapping rule fails on a sample row or needs manual
  review. Reports keep the failure. The controller can still produce drafts,
  but ETL disables the affected rule. Exit code 0 means the drafting workflow
  completed, not that every rule passed or production loading is approved.

The run log identifies `local`, `live_llm`, and `reused` modes. Errors are
redacted for key-like strings; secrets are never intentionally logged.
Source CSV hashes are checked between stages so a changing file cannot be
silently treated as one stable input.

## Reuse existing outputs without API calls

```bash
python onboarding_agent.py \
  --source-system "Customer A" \
  --input-dir data/examples/week1 \
  --schema outputs/unified-schema.json \
  --analysis outputs/customer-a-field-analysis.json \
  --mapping-dir outputs/mappings \
  --output-dir outputs/customer_a_reuse_01
```

This explicitly reuses analysis and mapping artifacts, checks their structure,
and reruns profiling and mapping execution. The log records that reuse.
Matching analysis field names/order does not prove semantic freshness when
CSV values have changed; that limitation is warned. Mapping source paths must
match the selected CSVs exactly. No source rebinding is performed.

## Another customer

Source labels are not restricted to A/B/C. By default, a source such as
`Maple Store` uses `maple_store_customers.csv` and `maple_store_orders.csv`.
For different filenames, provide both explicit paths:

```bash
python onboarding_agent.py \
  --source-system "Maple Store" \
  --input-dir data/maple \
  --customer-csv data/maple/clients_export.csv \
  --order-csv data/maple/transactions_export.csv \
  --schema outputs/unified-schema.json \
  --output-dir outputs/maple_run_01
```

This is example usage, not a claim those files exist. Exactly one customer
table and one order table are supported per invocation. Both CSV basenames
must be distinct. Additional tables/domains and production loading are outside
the MVP.

SchemaRecommender's source labels were generalized as part of integration.
Optional `source_system` metadata supplies the correct name even for custom
filenames. Missing concept coverage is recorded rather than filled with
invented sources; structural/modeling policy checks still apply.

## Verification performed

The Customer A no-API integration check used the original Week 1 examples,
the reviewed schema, and existing A analyses/mappings. All controller stages
completed with warnings; ETL and dictionary outputs were produced. This is an
artifact-reuse check, not a fresh LLM end-to-end accuracy evaluation. Customer
B/C fresh API runs remain part of later end-to-end testing.

All 17 controller tests passed. They use simulated LLM responses but actual
profiling, schema, mapping checks, validation, ETL and dictionary modules.
Coverage includes module order, custom source names/files, reviewed-schema
preservation, explicit schema generation, analysis/mapping partial failures,
bad analysis/schema, missing or changing CSVs, no-API reuse, wrong mapping
source paths, runtime failure propagation, manifest hashes, key redaction,
and non-overwrite CLI behavior.

The 23 dictionary, 23 transformation-helper, and 12 ETL tests also passed:
75 tests in total. The legacy A/B/C schema generation still passed all 12
schema checks. These counts do not claim a fresh live-API workflow test.

```bash
python scripts/test_onboarding_agent.py --results outputs/controller-tests/controller-test-results.json
python scripts/test_data_dictionary_generator.py
python scripts/test_transform_helpers.py
python scripts/test_etl_config_generator.py
```

Run-log contract version is 1.6 / run version 1.0. Existing artifact formats
remain unchanged. Changes are recorded in the module contract change log.
