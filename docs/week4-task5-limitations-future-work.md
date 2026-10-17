# Week 4 Task 5: Known Limitations and Future Work

## What this note covers

This note assesses the whole OnboardingAgent, not just one customer run.
The priority is the working command-line workflow, recorded tests, and
documentation. A Streamlit page is optional and was not added in this task.

## What the agent currently does

The agent helps turn differently named customer and order CSVs into a shared,
reviewable onboarding plan. It connects these modules in order:

```text
CSV profiling → FieldAnalyzer → reviewed schema / SchemaRecommender
→ MappingGenerator → sample validation → ETLConfigGenerator
→ DataDictionaryGenerator → exported artifacts and run log
```

Python calculates profiles, checks structures, validates sample transformations,
and produces the schema, ETL draft, and dictionary. The LLM interprets field
meanings and proposes mapping rules. The controller follows a fixed Python
workflow; it is not an autonomous model choosing arbitrary tools.

The generators accept supplied schemas, analyses, mappings, and source labels;
they are not limited to A/B/C field names. The current scope is still **CSV
files, one customer table and one order table per invocation, and configuration
drafts only**. There is no production database loading.

## Core deliverables checked first

Checks recorded on 2026-10-16:

| Core deliverable | Evidence and boundary |
|---|---|
| Data dictionary generator | Implemented and included in the passing test suite; target definitions remain consistent with the supplied schema and mapping lineage. |
| OnboardingAgent controller and CLI | Modules run in order; the reviewed schema can be reused. Logs, intermediate outputs, warnings, and partial failures are preserved. |
| A/B/C end-to-end test record | Existing fresh-API results were rechecked without new API calls: each has 16/16 required artifacts and 12/12 correct field meanings. Rule totals: 42 passed, 0 failed, 15 manual review. |
| Runnable repository and README | Setup, credentials, dependencies, live/offline commands, example inputs, and output paths are documented. Earlier isolated clean-clone verification passed, including a fresh API-backed Customer A run. |
| Regression checks | Reran 81 offline tests and CSV-profiler checks: all passed. These software checks do not measure live LLM accuracy on unseen customers. |

The [end-to-end test record](week4-task3-test-record.md) and
[repository verification note](week4-task4-repository-check.md) contain the
details. Recheck results from this task are stored locally under
`outputs/task5-core-check/`; generated evidence is intentionally ignored by Git.

