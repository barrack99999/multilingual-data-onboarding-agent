# Module Data Contracts — MVP Version 1.7

## Why these contracts exist

A data contract is an agreement about what one module receives and what it
must return. Defining these agreements now prevents Week 4 from becoming a
collection of scripts with incompatible filenames or JSON shapes.

The machine-readable version is `docs/module-data-contracts.json`. That file is
the detailed source of truth; this note is the easier human explanation.

The portable reviewed schema is now `schemas/unified-schema.json`, included
in a clean checkout and used by the CLI by default. References below to
`outputs/unified-schema.json` describe generated schema drafts or historical
artifacts; modules accept explicit schema paths and per-run copies. Current
workflow setup is documented in the root README. Run/artifact formats keep
their existing versions; only the default input location changed in 1.7.

## Shared rules

- CSV and JSON files use UTF-8.
- Source field names remain unchanged; unified target names use `snake_case`.
- JSON written to disk must be valid, parseable JSON.
- Mapping YAML uses UTF-8, two-space indentation, and the exact Version 1
  contract in `docs/week3-task1-mapping-format.md`.
- Fatal errors do not overwrite a previous good output and cause a non-zero
  command-line exit.
- Warnings allow output generation but must be recorded for review.
- Diagnostics use a sidecar named `<output>.diagnostics.json` with:
  `contract_version`, `module`, `status`, `errors`, and `warnings`.
- Every error records `code`, `message`, `location`, and `retryable`.
- Every warning records `code`, `message`, `location`, and
  `suggested_action`.

## Module summary

| Module | Main input | Main output | LLM dependency |
|---|---|---|---|
| FieldAnalyzer | CSV profile | Field-analysis JSON | Yes, for semantic judgment |
| SchemaRecommender | Analyses from A–C | Unified-schema JSON | No; deterministic Python |
| MappingGenerator | One analysis + unified schema | Source-to-target mapping YAML | Yes for draft; code validates |
| MappingValidator | CSV + mapping YAML + unified schema | Sample-execution report JSON | No |
| ETLConfigGenerator | Accepted mapping + schema | ETL configuration JSON | No |
| DataDictionaryGenerator | Schema + accepted mappings | JSON and Markdown dictionary | No |

## 1. FieldAnalyzer

**Input paths**

- CSV: `data/examples/week1/<source>_<table>.csv`
- Profile: `outputs/<csv-stem>_profile.json`

The profile requires file and row information plus a `fields` array. Each
profiled field requires its name, inferred type, samples, null count/rate,
unique count, top values, and pattern flags.

**Output path:** `outputs/<csv-stem>-analysis.json`

Required output fields are `file_name`, `table_type`, `table_confidence`, and
`fields`. Every analyzed field requires `field_name`, `semantic_type`,
`description`, `confidence`, and `evidence`.

The LLM performs semantic judgment. Ordinary Python validates the profile,
enforces structured output, verifies every field appears exactly once, and
preserves source order. Typical warnings are low confidence and an `unknown`
semantic type.

## 2. SchemaRecommender

**Input paths**

- `outputs/customer-a-field-analysis.json`
- `outputs/multilingual-field-analysis.json`

**Output paths**

- Schema: `outputs/unified-schema.json`
- Validation: `outputs/unified-schema-validation.json`

The schema requires `schema_version`, `modeling_decisions`, and `tables`.
Every table requires its name, grain, primary key, and fields. Every schema
field requires type, nullable setting, description, source coverage, and
rationale.

This module does not require an LLM. Its policies are explicit Python so the
same accepted analyses always produce the same schema.

## 3. MappingGenerator

**Inputs**

- One `outputs/<csv-stem>-analysis.json`
- `outputs/unified-schema.json`

**Output path:** `outputs/mappings/<source>-<table>-mapping.yaml`

The output requires mapping version, source system/file, table type, target
table, rules, unmapped source fields, unmapped target fields, and warnings.
Every rule requires target field, source fields, transformation type,
structured expression, example input/output, notes, confidence, evidence,
status, and manual-review fields. The detailed contract is in
`docs/week3-task1-mapping-format.md`; the machine-readable structural schema is
`schemas/mapping-format-v1.schema.json`.

The LLM drafts mappings because this requires judgment. Plain code must reject
unknown fields, duplicate target mappings, invalid transformations, and missing
required targets. The supported Version 1 transformations are `direct`,
`rename`, `parse_date`, `map_value`, `split`, `currency_conversion`, and
`default_value`. Deferred operations use `manual_review` with a reason.
Low-confidence or ambiguous mappings become warnings rather than being silently
accepted.

## 3a. MappingValidator (Week 3, Task 3)

**Inputs:** a source CSV, one Version 1 mapping YAML, and the unified schema.
Optional settings control the sample size (default 20 first rows) and fictional
fixed-rate currency previews.

**Implementation:** `src/mapping_validator.py`, using
`src/transform_helpers.py`. The CLI is `scripts/validate_mapping.py`.

**Output path:**
`outputs/mapping-validation/<mapping-stem>-validation.json`, with a
`.diagnostics.json` sidecar. Batch validation also writes `summary.json`.

