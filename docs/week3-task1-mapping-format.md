# Week 3, Task 1 — Mapping YAML Format

## Purpose

This document defines the mapping contract before any Customer A, B, or C
mapping is generated. A mapping rule must tell a person and a program:

1. which source field or fields are used;
2. which unified-schema field receives the result;
3. which supported transformation is applied;
4. the exact parameters of that transformation;
5. what a sample input should become; and
6. whether a human must review the rule.

The human-readable template is `docs/mapping-template.yaml`. The
machine-readable validation schema is `schemas/mapping-format-v1.schema.json`.

## 1. File-level structure

Every completed mapping YAML file must contain these top-level properties.

| Property | Type | Purpose |
|---|---|---|
| `mapping_version` | string | Mapping-format version. Version 1 uses `"1.0"`. |
| `source_system` | string | Stable name for the source customer or system. |
| `source_file` | string | Project-relative path to the input CSV. |
| `table_type` | string | Either `customer` or `order`. |
| `target_table` | string | Either `unified_customers` or `unified_orders`. |
| `rules` | list | Ordered mapping rules. A completed mapping needs at least one rule. |
| `unmapped_source_fields` | list of strings | Source fields intentionally not mapped. |
| `unmapped_target_fields` | list of strings | Target fields not produced by this source. |
| `warnings` | list of strings | File-level issues that do not make the YAML invalid. |

Rules should follow the source-field order where practical. Generated or
defaulted target fields may be placed after rules that use source fields.

## 2. Required properties for every rule

| Property | Type | Requirement |
|---|---|---|
| `target_field` | string | Must exist in the selected unified target table. |
| `source_fields` | list of strings | Must contain existing source columns. It is empty only for `default_value`. |
| `transformation_type` | string | Must be one of the allowed Version 1 types below. |
| `expression` | YAML object | Structured parameters for the selected transformation. |
| `example_input` | YAML object | Maps each source field to one representative value. Use `{}` for a source-free default. |
| `example_output` | any YAML value | Exact expected result. Use `null` when a manual-review rule has no approved result. |
| `notes` | string | Short business explanation, assumption, or limitation. |
| `confidence` | number | Decimal from `0.0` to `1.0`. |
| `evidence` | list of strings | Field-name, sample-value, profile, or business-rule evidence. |
| `status` | string | `accepted`, `needs_review`, or `rejected`. |
| `manual_review` | boolean | `true` when a person must decide or approve the rule. |
| `review_reason` | string or null | Required text when `manual_review` is `true`; otherwise `null`. |

`source_fields` is always a list, even when a rule uses only one field. This
avoids changing the data type when a future rule needs multiple inputs.

## 3. Supported transformation types

Only these values are allowed in Version 1:

```text
direct
rename
parse_date
map_value
split
currency_conversion
default_value
manual_review
```

### `direct`

Copies one source value without changing the field name meaning, value, or
data representation.

```yaml
expression:
  operation: copy
```

### `rename`

Copies one value unchanged while assigning it to a differently named target
field. It uses the same expression as `direct`; the separate type makes the
field-name change explicit.

```yaml
expression:
  operation: copy
```

### `parse_date`

Parses one date field and writes the target date in a consistent format.

```yaml
expression:
  input_formats: ["%m/%d/%Y"]
  output_format: "%Y-%m-%d"
  on_error: null
```

`on_error` must be `null`, `manual_review`, or `reject_row`. List every
accepted input format explicitly; do not say only "standardize the date."

### `map_value`

Translates source categories into controlled target values.

```yaml
expression:
  value_map:
    source_value: target_value
  case_sensitive: false
  trim_before_match: true
  unmapped_action: manual_review
```

`unmapped_action` must be `null`, `manual_review`, `reject_row`, or
`preserve_original`. The map must be complete for all currently known values.

### `split`

Extracts one part of a source string using an explicit delimiter and
zero-based part index.

```yaml
expression:
  delimiter: " "
  part_index: 0
  trim: true
  on_error: manual_review
```

