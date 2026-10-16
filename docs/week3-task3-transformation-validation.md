# Week 3 Task 3: Transformation Helpers and Sample Validation

## What I built

Task 2 writes instructions in YAML. Task 3 tries those instructions on actual
CSV values and records what happened. It uses normal Python, with no API call
or API key required.

- `src/transform_helpers.py`: date parsing, simple name splitting, explicit
  status translation, scalar defaults, and fixed-rate currency conversion.
- `src/mapping_validator.py`: loads CSV/YAML/schema, executes each example and
  sampled row, checks target types/nullability, and builds the report.
- `scripts/validate_mapping.py`: command-line entry point for one mapping or
  all six mappings.
- `scripts/test_transform_helpers.py`: offline tests for successful and broken
  transformations.

All 18 offline tests passed. They cover invalid and ambiguous dates, complex
names, missing/conflicting status translations, bad defaults, duplicate rules
and YAML keys, missing rates, nullable targets, empty samples, and preservation
of a previous report after invalid input.

The earlier `scripts/validate_mappings.py` remains the Task 2 structure check.
The new singular `validate_mapping.py` performs Task 3 execution checks.

## How to run it

Open a terminal in the project folder and activate the environment:

```bash
source .venv/bin/activate
```

Test Customer A's order mapping:

```bash
python scripts/validate_mapping.py \
  data/examples/week1/customer_a_orders.csv \
  outputs/mappings/customer_a-order-mapping.yaml
```

Test all six mappings:

```bash
python scripts/validate_mapping.py --all
```

Show optional fictional fixed-rate previews for review-required currency rules:

```bash
python scripts/validate_mapping.py --all --preview-review-currency
```

Test a larger synthetic file separately:

```bash
python scripts/validate_mapping.py \
  data/generated/customer_b_orders.csv \
  outputs/mappings/customer_b-order-mapping.yaml \
  --sample-size 100 \
  --output-dir outputs/mapping-validation/stress
```

Run the offline tests:

```bash
python scripts/test_transform_helpers.py
```

## What the helper functions do

| Helper | Example | Limit |
|---|---|---|
| `parse_date` | `22/01/2024` → `2024-01-22` using `%d/%m/%Y` | Uses only declared formats; competing valid interpretations require review |
| `split_name` | `Emma Johnson` → `Emma` or `Johnson` | Accepts exactly two components; `Maria del Carmen` or a single name requires review |
| `map_status` | `dibayar` → `paid` using the supplied map | Missing entries follow the mapping's declared error policy |
| `convert_currency` | `1500000 IDR` → `97.50 USD` using a fictional test rate | Uses Decimal arithmetic and explicit rounding; decimal-comma input requires review |
| `default_value` | Add `source_system: Customer B` | Only scalar values and explicit supported conditions are allowed |

The fixed-rate fixtures are USD `1`, EUR `1.10`, and IDR `0.000065`, expressed
as USD per unit. These numbers are invented for testing; no live exchange-rate
data was fetched. A mapping can explicitly name `test_fixed_rates` for a test
conversion, which produces a warning. Optional previews also retain the
original manual-review status and mark the result `approved: false`.

Decimal outputs are saved as strings such as `"97.50"` in JSON to preserve
precision. Copy/rename rules preserve the original CSV representation. The
validator checks whether a decimal string is compatible with `decimal(18,2)`;
it does not silently rewrite a locale-specific amount or missing-value marker.

## How rule results are counted

- **Passed:** the declared example matches, and all sampled rows transform
  successfully. A declared null policy can pass with recorded warnings.
- **Failed:** configuration, the expected example, a sample transformation,
  or the target type/nullability check fails. Any failure makes the rule fail.
- **Manual review:** the rule is already deferred, a helper encounters an
  ambiguity, an unknown value requires review, or there are no data rows to test.

Each rule is counted once. Failures take priority over review; review takes
priority over passing. The report also records separate row-level counts.

For Customer A, `invalid_date` and `2024-02-30` cannot be parsed. Both mappings
declare `on_error: "null"` and their date targets are nullable. Therefore, the
date rules pass with one warning each, and the affected date becomes JSON
`null`. The invalid source value remains visible in the warning message.

An unmapped status with `unmapped_action: manual_review` is a review result.
With `reject_row`, it is a failure. With `null`, a required `order_status` still
fails the target-schema check. Unsupported defaults and duplicate target rules
also fail validation.

## Results on the original Week 1 examples

All four rows in each of the six original CSVs were checked, for 24 source rows.

| Mapping | Passed rules | Failed rules | Manual-review rules |
|---|---:|---:|---:|
| A customers | 6 | 0 | 2 |
| A orders | 9 | 0 | 2 |
| B customers | 6 | 0 | 2 |
| B orders | 8 | 0 | 3 |
| C customers | 6 | 0 | 2 |
| C orders | 7 | 0 | 4 |
| **Total** | **42** | **0** | **15** |

The review items are phone normalization, generated unified IDs, cross-table
customer lookup, IDR/EUR conversion without approved rates, and German decimal
commas. The unified schema keeps `full_name`; splitting is tested in the
offline checks rather than added to these mappings.

## Results on the synthetic stress-test files

All 75 rows in each generated file were checked, for 450 source rows.

| Mapping | Passed rules | Failed rules | Manual-review rules |
|---|---:|---:|---:|
| A customers | 6 | 0 | 2 |
| A orders | 6 | 3 | 2 |
| B customers | 6 | 0 | 2 |
| B orders | 5 | 2 | 4 |
| C customers | 6 | 0 | 2 |
| C orders | 5 | 1 | 5 |
| **Total** | **34** | **6** | **17** |

The script found problems that the four-row examples do not expose:

1. All three order datasets have five missing customer-ID values. Those values
   fail because `source_customer_id` is required.
2. A and B have ten missing amount values each. Their copy rules preserve empty,
   `N/A`, and `null` strings, which fail decimal validation. The mapping needs
   an explicit missing-amount policy. A's `amount_usd` also fails on those rows.
3. B and C each have 38 mixed-case statuses that are missing from their
   case-sensitive value maps. The script records them for manual review.
4. Unsupported or invalid date strings become null under the declared policy,
   with warnings. Review those warnings before expanding accepted formats.

These issues are recorded as findings for mapping refinement. The validator
does not automatically change the mapping, drop source rows, or approve review
items.

## Deliverables and report format

The original-example reports are in `outputs/mapping-validation/`. The
synthetic reports are in `outputs/mapping-validation/stress/`.

Each report records `report_version`, source files, target table, sample limit
and rows checked, a summary, rule-level outcomes, executed example checks,
row-level results, partial unified-row previews, errors, warnings, and
`ready_for_etl`.

`summary.json` summarizes the six original mappings. Every report also has a
`.diagnostics.json` sidecar using the shared error/warning contract. Input
errors leave a previous primary report intact and update the diagnostic sidecar.

The CLI returns exit code `1` for failed rules or input errors. Expected manual
review and handled warnings return `0`. Check the report's `ready_for_etl`
separately: all six current draft mappings have it set to `false` because
manual-review work remains. A sample pass is evidence about the checked rows;
it does not establish correctness for unseen data or approve business policies.
