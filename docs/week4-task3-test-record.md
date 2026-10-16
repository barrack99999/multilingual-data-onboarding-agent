# Week 4 Task 3: End-to-End Test Record

Test date: 2026-10-16. Model: `gpt-4.1-mini`.

I ran the command-line workflow with fresh FieldAnalyzer and MappingGenerator
API calls for Customers A, B, and C. The reviewed Week 2 schema was reused
unchanged. These are live runs, not the artifact-reuse check from Task 2.

## Inputs and final results

All inputs are the original WORKKKK examples copied to `data/examples/week1/`.
Each CSV has four data rows: eight rows per customer, 24 rows across the final
three runs. Synthetic stress data was not substituted for the original examples.

| Customer | Input CSV files | Required artifacts | Key IDs | Dates | Status values | Amounts | Final rule results: pass / fail / review |
|---|---|---|---|---|---|---|---|
| A | `customer_a_customers.csv`, `customer_a_orders.csv` | 16/16 | Correct; source IDs unchanged | Valid dates converted correctly; two invalid dates become null with warnings | All four correct | Original/USD amounts correct, including zero | 15 / 0 / 4 |
| B | `customer_b_customers.csv`, `customer_b_orders.csv` | 16/16 | Correct; source IDs unchanged | All eight dates converted correctly | All four Indonesian translations correct | Original IDR amounts correct; USD conversion requires review | 14 / 0 / 5 |
| C | `customer_c_customers.csv`, `customer_c_orders.csv` | 16/16 | Correct; source IDs unchanged | All eight German dates converted correctly | All four SAP-code translations correct | Decimal-comma parsing and USD conversion require review; not executed | 13 / 0 / 6 |

All 36 source-field meanings were identified correctly (12 per customer),
including B's `id_pelanggan`, `tgl_daftar`, `total_harga` and C's
`Kundennummer`, `Name1`, `Bestelldatum`, `Währung`.

**Review is not a pass for an executed transformation.** The tests confirm
that unsupported operations remain visibly disabled, rather than claiming
their values were converted. Final totals are 42 passed rules, zero failed
rules, and 15 rules requiring review. Every run completed with warnings;
none is production-ready and no database loading was performed.

## What I checked

- Both profiles and individual analyses, the analysis bundle, schema copy and
  checks, two mapping YAMLs, two validation reports, ETL JSON, dictionary JSON
  and Markdown, export manifest, and run log: 16 required artifacts per run.
- Source CSV paths/hashes, all four rows of each CSV, and manifest hashes.
- Customer/order identifiers are copied from the correct fields and the
  correct source-system constant is set. Generated IDs/lookups stay under review.
- Dates match explicit expected ISO values, not simply any parseable date.
  A's `invalid_date` and `2024-02-30` are warned nulls, not guessed dates.
- Canonical statuses are `paid`, `shipped`, `cancelled`, `pending` in row order,
  while `status_raw` preserves the source text. Unfamiliar categories require review.
- Exact decimal comparisons for A/B executable amounts; true zero stays zero.
  No unapproved IDR/EUR conversion or German decimal parsing is executed.
- All 20 dictionary target definitions match the reviewed schema exactly.

`scripts/check_end_to_end.py` compares outputs to an independent, fixture-specific
answer key based on the Week 1 field design and actual original example rows.
It does not call transformation helpers to manufacture its expected values.
Its A/B/C answer key is a test fixture, not a restriction on the reusable agent.

## Issue found, fix, and reruns

| Priority | Finding | Action and result |
|---|---|---|
| P0: crashes / missing artifacts | None: all initial runs completed and generated all 16 artifacts | No crash fix needed |
| P1: unsupported status rules | A attempt 1 included Indonesian/German codes not observed in A; B attempt 1 included German `BEZ` aliases absent from B. Current rows transformed correctly, but these extra categories lacked source approval | Updated the prompt and deterministic mapping validation to restrict status-map keys to observed source categories, respecting declared case/whitespace normalization. Added six regression tests. Reran A and B with fresh API calls; the extra categories were removed and all independent checks passed |
| Expected limitations | Phones, generated keys, cross-table lookups, B/C exchange rates, and C decimal-comma parsing | Kept manual review and disabled execution; did not force unsupported operations |
| Coverage warnings | A lacks a customer segment; B/C lack a loyalty tier. A per-customer dictionary does not contain the other customers' source lineages | Kept nullable/unmapped fields visible. These warnings do not mean artifacts are missing |

A/B attempt 1 were retained. After the source-scope issue was discovered, the
independent checker records one failed scope check for each initial attempt,
even though the runtime validation of observed rows had zero failed rules.
This distinction is why simply trusting the CLI exit code would be insufficient.
C's source-scoped status map was already correct, so C did not need a rerun.

## Final output locations

| Customer | Final run folder | Check record |
|---|---|---|
| A | `outputs/end-to-end/customer_a/attempt_02/` | `outputs/end-to-end/customer_a/attempt_02-checks.json` |
| B | `outputs/end-to-end/customer_b/attempt_02/` | `outputs/end-to-end/customer_b/attempt_02-checks.json` |
| C | `outputs/end-to-end/customer_c/attempt_01/` | `outputs/end-to-end/customer_c/attempt_01-checks.json` |

Each run folder includes `run_log.json`, `output-manifest.json`, and the complete
intermediate/final artifacts. Check records are stored beside the run folder
so they do not alter the exported artifact inventory. Initial attempt folders
remain available for comparison. B's initial run had an extra explicit null
default for the absent loyalty tier; its final run leaves that nullable field
unmapped. Both representations are valid; the final table uses final-run counts.

## Reproduce

From the project folder with the virtual environment active:

```bash
python onboarding_agent.py \
  --source-system "Customer A" \
  --input-dir data/examples/week1 \
  --schema outputs/unified-schema.json \
  --sample-size 100 \
  --output-dir outputs/end-to-end/customer_a/new_run
```

Repeat with `Customer B` / `Customer C` and separate new output folders. These
commands use API credits. Do not pass `--analysis` or `--mapping-dir` for a fresh
test. Source CSVs and the reviewed shared schema are not edited.

Check a generated run without API calls:

```bash
python scripts/check_end_to_end.py \
  --customer a \
  --run-dir outputs/end-to-end/customer_a/attempt_02 \
  --output outputs/end-to-end/customer_a/attempt_02-checks.json
```

Use `b`/`c` and the appropriate run folder for the other customers. Exit code 1
means a missing artifact or incorrect check; review cases remain separately
labelled and are not represented as successful value conversions.

## Regression evidence and limits

All 81 offline tests passed after the fix: 17 controller, 23 dictionary,
23 transformation, 12 ETL, and 6 new status-scope tests. The independent checker
also caught four deliberately wrong in-memory ID/date/status/amount values;
that self-check did not modify any saved run files.

This test covers the supplied original examples, not unseen customers, all
real-world date/status conventions, or production-scale data. Existing Week 3
synthetic stress-test findings remain separate. No UI or output-formatting
redesign was needed.