Name splitting is culturally unreliable. If the available evidence does not
make the split safe, use `manual_review` instead.

### `currency_conversion`

Calculates a target amount using an amount, currency, dated rate source, and
rounding rule.

```yaml
expression:
  amount_field: source_amount_field
  currency_field: source_currency_field
  target_currency: USD
  rate_source: approved_rate_table
  conversion_date_field: source_order_date_field
  rounding_decimals: 2
  on_missing_rate: manual_review
```

`on_missing_rate` must be `null`, `manual_review`, or `reject_row`. A mapping
must never invent or hard-code a temporary exchange rate as if it were a
permanent business rule.

### `default_value`

Supplies a fixed value when no source field provides the target concept.

```yaml
expression:
  value: fixed_value
  apply_when: source_missing
```

`apply_when` must be `source_missing`, `source_null`, or `always`.
`source_fields` must be an empty list when the value is source-free.

### `manual_review`

Records a required operation that Version 1 cannot execute safely.

```yaml
expression:
  requested_operation: normalize_phone
  proposed_logic: "Convert valid numbers to an international format after a country-code policy is approved."
```

`requested_operation` is `merge`, `prefix`, `normalize_phone`, or `other`.
For this type, `manual_review` must be `true`, `status` should normally be
`needs_review`, `review_reason` must explain the blocker, and
`example_output` may be `null` if no result has been approved.

## 4. Deferred transformations and manual review

Version 1 deliberately does not support these transformations:

- `merge`
- `prefix`
- `normalize_phone`

They must never appear directly as `transformation_type`. Use
`transformation_type: manual_review`, name the deferred operation in
`expression.requested_operation`, and explain the reason in `review_reason`.
This makes the limitation visible instead of hiding an unsupported operation
inside a vague expression.

A rule may also require manual review when confidence is low, the sample values
conflict with the field name, or an important business policy is missing.

## 5. Validation requirements

Plain Python validation should eventually enforce all of the following:

1. The YAML parses successfully and contains no unknown top-level or rule keys.
2. All required file-level and rule-level properties are present.
3. `mapping_version` is `"1.0"`.
4. The table type and target table agree: customer to `unified_customers`,
   order to `unified_orders`.
5. Every source field exists in the source CSV/profile.
6. Every target field exists in the selected unified-schema table.
7. Each target field appears at most once in one mapping file.
8. Every transformation type belongs to the Version 1 allowed list.
9. `merge`, `prefix`, and `normalize_phone` are rejected as transformation
   types and represented through `manual_review` instead.
10. The `expression` object has the correct keys and value types for its
    transformation.
11. `default_value` has an empty `source_fields` list; the other types have at
    least one source field.
12. `example_input` contains the same source fields named by the rule, except
    for source-free defaults.
13. `confidence` is between `0.0` and `1.0`, and `evidence` is not empty.
14. `manual_review: true` has a non-empty `review_reason`.
15. `manual_review: false` has `review_reason: null`.
16. A `manual_review` transformation has `manual_review: true`.
17. Required target fields that remain unmapped produce an error or explicit
    review item; nullable targets may appear in `unmapped_target_fields`.
18. YAML examples that look like dates, booleans, or nulls are quoted when they
    are intended to remain strings.

The JSON Schema checks the structural rules. Cross-file checks—such as whether
a field really exists in the CSV or unified schema—and duplicate target checks
must be performed by ordinary Python later.

## 6. YAML writing rules

- Use UTF-8 and two-space indentation.
- Use spaces, never tabs.
- Quote date-like strings such as `"01/12/2026"` so the YAML parser does not
  silently convert them.
- Write missing values as YAML `null`, not the strings `"N/A"` or `"null"`.
- Keep original source-column spelling and capitalization.
- Use unified-schema target names exactly as defined.
- Do not include API keys, customer secrets, or production credentials.

## Task 1 completion boundary

This task defines the format only. It does not generate mappings for Customer
A, B, or C and does not apply transformations to any CSV rows.