The published repository also has offline CI and a manually triggered live
workflow. The [Customer A GitHub live test](https://github.com/barrack99999/multilingual-data-onboarding-agent/actions/runs/38898276090)
completed successfully, including fresh API-backed onboarding, independent
output checks, and artifact upload. This confirms that cloud execution works
for that example; it does not establish general accuracy or production safety.
Cloud artifacts are temporary, not permanent project documentation.

## Known limitations

| Limitation | What it means for the whole agent | Current handling |
|---|---|---|
| Unstable or incorrect LLM output | Valid JSON can still contain the wrong business interpretation. Temperature 0 does not guarantee identical or correct answers, and model confidence is not a measured probability. | Structured validation, evidence, lower-confidence warnings, bounded mapping retries, and human review. No guarantee of correctness. |
| Limited multilingual/generalization evidence | English, Indonesian, and German examples are small and controlled. New abbreviations, SAP conventions, or industries may be misunderstood. | Keep uncertain fields visible; do not treat the A/B/C scores as an unseen-customer benchmark. |
| Complex name splitting | A two-part split cannot reliably handle compound surnames, titles, single-word names, or different cultural name orders. | Preserve `full_name` in the shared schema. The simple helper flags non-two-part cases for review; a two-part name is not proof of first/last-name meaning. |
| Fixed exchange rates | Demo rates are fictional test fixtures, not current, dated, approved business rates. | Non-identity conversions require review; test previews cannot approve ETL execution. USD-to-USD identity needs no external rate. |
| Very large files | The profiler loads the full CSV and keeps values/counts in memory. Small LLM profiles do not make local processing streaming or production-scale. | Use small inputs for this MVP. No production file-size limit or performance guarantee has been established. |
| Sample-only validation | Validation checks the first N rows, so problems later in a large file may be missed. `--sample-size` does not limit the profiler's full-file read. | Record sampling details. All four rows per original example were checked, but a sample pass does not certify an entire larger dataset. |
| Deferred transformations | `merge`, `prefix`, and `normalize_phone` are not executable Version 1 operations. | Use `manual_review` with the requested operation and reason; do not disguise them as supported transformations. |
| Dates, statuses, and amount formats | Ambiguous dates, unseen status codes, and locale-specific amounts need explicit business rules. German decimal-comma detection is not the same as approved conversion. | Declared date formats and status maps only; invalid-date nulls carry warnings. Ambiguous dates, unapproved decimal-comma parsing, and unknown values remain errors/review findings according to policy. |
| IDs, lookups, and loading | Generated unified keys and customer/order linking need approved identity rules. The ETL output is a draft configuration, not a running data loader. | Preserve source IDs and source-system lineage. Hold unresolved rules for review; `production_ready` and loading remain false. |
| API access and interruptions | Credits, model access, network failures, and provider changes can interrupt LLM-dependent steps. Reused analysis may be stale even when its field names match. | Record the failed step and keep completed files. Offline reuse is labelled explicitly. There is no automatic whole-run resume; retries need a new output directory. |
| Real-data permissions and privacy | Profiles still contain sample values and can expose names, emails, or phones. Logs, dictionaries, and mappings may also contain sensitive examples. A public repository's cloud artifacts are not a safe place for private customer records. | Use fictional data for public tests. Obtain permission before sending real samples to an API; review/redact them and restrict artifact access/retention. Ignored folders are not encryption or access controls. |
| Credential and repository access | A connected account still needs appropriate repository/API permissions. Secret-pattern scans cannot find every credential or sensitive value. | Keep keys out of code/Git, use local environment configuration or GitHub Secrets, grant only needed access, and manually review publication candidates. Rotate exposed credentials. |

A successful CLI exit means the drafting workflow completed. It does **not**
mean all rules passed, review items were resolved, or data can be loaded safely.
Read the validation reports and review flags, not only the exit code.

## Future work, in priority order

1. **Test an unseen customer.** Prepare an independent answer key, run without
   customer-specific prompt tuning, and measure field/mapping accuracy and
   credible uncertainty. Reusable software tests are not a substitute for this.
2. **Improve reliability and scale.** Add broader regression cases, streaming
   profiling, better sampling/full-data validation options, and measured runtime
   and memory limits. Review privacy and prompt-injection risks before real data.
3. **Extend transformations.** Add tested, versioned rules for `merge`, `prefix`,
   and `normalize_phone`; improve locale-aware amount parsing and name handling.
   Approved dated exchange rates need provenance, rounding, and missing-rate rules.
4. **Add a Streamlit UI only if time remains.** A minimum page would provide
   upload, run, results, and downloads using the existing controller. Keep API
   secrets server-side and define safe upload/retention limits. Do not delay or
   replace the command-line deliverables to build it.
5. **Integrate a database in a later version.** First resolve generated keys,
   relationships, duplicates, approval gates, credentials, rollback, and repeatable
   loading. Keep database writes disabled in the current MVP.
6. **Support additional data sources.** Add adapters for formats/services such as
   Excel, JSON, or source-system exports, with explicit contracts and tests rather
   than assuming the CSV-specific code already supports them.

These items are future work, not claims of implemented functionality. No new
UI, database connector, exchange-rate feed, or input adapter was added here.

## Conclusion about the whole agent

The project delivers a reusable command-line onboarding assistant that connects
profiling, multilingual field interpretation, shared schema design, mapping,
validation, ETL drafting, and data-dictionary generation. Its main value is
reducing repeated manual investigation while keeping the proposed rules and
their evidence reviewable.

The core MVP is implemented and tested on the supplied customers, with a
documented setup and explicit failure/review records. However, it is **a
human-reviewed draft generator, not a production ETL system**. Small example
tests do not prove general accuracy, large-file performance, or permission to
process real customer data. The next priority is broader independent testing
and safer, more reliable transformations; a UI and database integration remain
optional/later work.
