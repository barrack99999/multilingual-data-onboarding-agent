# Week 4 Task 4: Repository and README Check

## Changes made

- Replaced the starter README with clone/setup instructions, Python 3.12 venv
  creation, API configuration, live/offline commands, input/output examples,
  directory structure, tests, and common issues.
- Preserved the earlier weekly commands in `docs/legacy-weekly-commands.md`.
- Added the unchanged reviewed schema at `schemas/unified-schema.json` and
  made it the CLI default. A new clone no longer depends on ignored outputs.
- Added reviewed teaching fixtures under `examples/`; offline tests now create
  their own temporary stress data instead of requiring earlier local files.
- Pinned four core dependencies to verified versions. Moved the optional
  embedding dependency to `requirements-embeddings.txt` so the normal workflow
  does not install the ML stack or download a model.
- Hardened `.gitignore` for credentials, private/raw data, common data exports,
  logs, caches, and temporary files. Only the supplied teaching CSVs are
  allowlisted for publication. The credential template contains a blank key.
- Added `scripts/run_tests.py`, `scripts/check_repository.py`, and a repeatable
  clean-clone verification utility.

## Clean-clone verification

The verification utility copied only tracked/unignored candidate files into a
temporary Git snapshot and cloned it locally. It did not stage, commit, or push
the user's repository. No `.env`, `.env.local`, original venv, generated run
folder, or credential file was copied.

| Check | Result |
|---|---|
| New Python 3.12 virtual environment | Passed |
| Install pinned core requirements and `pip check` | Passed |
| Offline unit tests | 81 passed; no errors, failures, or skips |
| Additional CSV-profiler checks | Passed |
| No-key offline Customer A workflow from included fixtures | Passed |
| Fresh live Customer A workflow using README command/default schema | Passed |
| Live required artifacts | 16/16 generated |
| Live key/date/status/currency/amount checks | Passed; zero incorrect checks |
| Live mapping rules | 15 passed, 0 failed, 4 manual review |
| Loading | Disabled, as required by MVP |
| Clone secret/path scan, including its snapshot history | Passed |

The existing approved key was passed only in the live subprocess environment,
not written into the clone. Live analysis/mapping stages were not replaced
with mocks or cached results. Temporary verification repositories/venvs were
removed after the check; the result record remains at
`outputs/repository-check/clean-clone-verification.json`.

The core test results are additionally recorded in
`outputs/repository-check/local-tests.json`.

## Security review

`python scripts/check_repository.py --history` passed for the publishable
working tree and reachable repository history. The scanner reports locations,
not credential contents. One exact historical dummy token in a known
redaction test is explicitly recognized as a test fixture, not a real key;
new tests construct that dummy without a token-shaped source literal.

Pattern checks cannot prove that arbitrary data contains no personal or
sensitive information. The supplied teaching examples are the only CSVs
allowlisted; real customer files belong in ignored `data/private/` or
`data/raw/` and still require manual review before any publication/API use.

## Cleanup and recovery

Archived 44 disposable Python-cache/OS-metadata files and one superseded
Task 2 smoke-test folder, `outputs/controller-tests/customer_a-reuse`.
They are recoverable for now under:

`/private/tmp/onboarding-cleanup-backup.v5L0x0`

The archive preserves relative paths. Temporary storage may be cleared by the
operating system, so move anything needed out of it before that happens.
Removed obsolete empty `scripts/.gitkeep` and `src/.gitkeep` placeholders.
Meaningful Week 3/4 reports, first-attempt issue evidence, final test runs,
the working `.env`, and the existing project venv were preserved.

## Re-run the checks

```bash
python scripts/run_tests.py
python scripts/check_repository.py --history
python scripts/verify_clean_clone.py --live
```

The last command creates another isolated venv, downloads core dependencies,
and makes fresh API requests. Without `--live`, it verifies installation,
offline tests and the offline fixture workflow only.

This cleanup verified a local snapshot of the project files, not a GitHub
release. No remote was updated as part of that check. Publication is a separate
step; see the repository README for the current clone URL and local/live
GitHub Actions run instructions. Local API credentials are never part of the
published project.