Report version 1.0 requires source paths, target table, sampling information,
summary counts, exclusive per-rule statuses (`passed`, `failed`,
`manual_review`), example checks, row results, partial transformed rows,
errors, warnings, and `ready_for_etl`. Decimal results are JSON strings to
preserve precision.

Runtime missing-value policy 1.1 normalizes known empty/N/A/null/none markers
to null according to the target nullable setting. Required fields still fail;
`status_raw` retains source text. Copy/rename preserves all non-missing values,
and missing conversion amounts never become zero. This shared policy is part
of the runtime contract; it does not add a new Version 1 transformation type.

No LLM or API key is required. Unsupported operations, ambiguous names/dates,
and unapproved rates require review. Failed transformations and input errors
cause a non-zero CLI exit. Handled nulls remain explicit warnings. A fictional
currency preview never changes a review rule into an accepted one. Reports
with failed or review-required rules are not ready for ETL.

## 4. ETLConfigGenerator

**Inputs**

- Source-system name
- Two `outputs/mappings/<source>-<table>-mapping.yaml` files
- `outputs/unified-schema.json`
- Primary results: `outputs/mapping-validation/<mapping-stem>-validation.json`
- Optional additional results, such as Task 4 synthetic validation reports

**Output path:**
`outputs/etl-configs/<source>-etl-config.json`

Config version 2.0 contains one customer bundle with two jobs. Required bundle
fields include source system, input files, target tables, jobs, loading behavior,
summary, provenance, warnings, draft status, and `production_ready: false`.
The original table-level fields (`source_file`, `target_table`, `read_options`,
`field_mappings`, `validation_rules`, `reject_policy`) remain inside each job.
Each job adds ordered transformation steps, missing-value policy, loading
behavior, validation evidence, unmapped fields, and warnings. Field mappings
retain source fields, target field, transformation type, and expression, plus
review reason, proposed transformation, and a dry-run enable flag.

No LLM is required. Unreviewed or failed rules may appear only as disabled
`manual_review` drafts. No loading is enabled. Reports must have current input
fingerprints for the CSV, mapping, schema, validator, and helpers. Primary
reports must match configured input CSVs; additional datasets remain evidence.
Invalid/stale inputs do not overwrite a previous configuration. Diagnostics use
the shared sidecar contract.

## 5. DataDictionaryGenerator

**Inputs**

- `outputs/unified-schema.json`
- Field analysis: `outputs/customer-a-field-analysis.json` and
  `outputs/multilingual-field-analysis.json` (filename-keyed bundles or individual results)
- All supplied `outputs/mappings/*-mapping.yaml` files, including review drafts

**Outputs**

- `outputs/data-dictionary.json`
- `outputs/data-dictionary.md`
- `outputs/data-dictionary.md.diagnostics.json`

Implemented in `src/data_dictionary_generator.py`; run with
`python scripts/data_dictionary_generator.py`. Dictionary version 1.0 contains
one entry per schema field, preserving table/field order and exact schema
name, type, nullable setting, and business description. Each entry also includes
table name, source fields, source coverage, lineage, transformation notes,
example values, and comments. The Markdown version explains both unified
tables, source lineage, known limitations, and input provenance.

No LLM is required. Mappings supply exact expressions and documented examples;
analysis supplies source descriptions, confidence, and evidence. Neither
overrides schema definitions. Review rules and uncertain interpretations stay
flagged; examples are not executed or claimed as validated. Nullable unmapped
fields stay visible, without invented examples. Missing mapping coverage is a
warning, while unknown fields, duplicate mappings, or unmatched analyses are
errors. Invalid inputs do not overwrite previous dictionaries. Shared
diagnostics record errors/warnings, and input hashes support regeneration.

## 6. OnboardingAgent controller

`src/onboarding_agent.py` connects modules; root `onboarding_agent.py` is the CLI.
Each invocation handles one source system with a customer/order CSV pair.
Default filenames are `<source_slug>_customers.csv` and
`<source_slug>_orders.csv`. Both can be overridden with explicit CSV paths.

The CLI reuses the reviewed schema by default (`--schema`); use
`--recommend-schema` only to explicitly request a new draft. SchemaRecommender
now accepts an optional source-system name rather than restricting coverage to
A/B/C. Missing concept coverage produces a warning, not fabricated lineage.

The output directory must be empty. Intermediate artifacts are saved as each
file completes. `run_log.json` version 1.0 records per-step status/mode, outputs,
errors, warnings, timestamps, and final artifact paths. A module exception marks
the current step failed, downstream steps skipped, and exits 1, retaining
completed artifacts. Rule-level validation findings can continue into disabled
manual-review drafts; that run exits 0 with warnings, not production approval.

`--analysis` and `--mapping-dir` explicitly reuse artifacts without those LLM
calls. Reuse is recorded. Analysis names/order are checked, but old analysis
meaning is not proven fresh for changed CSV values. A reused mapping cannot
silently point at another CSV. Validation always runs again. Input hashes detect
CSV changes between stages. The export manifest lists artifact paths and hashes.
Diagnostics are consolidated in the controller's run log; standalone module
CLIs retain their existing diagnostic sidecars. No database loading is enabled.

## Contract changes

Later tasks may refine these contracts. Any change must update the contract
version and be recorded in `docs/module-contract-change-log.md`. Adding an
optional field is normally compatible; renaming or removing a required field
is a breaking change.
