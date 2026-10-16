# Week 3 Task 2: MappingGenerator

## What this task achieves

The MappingGenerator turns Week 2 field-analysis results into precise mapping
rules for the unified customer and order schemas. It produces rules that a
future ETL process can follow instead of returning a natural-language answer.

The generator runs once per source CSV table. Customers A, B, and C each have
a customer table and an order table, so the completed task produces six YAML
files in `outputs/mappings/`.

## Inputs and output

Each run uses:

- one table's field-analysis JSON;
- `outputs/unified-schema.json`;
- the source-system name;
- the project-relative source CSV path; and
- any applicable Week 2 open issues.

The model drafts a structured mapping object using the prompt in
`docs/week3-task2-mapping-generator-prompt.md`. Python then normalizes harmless
JSON/YAML representation differences, validates the business rules, and writes
the accepted object as YAML.

## Generated mappings

| Source | Customer mapping | Order mapping |
|---|---|---|
| Customer A | `customer_a-customer-mapping.yaml` | `customer_a-order-mapping.yaml` |
| Customer B | `customer_b-customer-mapping.yaml` | `customer_b-order-mapping.yaml` |
| Customer C | `customer_c-customer-mapping.yaml` | `customer_c-order-mapping.yaml` |

All six files passed the final validator.

## Important mapping decisions

- Dates use explicit input formats and produce `YYYY-MM-DD` output.
- Customer B status values are translated: `dibayar` to `paid`, `dikirim` to
  `shipped`, `dibatalkan` to `cancelled`, and `menunggu` to `pending`.
- Customer C status codes are translated: `BEZ` to `paid`, `VERS` to
  `shipped`, `STOR` to `cancelled`, and `OFF` to `pending`.
- The raw status is also preserved in `status_raw`.
- Customer B and C USD conversions are marked for manual review because no
  approved dated exchange-rate data was supplied.
- Customer C's comma-decimal amount, such as `129,99`, is marked for manual
  review because Version 1 has no `parse_decimal` transformation.
- Phone normalization is marked for manual review because
  `normalize_phone` is deferred in Version 1.
- Generated unified IDs and the order-to-customer lookup are explicit
  manual-review rules rather than silently omitted fields.
- The schema keeps `full_name`, so the generator does not split names.

## Week 2 open issues

The measured Week 2 multilingual evaluation contained no remaining open
issues. Therefore, Task 2 did not inherit an unresolved Indonesian or German
field. The manual-review rules above are new transformation or external-data
requirements, not failed field recognition.

## How to run it

Activate the virtual environment, then run:

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

Validate all six saved mappings:

```bash
python scripts/validate_mappings.py
```

The validator checks source and target fields, transformation expressions,
real example values, date-format coverage, status-map coverage, generated-key
handling, manual-review consistency, and target completeness.

