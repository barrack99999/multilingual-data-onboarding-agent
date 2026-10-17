# Week 4 Deliverables

One place to find the implementation, customer outputs, test evidence, and
documentation for the whole OnboardingAgent.

**Start here:** [README and run instructions](../README.md) ·
[GitHub repository](https://github.com/barrack99999/multilingual-data-onboarding-agent) ·
[Notion page with attached dictionaries, outputs, and test records](https://app.notion.com/p/1aef2154d6118307a7e58130019067d8)

Code and documentation are in GitHub. The reviewed fictional-customer run files
are attached in Notion, with access controlled by the existing Notion sharing
permissions. A public GitHub link does not grant access to those attachments.

## 1. DataDictionaryGenerator

- [data_dictionary_generator.py — reusable implementation](../src/data_dictionary_generator.py)
- [data_dictionary_generator.py — command-line wrapper](../scripts/data_dictionary_generator.py)
- [Generator explanation and reuse instructions](week4-task1-data-dictionary.md)

It reads the schema, field analysis, and mappings, then produces a reviewable
dictionary. Each customer dictionary below covers both customer and order tables.

## 2. Data dictionaries for Customers A, B, and C

| Customer | Dictionary files in Notion |
|---|---|
| A | [Open Customer A files](https://app.notion.com/p/0477e17e6fca49ff8a59268da028bcc2): `data-dictionary.md` and `data-dictionary.json` |
| B | [Open Customer B files](https://app.notion.com/p/3d82f9f96bb34695ba82ca1df807378e): `data-dictionary.md` and `data-dictionary.json` |
| C | [Open Customer C files](https://app.notion.com/p/5c492b459d2d465c8eea3c2a979cb189): `data-dictionary.md` and `data-dictionary.json` |

## 3. OnboardingAgent with a command-line entry point

- [onboarding_agent.py — main CLI entry point](../onboarding_agent.py)
- [OnboardingAgent — reusable controller](../src/onboarding_agent.py)
- [Controller explanation](week4-task2-onboarding-agent.md)
- [Reviewed shared schema](../schemas/unified-schema.json)

Run the root `onboarding_agent.py`, not the controller module inside `src/`.
For a fresh API-backed run, from the project root with the environment configured:

```bash
python onboarding_agent.py \
  --source-system "Customer A" \
  --input-dir data/examples/week1 \
  --output-dir outputs/customer_a_new_run
```

This uses API credits. Choose a new output folder for every run. The README
also includes a complete offline example and instructions for other customers.

## 4. Complete output folders for Customers A, B, and C

These are attached copies of the final end-to-end runs, not the earlier
attempts retained for issue investigation. Each contains 16 original artifacts
and preserves the customer run's folder layout.

| Customer | Complete output folder |
|---|---|
| A | [Open Customer A in Notion](https://app.notion.com/p/0477e17e6fca49ff8a59268da028bcc2) |
| B | [Open Customer B in Notion](https://app.notion.com/p/3d82f9f96bb34695ba82ca1df807378e) |
| C | [Open Customer C in Notion](https://app.notion.com/p/5c492b459d2d465c8eea3c2a979cb189) |

Open `run_log.json` for step status and `output-manifest.json` for the artifact
inventory and hashes. Paths inside these unchanged records refer to the
original local run, not Notion navigation links.

Folders include profiles, analyses, schema/checks, mapping YAMLs, validation
reports, ETL drafts, dictionaries, the manifest, and the run log.

**Availability:** Generated `outputs/` remain intentionally ignored by Git.
The links above open the reviewed copies in Notion; you need permission to
view that page. A GitHub clone includes the code and fictional source CSVs,
not old run folders. Generate new outputs using the README. Do not force-add
private outputs or credentials just to make them public.

The separate [GitHub live Customer A test](https://github.com/barrack99999/multilingual-data-onboarding-agent/actions/runs/38898276090)
has a downloadable `live-onboarding-a` artifact. It is a different run from the
local folders above and has temporary retention, not permanent storage.

## 5. End-to-end test record

- [Main A/B/C test record: inputs, results, issues, fixes, and reruns](week4-task3-test-record.md)
- [Independent A/B/C checks and offline test results — Notion attachments](https://app.notion.com/p/1aef2154d6118307a7e58130019067d8) under section 5: `customer-a.json`, `customer-b.json`, `customer-c.json`, and `offline-tests.json`.
- [Independent end-to-end checker](../scripts/check_end_to_end.py)
- [Test-suite entry point](../scripts/run_tests.py)

Across the final local runs: 48/48 required artifacts, 36/36 correct source-field
meanings, 42 passed rules, 0 failed rules, and 15 manual-review rules.
Manual review is not a successfully executed transformation.

## 6. Cleaned repository and setup documentation

- [README.md](../README.md) — setup, API configuration, run commands, structure,
  inputs/outputs, and common issues.
- [requirements.txt](../requirements.txt) — pinned core dependencies.
- [.gitignore](../.gitignore) — excludes keys, private inputs, local outputs,
  virtual environments, and disposable files.
- [.env.example](../.env.example) — blank credential template; never share `.env`.
- [Repository cleanup and clean-clone verification](week4-task4-repository-check.md).
- [Repository safety checker](../scripts/check_repository.py).

## 7. Known limitations and future-work list

[Read the whole-agent assessment](week4-task5-limitations-future-work.md).

It covers LLM uncertainty, multilingual generalization, complex names, fictional
exchange rates, large-file and sample-validation limits, deferred `merge`,
`prefix`, and `normalize_phone`, and real-data permissions/privacy. Future work
includes unseen-customer evaluation, reliability improvements, optional
Streamlit, database integration, and additional sources.

## Whole-agent conclusion

The agent connects the full CSV-onboarding workflow and generates reviewable
schema, mapping, validation, ETL-configuration, and data-dictionary outputs.
It is reusable and tested on the supplied A/B/C examples, but it remains a
human-reviewed draft generator—not a production ETL loader. The CLI, recorded
tests, and documentation take priority over an optional UI.
