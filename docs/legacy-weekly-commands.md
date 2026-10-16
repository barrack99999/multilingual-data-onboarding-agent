# Historical weekly commands

These are the earlier learning-stage instructions, retained for reference.
Some commands depend on generated local artifacts that are not committed.
For a new checkout, use the root README quick start instead.

# Data Onboarding Agent

Starter project for building an agent that helps interpret, map, normalize, and
document customer data during onboarding.

## Setup

Python 3.12 and Git are installed, and a local virtual environment has been
created in `.venv`.

Activate the environment and install dependencies:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Configure API access when it becomes available:

```bash
cp .env.example .env
```

Open `.env` and replace the placeholder with the real key. `.env` is excluded
by `.gitignore` and must never be committed.

Run the API connectivity check:

```bash
python scripts/hello_llm.py
```

The script prints a JSON result. To compare low- and high-temperature outputs,
run:

```bash
python scripts/temperature_experiment.py
```

Prompt changes and observations are recorded in `docs/prompt-log.md`.

## Mini agent

Run the two required mini-agent tests:

```bash
python scripts/test_mini_agent.py
```

Ask it a custom question:

```bash
python scripts/run_mini_agent.py "Inspect data/customer_a_customers.csv and summarize it." --trace
```

Without a key, the script exits with a clear configuration message. This does
not block work that does not require API access, including Tasks 3 and 6.

## Synthetic data (Task 6)

Create the six deliberately messy CSV test files:

```bash
python scripts/generate_fake_data.py
```

The script writes 75 rows per file to `data/generated/`, checks that the files
contain the planned data-quality problems, and creates `data_design_note.md` as
the field-recognition answer key. The same results can be recreated at any time
because the script uses a fixed random seed by default.

## CSV profiling (Week 2, Task 1)

Create a compact field summary without sending the full CSV to an LLM:

```bash
python scripts/profile_csv.py data/examples/week1/customer_a_customers.csv
```

Save the profile as JSON:

```bash
python scripts/profile_csv.py data/examples/week1/customer_a_customers.csv \
  --output outputs/customer_a_customers_profile.json
```

Run the profiler checks:

```bash
python scripts/test_csv_profiler.py
```

The profiler uses only normal Python. It reports types, samples, missing-value
rates, unique counts, top values, duplicate rows, and date/email/amount/status
signals. No API key or LLM call is needed.

## FieldAnalyzer (Week 2, Task 2)

Analyze one CSV from its compact profile:

```bash
python scripts/analyze_fields.py data/examples/week1/customer_a_customers.csv \
  --output outputs/customer-a-customers-analysis.json
```

Run the measured Customer A evaluation:

```bash
python scripts/evaluate_customer_a.py
```

The evaluation checks all 12 customer and order fields from the original
`WORKKKK/data/examples/week1` examples. It records exact matches and
accuracy in `outputs/customer-a-field-analysis-evaluation.json`.

## Multilingual evaluation (Week 2, Task 3)

Evaluate all Indonesian and German/SAP-style fields:

```bash
python scripts/evaluate_multilingual.py
```

The result records semantic accuracy, whether confidence is reasonable, and
whether evidence explicitly cites both the field name and real sample values.
If accuracy is below 80% after prompt refinement, the report activates the
fallback rule and lists incorrect fields as open issues for Week 3.

## Schema recommendation (Week 2, Task 4)

Build unified customer and order schemas from all field-analysis results:

```bash
python scripts/recommend_schema.py
```

The command creates `outputs/unified-schema.json` and a deterministic validation
report. The recommendation keeps customers and orders separate, retains
`full_name`, preserves original-currency amounts, calculates nullable USD
amounts, and standardizes order status with a controlled enum. It runs locally
with ordinary Python and does not send the field-analysis JSON to an API.

## Schema review and module contracts (Week 2, Task 5)

The manual schema review is recorded in
`outputs/week2-task5-schema-review.md`. The agreed contracts for FieldAnalyzer,
SchemaRecommender, MappingGenerator, ETLConfigGenerator, and
DataDictionaryGenerator are documented in:

- `docs/module-data-contracts.md` for people
- `docs/module-data-contracts.json` for code and precise validation
- `docs/module-contract-change-log.md` for later revisions

The reviewed schema is version 1.1. It adds a nullable unified customer link to
orders while preserving the required source customer ID from the original examples.

## Mapping format (Week 3, Task 1)

