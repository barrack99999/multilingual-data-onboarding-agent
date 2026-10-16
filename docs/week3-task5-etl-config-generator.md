# Week 3 Task 5: ETLConfigGenerator

## What this task does

ETL means extract, transform, and load. Our draft config describes which CSVs
to read, which mapping rules to apply, which values to validate, and what must
be resolved before loading data. It is a plan for a future ETL runner.

The generator uses normal Python. It does not need an LLM or API key.

## Files created

- `src/etl_config_generator.py`: reusable generator.
- `scripts/etl_config_generator.py`: command-line entry point.
- `scripts/test_etl_config_generator.py`: twelve offline checks.
- `outputs/etl-configs/customer_a-etl-config.json`.
- `outputs/etl-configs/customer_b-etl-config.json`.
- `outputs/etl-configs/customer_c-etl-config.json`.

Each customer gets one primary JSON file with two jobs: `unified_customers`
and `unified_orders`. Each file also has a `.diagnostics.json` sidecar.

## Inputs

Each customer config receives:

1. The source-system name, such as `Customer A`.
2. The reviewed unified schema.
3. That customer's two mapping YAML files.
4. The matching primary validation reports for the configured CSV inputs.
5. Additional synthetic validation reports, when available.

The current run includes both original examples and the Task 4 synthetic tests.
Synthetic CSVs are supporting evidence, not additional production input files.

The generator checks that each report belongs to the right source, mapping,
and target table. Validation reports now record SHA-256 fingerprints for the
CSV, mapping, schema, validator, and helpers. If any of these change, the report
must be refreshed. Old reports without fingerprints are also rejected. These
checks detect stale inputs; they are not cryptographic signatures proving that
a report is trustworthy.

## What the config contains

| Section | Purpose |
|---|---|
| `input_files` | The customer's customer and order CSV files |
| `target_tables` | The two unified destination tables |
| `jobs` | Separate customer and order plans |
| `read_options` | CSV format, encoding, delimiter, and header behavior |
| `field_mappings` | Source fields, targets, types, expressions, and review state |
| `transformation_steps` | Ordered instructions with dry-run enable flags |
| `missing_value_policy` | Nullable missing markers become null; required missing values are held |
| `validation_rules` | Required values, types, enums, primary keys, customer links, and conditional currency requirements |
| `reject_policy` | Proposed quarantine/review behavior; no silent dropping |
| `loading_behavior` | Disabled loading, customer-before-order order, and unresolved write/duplicate policies |
| `validation_evidence` | Report paths, test scope, row counts, results, and fingerprints |
| `warnings` | Source-quality problems and decisions that still need review |

The overall config has `status: draft`, `production_ready: false`, and disabled
loading. Even the fields verified on samples are only enabled for a future dry
run. This task does not implement that ETL runner or connect a database.

## How manual review works

A rule requires review if its mapping is unapproved, its transformation is
unsupported, any validation dataset failed or required review, or it relies
on fictional test exchange rates. Confidence below 0.70 also requires review,
following the project's existing uncertain/likely confidence boundary. The
config retains the confidence and evidence. It then uses:

```json
{
  "transformation_type": "manual_review",
  "status": "manual_review",
  "manual_review": true,
  "enabled_for_dry_run": false,
  "review_reason": "Reason from the mapping and validation evidence"
}
```

The intended rule remains in `proposed_transformation` so a person can review
and fix it later. Generated IDs, phone normalization, customer lookup, German
decimal commas, and unapproved IDR/EUR conversions remain disabled.

The original order examples have valid customer IDs, but the synthetic tests
contain five missing IDs per customer. The config carries that failure forward
as a review item for each order `source_customer_id` rule. A repair or rejection
policy must be approved before enabling that rule.

Customer A's same-currency USD conversion is limited by an explicit guard:
source currency must be USD. A different currency triggers review, rather
than assuming the placeholder rate source exists.

## Results

| Customer | Table jobs | Fields verified for dry run | Fields requiring review |
|---|---:|---:|---:|
| A | 2 | 14 | 5 |
| B | 2 | 13 | 6 |
| C | 2 | 12 | 7 |

The review counts are one higher than the Task 4 mapping review counts per
customer because ETL also holds the synthetic customer-ID failure for review.

All twelve ETL tests passed. They cover disabled loading and review steps,
propagation of synthetic failures, USD identity guards, wrong sources and
reports, changed CSV/schema/mapping inputs, inconsistent pass claims,
fictional rates, and preserving a previous config when inputs are invalid.
Low-confidence rules also remain under review despite a successful sample test.
All 23 transformation tests also continue to pass.

## How to run it

From the project folder:

```bash
source .venv/bin/activate
python scripts/etl_config_generator.py --all
```

For one customer:

```bash
python scripts/etl_config_generator.py --source-system "Customer B"
```

If a mapping, CSV, schema, validator, or helper changed, refresh its evidence:

```bash
python scripts/validate_mapping.py --all
python scripts/report_mapping_validation.py --phase after
python scripts/etl_config_generator.py --all
```

Run the offline checks:

```bash
python scripts/test_etl_config_generator.py
python scripts/test_transform_helpers.py
```

The CLI accepts custom schema, mapping, primary-validation, additional-validation,
and output directories. Bad or stale inputs cause exit code 1 and an error
diagnostic, while preserving a previous good config. Review-required drafts
are valid outputs and receive warnings.

## Contract update

The Week 2 plan described one ETL file per table. Task 5 explicitly requires
one per customer, so contract version 1.4 records a customer bundle with config
version 2.0. The original per-table contract fields remain inside `jobs`.
Consumers expecting the old top-level per-table shape must read `jobs` instead.

The reviewed schema remains version 1.1 and mapping YAML remains version 1.0.
The change is recorded in `docs/module-contract-change-log.md`.
