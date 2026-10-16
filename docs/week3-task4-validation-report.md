# Week 3 Task 4: Mapping Validation Report

## What was changed

I used the Task 3 findings to refine the MappingGenerator prompt, the
helpers, and the existing YAML mappings. The YAML edits were reviewed
manual corrections; no new API calls or regenerated LLM outputs were used.

- Missing nullable values (`""`, `N/A`, `null`, `none`) become actual nulls
  with warnings. Required IDs still fail, and `status_raw` preserves the original text.
- B/C status maps now use case-insensitive matching and trim whitespace.
- Added the synthetic generator's documented A month-day-year dash format
  and C ISO/slash day-month-year formats. No format is guessed from an ambiguous value.
- Missing amounts do not become zero. Currency conversion returns null for
  missing amounts, subject to target nullability, with a warning.
- Phone normalization, generated IDs, customer lookup, German decimal
  commas, and unapproved non-USD exchange rates remain manual review.

## How pass rates are calculated

A rule passes only if its example and every sampled row succeed. A declared
null policy can pass with warnings. One failed row makes the rule fail.
Review rules count separately and never count as passed.

**All-rule pass rate** = passed / total rules.

**Executable-rule pass rate** = passed / (passed + failed). This excludes
review items and must be read alongside their count.

Before and after use the same CSV files (verified by SHA-256). Both tables
are tested per customer: 8 original rows or 150 synthetic rows. There are
19 rules per customer. Sample limit is 100, covering every row in these files.

## Original examples

| Customer | Before: pass/fail/review | After: pass/fail/review | All-rule pass rate: before → after | Executable pass rate after |
|---|---|---|---|---|
| Customer A | 15/0/4 | 15/0/4 | 78.9% → 78.9% | 100.0% |
| Customer B | 14/0/5 | 14/0/5 | 73.7% → 73.7% | 100.0% |
| Customer C | 13/0/6 | 13/0/6 | 68.4% → 68.4% | 100.0% |

## Synthetic stress tests

| Customer | Before: pass/fail/review | After: pass/fail/review | All-rule pass rate: before → after | Executable pass rate after |
|---|---|---|---|---|
| Customer A | 12/3/4 | 14/1/4 | 63.2% → 73.7% | 93.3% |
| Customer B | 11/2/6 | 13/1/5 | 57.9% → 68.4% | 92.9% |
| Customer C | 11/1/7 | 12/1/6 | 57.9% → 63.2% | 92.3% |

## Remaining failure cases

- Customer A (synthetic): `source_customer_id` fails on 5 rows. CSV row numbers: [2, 31, 33, 60, 64]. Reason: Required target source_customer_id is missing; repair the source or reject the row.
- Customer B (synthetic): `source_customer_id` fails on 5 rows. CSV row numbers: [2, 31, 33, 60, 64]. Reason: Required target source_customer_id is missing; repair the source or reject the row.
- Customer C (synthetic): `source_customer_id` fails on 5 rows. CSV row numbers: [2, 31, 33, 60, 64]. Reason: Required target source_customer_id is missing; repair the source or reject the row.

Missing required customer IDs must be repaired from the source or rejected
under an approved ingestion policy. No ID was invented, no source row was
removed, and target nullability was not weakened.

## Review items and limits

Customer A retains four review rules; B retains five; C retains six
across customer and order tables. These include unsupported operations and
missing external policies/data. Their counts stay visible in both tables.

Complex names and ambiguous dates remain review cases in the regression
tests. The schema keeps full_name, so the source mappings do not split names.
Fixed exchange rates are fictional test fixtures and do not approve a
production conversion. Decimal comma parsing remains deferred.

Warnings record invalid dates and missing nullable values. A pass rate
measures correct handling of tested samples, including declared fallbacks;
it does not mean every source value is valid. Duplicate rows, orphan foreign
keys, and real exchange-rate selection still need later ingestion checks.
All six drafts remain not ready for ETL because review work remains.

The regression suite passed all 23 tests, including missing nullable amounts,
required IDs, mixed-case statuses, unknown translations, raw-status preservation,
complex names, ambiguous dates, and unapproved currency conversions.

## Deliverables and reproduction

- Updated prompt: `docs/week3-task2-mapping-generator-prompt.md`.
- Updated helpers: `src/transform_helpers.py`.
- Updated mappings: `outputs/mappings/`.
- Before and after reports: `outputs/validation-iterations/before/` and `after/`.
- Machine-readable comparison: `outputs/validation-iterations/comparison.json`.
- Prompt revisions: `docs/prompt-log.md`.

Run from the project folder with the virtual environment active:

```bash
python scripts/test_transform_helpers.py
python scripts/validate_mapping.py --all
python scripts/report_mapping_validation.py --phase after --build-report
```

Preserve the before snapshot; recapturing it after fixes would invalidate
the improvement comparison. The after capture runs validate_mapping.py
for all twelve CSV/mapping pairs and records expected failures as findings.