The stable Version 1 YAML mapping contract is defined before any customer
mapping is generated:

- `docs/week3-task1-mapping-format.md` explains every field, supported
  transformation, manual-review rule, and validation requirement.
- `docs/mapping-template.yaml` is the blank copy-and-fill template.
- `schemas/mapping-format-v1.schema.json` is the machine-readable structural
  schema for later validation code.

Version 1 supports `direct`, `rename`, `parse_date`, `map_value`, `split`,
`currency_conversion`, and `default_value`. Rules requiring `merge`, `prefix`,
or `normalize_phone` must use `manual_review` and provide a reason.

## MappingGenerator (Week 3, Task 2)

Generate the two mappings for each customer source:

```bash
python scripts/mapping_generator.py \
  --analysis outputs/customer-a-field-analysis.json \
  --source-system "Customer A"
python scripts/mapping_generator.py \
  --analysis outputs/multilingual-field-analysis.json \
  --source-system "Customer B"
python scripts/mapping_generator.py \
  --analysis outputs/multilingual-field-analysis.json \
  --source-system "Customer C"
```

The command uses the prompt in
`docs/week3-task2-mapping-generator-prompt.md`, validates the model's structured
result, and writes six YAML files to `outputs/mappings/`. Recheck every saved
mapping with:

```bash
python scripts/validate_mappings.py
```

The implementation note is `docs/week3-task2-mapping-generator.md`.

## Transformation helpers and sample validation (Week 3, Task 3)

Execute mappings on actual CSV samples, using plain Python without API access:

```bash
python scripts/validate_mapping.py --all
```

Validate one file and optionally display fictional currency-conversion previews:

```bash
python scripts/validate_mapping.py \
  data/examples/week1/customer_b_orders.csv \
  outputs/mappings/customer_b-order-mapping.yaml \
  --preview-review-currency
python scripts/test_transform_helpers.py
```

Reports in `outputs/mapping-validation/` show passed, failed, and manual-review
rules, executed example checks, per-row results, partial unified rows, and
warnings. `--sample-size` defaults to 20. Invalid dates handled by a declared
null policy produce warnings. Review rules remain unapproved even when a test
preview is calculated. Exit code 1 indicates failed rules or input errors;
review-required drafts return 0 with warnings and `ready_for_etl: false`.

The helper functions are in `src/transform_helpers.py`. The implementation,
original-example results, and synthetic-data findings are explained in
`docs/week3-task3-transformation-validation.md`.

## Iteration and validation report (Week 3, Task 4)

The prompt, helpers, and mappings were refined using the Task 3 findings.
`docs/week3-task4-validation-report.md` records before/after pass rates,
remaining failures, manual-review items, and the changes made. The compared
CSV files are identical; synthetic results cover all 450 rows.

Reproduce the post-fix checks and rebuild the report:

```bash
python scripts/test_transform_helpers.py
python scripts/report_mapping_validation.py --phase after --build-report
```

The script runs all twelve original/synthetic validation pairs. Expected
missing required IDs remain recorded failures; it does not treat them as a
report-generation error. Preserve `outputs/validation-iterations/before/` as
the original baseline. The machine-readable comparison is
`outputs/validation-iterations/comparison.json`.

## ETL configuration drafts (Week 3, Task 5)

Create one JSON file per customer, containing customer and order jobs:

```bash
python scripts/etl_config_generator.py --all
python scripts/test_etl_config_generator.py
```

The files are `outputs/etl-configs/customer_a-etl-config.json`,
`customer_b-etl-config.json`, and `customer_c-etl-config.json`. They include
inputs, target tables, mappings, transformation steps, validation rules,
loading behavior, evidence, and warnings. Loading is disabled and failed or
unreviewed transformations become disabled `manual_review` steps.

The generator verifies fresh validation fingerprints. Refresh validation
after changing a mapping, CSV, schema, validator, or helper:

```bash
python scripts/validate_mapping.py --all
python scripts/report_mapping_validation.py --phase after
python scripts/etl_config_generator.py --all
```

Details are in `docs/week3-task5-etl-config-generator.md`. Contract version 1.4
records customer bundles with config version 2.0 and two table-level jobs.

## Data dictionary (Week 4, Task 1)

Generate a reviewable dictionary from the unified schema, field analyses,
and all six mapping YAML files. No API call is required:

```bash
python scripts/data_dictionary_generator.py
python scripts/test_data_dictionary_generator.py
```

