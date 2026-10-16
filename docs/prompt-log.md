# Prompt Log

This log records important prompt changes and test results.

## 2026-09-23 — First structured API call

**Goal:** Confirm that the local project can call the OpenAI API and return JSON.

**System prompt:**

> You are a test assistant for a data onboarding project. Return only the
> requested structured result.

**User prompt:**

> Confirm that the API call worked. Use the message "Hello from the data
> onboarding project!" and identify the project as "data onboarding".

**Output format:** A strict JSON schema with `message`, `project`, and
`api_working`.

**Result:** Successful. The API returned valid JSON:

```json
{
  "message": "Hello from the data onboarding project!",
  "project": "data onboarding",
  "api_working": true
}
```

## 2026-09-23 — Temperature experiment

**Goal:** Run the same field-mapping prompt several times at temperatures 0.0
and 1.2.

**System prompt:**

> You help map source CSV fields to a standard data model. Return only the
> requested structured result.

**User prompt:**

> Map the U.S. customer CSV field `signup_dt`. Sample values are `2024-01-15`,
> `01/22/2024`, and `2024/02/03`. Suggest one target field, one data type, and a
> short reason.

**Output format:** A strict JSON schema with `target_field`, `data_type`, and
`reason`.

**Result:** Successful. All six runs returned the same target field
(`signup_date`) and data type (`date`). The exact wording of `reason` changed in
both groups. The high-temperature answers showed somewhat more wording
variation, but this small test does not prove a general rule.

**Decision:** Use a low temperature for mapping drafts and keep the strict JSON
schema. Validate the meaning separately because valid JSON can still contain a
bad mapping.

## Template for later changes

- Date:
- Goal:
- What changed:
- System prompt:
- User prompt:
- Output format:
- Result:
- Decision:

## 2026-09-23 — Mini Agent tool decision

**Goal:** Check whether the model can answer a greeting directly but call
`get_csv_info` for a CSV question.

**System prompt:**

> You are a small learning agent. Answer greetings directly. When a question
> requires facts from a CSV file, call get_csv_info. Clearly summarize the tool
> result.

**Result:** Both tests passed. The greeting used no tool. The CSV question used
`get_csv_info` once and returned the correct row count and column names.

**Decision:** Keep deterministic CSV reading in Python and use the LLM only to
decide when the tool is needed and explain the result.

## 2026-10-09 — MappingGenerator Version 1 prompt

**Goal:** Draft one validated mapping object for one source CSV table using its
field analysis and the unified schema.

**What changed:** Added explicit rules for Version 1 transformation types,
dates, multilingual status values, original and converted amounts, name
handling, defaults, unsupported operations, examples, confidence, and Week 2
open-issue resolution.

**System prompt:** See `docs/week3-task2-mapping-generator-prompt.md`.

**User prompt:** Supplies the source-system name, one table's field-analysis
JSON, the unified-schema JSON, and the table's Week 2 open issues.

**Output format:** A typed mapping object validated against
`schemas/mapping-format-v1.schema.json`, then serialized to YAML by Python.

**Result:** The prompt was used by `scripts/mapping_generator.py` to generate
six mapping YAML files. All six passed structural, cross-file, observed-value,
date-format, and status-coverage validation.

**Decision:** Run one table per call at temperature 0. Do not ask the LLM to
mix customer and order tables or to return natural-language explanations.

## 2026-10-09 — Week 3 Task 4 validation-driven revision

**Evidence:** On 450 synthetic rows, six rules failed and 17 required review.
Missing amounts were copied as text markers, B/C status maps were case-sensitive,
and A/C did not declare all synthetic date formats.

**Prompt changes:** Added explicit nullable-marker handling, preservation of
required IDs and true zero amounts, case-insensitive status matching, documented
synthetic date formats, and reasons to keep complex operations under review.

**Helper changes:** Added `normalize_missing`, applied it using target
nullability, preserved `status_raw`, and made missing currency-conversion
amounts yield nullable nulls with warnings rather than zero.

**Mapping changes:** Reviewed manual YAML edits set B/C status matching to
case-insensitive and add supported A/C formats. No new LLM calls were made.
This measures the corrected mapping/helper pipeline; it does not measure the
effect of the revised prompt on fresh LLM output.

**Result:** On the same synthetic CSVs, 39/57 rules passed, 3 failed, and 15
required review, compared with 34/57 passed, 6 failed, and 17 requiring review
before fixes. Original examples remain 42 passed, 0 failed, and 15 under review.
All 23 regression tests passed.

**Decision:** Keep the three required customer-ID rules failing on the five
missing IDs per customer. Preserve review flags for phones, generated keys,
lookups, decimal commas, and missing approved rates. Full results are in
`docs/week3-task4-validation-report.md` and
`outputs/validation-iterations/comparison.json`.

## 2026-10-16 — Week 4 live end-to-end status-scope correction

**Evidence:** Fresh A/B/C CLI runs produced every artifact. Observed rows
transformed correctly, but A's generated status map included Indonesian/German
codes absent from A's CSV; B's included German BEZ variants absent from B.
Language hints had been copied into source-specific rules without evidence.

**Change:** The prompt now limits status keys to observed source categories
under the declared case/whitespace normalization. `validate_mapping` rejects
unobserved categories and gives retry feedback. Unknown future statuses remain
manual review. Six offline regression tests cover the boundary.

**Result:** Reran A and B with fresh analysis and mapping API calls in separate
attempt_02 folders. Both maps are now source-scoped; all independent checks
passed. C attempt_01 already met this criterion. Initial A/B outputs and failed
scope-check records remain preserved. Final validation totals: 42 passed,
zero failed, 15 manual-review rules across the original examples.

**Record:** `docs/week4-task3-test-record.md` and `outputs/end-to-end/`.
No schema, mapping YAML shape, module call signature, or data contract version
changed; this is a tightening of prompt/semantic validation behavior.
