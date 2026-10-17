# Data Onboarding Agent

A Python command-line project that turns differently named customer/order CSVs
into reviewable onboarding drafts. It profiles files, analyzes field meanings,
uses a shared schema, generates and validates mappings, and exports ETL
configuration and a data dictionary.

**This is a draft-generation MVP, not a production ETL loader.** It does not
connect to a database. Unsupported or uncertain transformations remain
`manual_review`, and loading stays disabled.

## 1. Requirements

- Python **3.12**, Git, and a terminal.
- Internet access to install dependencies.
- For a fresh LLM run: your own OpenAI API key, API credits, and access to the
  configured model. The tested model is `gpt-4.1-mini`.
- No key or API credits are needed for the offline example or offline tests.

Only CSV inputs, one customer table and one order table per run are supported.
Customer names and source field names are not restricted to A/B/C.

## 2. Clone and set up

```bash
git clone https://github.com/barrack99999/multilingual-data-onboarding-agent.git data-onboarding-agent
cd data-onboarding-agent
```

macOS / Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` in place of
`python`; you do not need to change the machine's security settings.

Run the remaining commands from the repository root. Core dependencies are
pinned in `requirements.txt`; optional embedding/ML packages are separate.

## 3. API-key configuration (fresh LLM runs only)

Copy the template:

```bash
cp .env.example .env
```

On Windows, use `Copy-Item .env.example .env`. Open `.env` in an editor and enter
your own key after `OPENAI_API_KEY=`. Keep `OPENAI_MODEL=gpt-4.1-mini` for the
tested setup, or choose a compatible model you can access.

The CLI reads environment variables first, then `.env.local`, then `.env`.
It does not overwrite an already configured environment variable.
Never paste your key into Python source, a command argument, screenshots, logs,
or Git. API billing is separate from a ChatGPT subscription.
See the [official OpenAI Python setup documentation](https://developers.openai.com/api/reference/python).

Confirm the local file is ignored:

```bash
git check-ignore .env
```

It should print `.env`. Do not commit it.

## 4. Run one customer through the full workflow

This command starts with the included original teaching CSVs and makes fresh
FieldAnalyzer and MappingGenerator API calls:

```bash
python onboarding_agent.py \
  --source-system "Customer A" \
  --input-dir data/examples/week1 \
  --output-dir outputs/customer_a_run_01
```

The reviewed schema is included at `schemas/unified-schema.json`, so a clean
checkout does not need anything pre-generated in `outputs/`. It is reused by
default. You can supply another reviewed schema with `--schema PATH`.
`--recommend-schema` explicitly requests a new draft instead.

A run normally takes some time and may retry invalid mapping drafts. It uses
API credits. When it finishes, expect `completed_with_warnings` because deferred
rules and disabled loading are deliberate.

For B or C, change `"Customer A"` to `"Customer B"` or `"Customer C"` and use a
different output folder. The filename selector reads only that customer's
`customer_a_customers.csv` / `customer_a_orders.csv` pair, or the equivalent B/C
pair, even when all six inputs are in the same directory.

For custom filenames, supply both paths:

```bash
python onboarding_agent.py \
  --source-system "New Customer" \
  --input-dir data/private/new_customer \
  --customer-csv data/private/new_customer/clients.csv \
  --order-csv data/private/new_customer/purchases.csv \
  --output-dir outputs/new_customer_run_01
```

That is an example, not an included dataset. A live run sends compact profiles
and source-analysis/mapping evidence to the configured API, so use only data
you are authorized to send. Keep real customer data in ignored private folders.

## 5. Try the complete local workflow without an API key

This explicitly reuses the included reviewed Customer A analysis/mappings;
profiling, schema checks, sample validation, ETL drafting, dictionary generation,
and export still run:

```bash
python onboarding_agent.py \
  --source-system "Customer A" \
  --input-dir data/examples/week1 \
  --analysis examples/field-analysis/customer_a.json \
  --mapping-dir examples/mappings \
  --output-dir outputs/customer_a_offline_01