Read `outputs/data-dictionary.md`. The companion `outputs/data-dictionary.json`
supports later integration; warnings/errors go to
`outputs/data-dictionary.md.diagnostics.json`.
The dictionary contains all 20 unified fields, original A/B/C field names,
types, nullability, meanings, transformations, examples, and review comments.
Manual-review mappings remain flagged. Examples come from mappings, not a new
validation run. Regenerate the dictionary after changing any of its inputs.

Custom inputs are supported with `--schema`, `--analysis` (one or more JSON
files), `--mapping-dir` or `--mappings` (explicit YAML files), and `--output-dir`.
See `docs/week4-task1-data-dictionary.md` for an explanation and test results.

Customer A/B/C are defaults, not a fixed list. For another customer, supply its
analysis and mapping files and use a new output directory; no code edits are
needed. For example, after creating Customer D's upstream artifacts:

```bash
python scripts/data_dictionary_generator.py \
  --schema outputs/unified-schema.json \
  --analysis outputs/customer_d-field-analysis.json \
  --mappings outputs/mappings/customer_d-customer-mapping.yaml outputs/mappings/customer_d-order-mapping.yaml \
  --output-dir outputs/customer_d
```

See the note's reuse section for filename matching, source coverage warnings,
and the current customer/order-table scope.

## OnboardingAgent controller (Week 4, Task 2)

Run the modules in order with one command. From the project folder and with
the virtual environment active, a fresh run uses the existing API key for
FieldAnalyzer and MappingGenerator:

```bash
python onboarding_agent.py \
  --source-system "Customer A" \
  --input-dir data/examples/week1 \
  --schema outputs/unified-schema.json \
  --output-dir outputs/customer_a_run_01
```

For the synthetic stress-test CSVs, change `--input-dir` to `data/generated`.
The main examples remain in `data/examples/week1/`. The output directory must
be new or empty; choose a new name for another run.

For a no-API integration check using existing A artifacts:

```bash
python onboarding_agent.py \
  --source-system "Customer A" \
  --input-dir data/examples/week1 \
  --schema outputs/unified-schema.json \
  --analysis outputs/customer-a-field-analysis.json \
  --mapping-dir outputs/mappings \
  --output-dir outputs/customer_a_reuse_01
python scripts/test_onboarding_agent.py
```

Reused steps are labelled in `run_log.json`; they are not fresh LLM outputs.
Reuse mappings only for their original CSV paths. For custom CSV names, pass
both `--customer-csv` and `--order-csv`. Source names are not restricted to A/B/C.
The CLI reuses the reviewed schema by default. `--recommend-schema` explicitly
requests a new schema draft instead.

The run folder contains profiles, analyses, schema, mappings, validation
results, ETL config, data dictionary, `output-manifest.json`, and `run_log.json`.
A fatal step failure preserves completed outputs and logs the reason. Validation
findings may continue as review-required drafts, with loading disabled.
See `docs/week4-task2-onboarding-agent.md` for outputs, limits, and test evidence.

## Live end-to-end test record (Week 4, Task 3)

`docs/week4-task3-test-record.md` records fresh A/B/C command-line runs on the
original examples, artifact completeness, key/date/status/amount checks, the
status-scope issue found in A/B, and their successful reruns. Final run folders
are `outputs/end-to-end/customer_a/attempt_02/`,
`customer_b/attempt_02/`, and `customer_c/attempt_01/`.

Recheck a saved original-example run without an API call:

```bash
python scripts/check_end_to_end.py \
  --customer a \
  --run-dir outputs/end-to-end/customer_a/attempt_02 \
  --output outputs/end-to-end/customer_a/attempt_02-checks.json
python scripts/test_mapping_status_scope.py
```

The checker is an A/B/C fixture-specific oracle, not a restriction on the agent.
It separates executed passes from safely deferred manual-review cases. Loading
remains disabled in every ETL draft.

## Project structure

```text
scripts/          Runnable utilities and experiments
src/              Reusable application code
data/examples/week1/ Original WORKKKK examples used by Week 2 Tasks 1-5
data/generated/     Synthetic stress-test data used separately
outputs/          Reports and deliverables (ignored by Git)
requirements.txt  Python dependencies
```

## Git safety check

Before committing, run:

```bash
git status
git check-ignore .env
```

The second command should print `.env`, confirming that the secret file is
ignored. Never paste an API key into source code, notebooks, documentation, or
commits.