```

The log labels these steps `reused`, not fresh LLM output. Do not reuse those
mappings against another CSV path; generate new mappings instead.
[Portable example details](examples/README.md).

## 6. Inputs and outputs

Included example inputs are in `data/examples/week1/`: six fictional teaching
CSVs, each with four rows, plus their master CSV and source README. They
demonstrate English abbreviations, Indonesian names, and German/SAP-style names.

Each run produces:

```text
outputs/customer_a_run_01/
  profiles/                  CSV field summaries
  analyses/                  Individual source-field analyses
  field-analysis.json        Combined analyses
  unified-schema.json        Exact reviewed-schema copy, or requested draft
  schema-checks.json
  mappings/                  Customer and order mapping YAMLs
  validation/                Sample execution reports
  etl-configs/               One customer ETL draft containing two jobs
  data-dictionary.md
  data-dictionary.json
  output-manifest.json       Artifact paths and hashes
  run_log.json               Step status, errors, warnings, final paths
```

Start by reading `run_log.json`, then the dictionary and validation reports.
For Customer A's original examples, source IDs remain unchanged,
`01/22/2024` becomes `2024-01-22`, an impossible date becomes a warned null,
and a real zero amount stays zero. The shared schema has 20 target fields.

A successful workflow is not a promise that every rule is executable:
phone normalization, generated IDs, customer lookup, unapproved currency
rates, and German decimal-comma parsing remain review cases. The controller
continues drafting with those steps disabled.

Generated runs, profiles, validation logs, and synthetic data are ignored by
Git. The portable reviewed schema and teaching fixtures are intentionally
included separately.

## 7. Run offline tests and safety checks

```bash
python scripts/run_tests.py
python scripts/check_repository.py --history
```

The offline suite runs 81 unit tests plus CSV-profiler checks. Tests build
temporary synthetic fixtures themselves; no old `outputs/`, downloaded model,
API key, or pre-generated `data/generated/` is required.

The safety check examines tracked/unignored candidate files and, with
`--history`, reachable Git history for private paths and common credential
patterns. It reports locations, not secret values. It cannot detect every
kind of personal or sensitive data: manually review files before committing.

A fixture-specific checker can verify an original-example run's artifacts,
field meanings, dates, statuses, and amounts without additional API calls:

```bash
python scripts/check_end_to_end.py \
  --customer a \
  --run-dir outputs/customer_a_run_01 \
  --output outputs/customer_a_run_01-checks.json
```

This checker expects a fresh LLM run on the original examples; it deliberately
does not label an offline reused example as a fresh end-to-end evaluation.

## 8. Run a real API test on GitHub

The complete agent can run on your computer using section 4, or on a GitHub
Actions runner. Uploading code does not start an API call or host a web app.

1. In your repository, open **Settings → Secrets and variables → Actions →
   New repository secret**. Name it `OPENAI_API_KEY` and enter your key there,
   never in a file, issue, workflow input, or chat. This is a separate credential
   destination from your local `.env`; no local key is uploaded automatically.
2. Open **Actions → Live onboarding test → Run workflow**, leave the branch as
   `main`, choose `a`, `b`, or `c`, and confirm the run. Each click makes real API
   calls and consumes API credits. There is no scheduled or push-triggered paid run.
3. Open the finished run. It executes the entire controller without reused
   analyses/mappings, then checks the result against the original example answer
   key. Download the `live-onboarding-CUSTOMER` artifact to inspect the run log,
   mappings, validation results, ETL draft, and data dictionary.

Only the included fictional teaching data is used. Artifacts/logs in this public
repository may be accessible to others; do not substitute private customer data
without reviewing access and data-governance requirements. Artifacts expire
after seven days. Loading remains disabled, even when all checks pass.

The separate **Offline checks** workflow runs on pushes to `main` and pull
requests. It needs no API key and does not spend API credits. A green offline
check is not a live API test. The live workflow fails clearly if the repository
secret is missing, credits/access are unavailable, or an end-to-end check fails.

See GitHub's [manual-run guide](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
and [repository-secret guide](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

## 9. Directory structure

```text
onboarding_agent.py         Main CLI entry point
.github/workflows/         Offline CI and manually triggered live API test
src/                        Reusable modules and controller
scripts/                    Module CLIs, generators, tests, safety checks
schemas/                    Reviewed unified schema and mapping-format schema
examples/                   Portable reviewed analysis and mapping fixtures
data/examples/week1/        Original fictional A/B/C teaching datasets
data/generated/             Reproducible synthetic stress data (ignored)
data/private/               Suggested location for real input data (ignored)
outputs/                    Local generated artifacts and test evidence (ignored)
docs/                       Technical contracts, mapping format, runtime prompt
.env.example                Blank credential template; safe to commit
requirements.txt            Pinned core dependencies
requirements-embeddings.txt Optional ML experiment dependencies
```

## 10. Common issues

| Symptom | What to do |
|---|---|
| `python3.12: command not found` | Install Python 3.12 and reopen the terminal; on Windows use `py -3.12`. |
| `ModuleNotFoundError` or missing `responses` API | Activate the correct venv, then reinstall `requirements.txt`. Run `python -m pip check`. |
| Missing API key / 401 | Fill the ignored `.env` locally or configure the environment. Check project/model access; do not share the key. |
| 429 / insufficient credits | Check API billing and credits. Rate limiting may need a later retry; use the offline example while waiting. |
| Connection or certificate error | Check network/proxy access to the API. Do not disable TLS verification. Completed local artifacts remain in the run folder. |
| Output directory is not empty | Choose a new `--output-dir`; prior runs are preserved, not overwritten. |
| Missing CSV or wrong customer | Check the source label/filename pair, or pass both explicit CSV paths. |
| Missing schema | Use `--schema schemas/unified-schema.json`, or supply another reviewed schema that exists locally. |
| Failed step | Read `failed_step` and `errors` in `run_log.json`. Fix the cause and retry in a new folder. There is no automatic resume. |
| `manual_review` / invalid-date warning | Inspect the rule/report. A safe deferral or warned null is expected for unsupported/invalid data; do not force a production value. |
| Stale validation fingerprints | Rerun validation for the current CSV/mapping/schema before drafting ETL. |
| LLM mapping fails after retries | Keep the failed run evidence; inspect its source-specific rules and retry or review the mapping. Output quality is not guaranteed for unseen data. |
| GitHub live test reports missing secret | Add `OPENAI_API_KEY` in repository Settings → Secrets and variables → Actions, then manually rerun. Local `.env` is intentionally not copied. |

## 11. Known limitations and future work

The whole agent is a human-reviewed draft generator, not a production ETL
system. LLM answers can be wrong, complex names cannot be safely split by a
simple rule, and fixed exchange rates are fictional test fixtures. Profiling
currently holds the CSV in memory, while validation checks only the first N
rows. `merge`, `prefix`, and `normalize_phone` remain manual-review operations.
Real customer samples require permission, privacy controls, and careful handling
of API access, logs, and downloadable artifacts.

The next priorities are unseen-customer evaluation, reliability/scale, and
additional approved transformations. Streamlit, database integration, and new
data sources remain future work; a UI must not delay the CLI, tests, or docs.

## Optional experiments and further documentation

Generate six 75-row synthetic stress-test CSVs:

```bash
python scripts/generate_fake_data.py
```

The optional multilingual embedding experiment is not required by the workflow.
To use it, install `requirements-embeddings.txt` separately; it adds substantial
ML dependencies and downloads model weights on first use.

- [Mapping format](docs/week3-task1-mapping-format.md)
- [Module contracts](docs/module-data-contracts.md)

Before publishing, run the safety check and inspect `git status`. Do not force-add
ignored secrets, customer files, virtual environments, logs, or generated runs.
An accidentally committed real credential must be revoked/rotated; adding it
to `.gitignore` afterwards does not remove it from history.
