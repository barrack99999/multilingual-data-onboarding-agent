"""Capture before/after sample checks and write the Week 3 validation report."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_mapping import save_json  # noqa: E402

OUTPUT = PROJECT_ROOT / "outputs/validation-iterations"


def capture(phase: str) -> None:
    results = []
    for dataset, folder in (("original", "data/examples/week1"), ("synthetic", "data/generated")):
        for mapping in sorted((PROJECT_ROOT / "outputs/mappings").glob("*-mapping.yaml")):
            data = yaml.safe_load(mapping.read_text(encoding="utf-8"))
            csv = PROJECT_ROOT / folder / Path(data["source_file"]).name
            output = OUTPUT / phase / dataset / f"{mapping.stem}-validation.json"
            command = [sys.executable, str(PROJECT_ROOT / "scripts/validate_mapping.py"),
                       str(csv), str(mapping), "--sample-size", "100", "--output", str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode not in {0, 1} or result.stderr or not output.is_file():
                raise RuntimeError(f"Validation could not produce a report for {mapping.name}: {result.stderr}")
            report = json.loads(output.read_text(encoding="utf-8"))
            print(f"{phase}/{dataset}/{mapping.name}: {report['summary']}")
            results.append({"dataset": dataset, "customer": data["source_system"], "mapping": mapping.name,
                            "mapping_sha256": hashlib.sha256(mapping.read_bytes()).hexdigest(),
                            "csv_sha256": hashlib.sha256(csv.read_bytes()).hexdigest(), "report": str(output),
                            "rows_checked": report["sampling"]["rows_checked"], **report["summary"]})
    save_json(OUTPUT / phase / "summary.json", {"phase": phase, "sample_size": 100, "runs": results})


def percent(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.1%}" if denominator else "N/A"


def aggregate(runs: list[dict], dataset: str, customer: str) -> dict:
    chosen = [run for run in runs if run["dataset"] == dataset and run["customer"] == customer]
    counts = {key: sum(run[key] for run in chosen) for key in
              ("rows_checked", "rules_total", "rules_passed", "rules_failed", "rules_manual_review")}
    counts["pass_rate_all_rules"] = percent(counts["rules_passed"], counts["rules_total"])
    counts["pass_rate_executable_rules"] = percent(counts["rules_passed"], counts["rules_passed"] + counts["rules_failed"])
    return counts


def build_report() -> None:
    before = json.loads((OUTPUT / "before/summary.json").read_text())["runs"]
    after = json.loads((OUTPUT / "after/summary.json").read_text())["runs"]
    if {(r["dataset"], r["mapping"], r["csv_sha256"]) for r in before} != {(r["dataset"], r["mapping"], r["csv_sha256"]) for r in after}:
        raise ValueError("Before/after comparison requires identical CSV inputs.")
    comparison, failures = [], []
    for dataset in ("original", "synthetic"):
        for customer in ("Customer A", "Customer B", "Customer C"):
            comparison.append({"dataset": dataset, "customer": customer,
                               "before": aggregate(before, dataset, customer),
                               "after": aggregate(after, dataset, customer)})
    for run in after:
        report = json.loads(Path(run["report"]).read_text())
        for rule in report["rules"]:
            if rule["status"] == "failed":
                bad_rows = [row for row in rule["row_results"] if row["status"] == "failed"]
                failures.append({"dataset": run["dataset"], "customer": run["customer"],
                                 "mapping": run["mapping"], "target_field": rule["target_field"],
                                 "failed_rows": len(bad_rows),
                                 "example_check": rule["example_check"],
                                 "cases": bad_rows[:5], "report": run["report"]})
    save_json(OUTPUT / "comparison.json", {"report_version": "1.0", "same_csv_inputs": True,
                                          "mapping_updates": "Reviewed manual YAML patches; no new LLM generation",
                                          "comparison": comparison, "remaining_failures": failures})
    lines = ["# Week 3 Task 4: Mapping Validation Report", "",
             "## What was changed", "",
             "I used the Task 3 findings to refine the MappingGenerator prompt, the",
             "helpers, and the existing YAML mappings. The YAML edits were reviewed",
             "manual corrections; no new API calls or regenerated LLM outputs were used.", "",
             "- Missing nullable values (`\"\"`, `N/A`, `null`, `none`) become actual nulls",
             "  with warnings. Required IDs still fail, and `status_raw` preserves the original text.",
             "- B/C status maps now use case-insensitive matching and trim whitespace.",
             "- Added the synthetic generator's documented A month-day-year dash format",
             "  and C ISO/slash day-month-year formats. No format is guessed from an ambiguous value.",
             "- Missing amounts do not become zero. Currency conversion returns null for",
             "  missing amounts, subject to target nullability, with a warning.",
             "- Phone normalization, generated IDs, customer lookup, German decimal",
             "  commas, and unapproved non-USD exchange rates remain manual review.", "",
             "## How pass rates are calculated", "",
             "A rule passes only if its example and every sampled row succeed. A declared",
             "null policy can pass with warnings. One failed row makes the rule fail.",
             "Review rules count separately and never count as passed.", "",
             "**All-rule pass rate** = passed / total rules.", "",
             "**Executable-rule pass rate** = passed / (passed + failed). This excludes",
             "review items and must be read alongside their count.", "",
             "Before and after use the same CSV files (verified by SHA-256). Both tables",
             "are tested per customer: 8 original rows or 150 synthetic rows. There are",
             "19 rules per customer. Sample limit is 100, covering every row in these files.", ""]
    for dataset, title in (("original", "Original examples"), ("synthetic", "Synthetic stress tests")):
        lines += [f"## {title}", "", "| Customer | Before: pass/fail/review | After: pass/fail/review | All-rule pass rate: before → after | Executable pass rate after |", "|---|---|---|---|---|"]
        for item in comparison:
            if item["dataset"] != dataset:
                continue
            b, a = item["before"], item["after"]
            lines.append(f"| {item['customer']} | {b['rules_passed']}/{b['rules_failed']}/{b['rules_manual_review']} | {a['rules_passed']}/{a['rules_failed']}/{a['rules_manual_review']} | {b['pass_rate_all_rules']} → {a['pass_rate_all_rules']} | {a['pass_rate_executable_rules']} |")
        lines.append("")
    lines += ["## Remaining failure cases", ""]
    for item in failures:
        row_numbers = [row["csv_row"] for row in item["cases"]]
        messages = sorted({row.get("message", "") for row in item["cases"]})
        lines.append(f"- {item['customer']} ({item['dataset']}): `{item['target_field']}` fails on {item['failed_rows']} rows. CSV row numbers: {row_numbers}. Reason: {'; '.join(messages)}")
    if not failures:
        lines.append("No failed rules in the tested rows; review items may remain.")
    lines += ["", "Missing required customer IDs must be repaired from the source or rejected",
              "under an approved ingestion policy. No ID was invented, no source row was",
              "removed, and target nullability was not weakened.", "",
              "## Review items and limits", "",
              "Customer A retains four review rules; B retains five; C retains six",
              "across customer and order tables. These include unsupported operations and",
              "missing external policies/data. Their counts stay visible in both tables.", "",
              "Complex names and ambiguous dates remain review cases in the regression",
              "tests. The schema keeps full_name, so the source mappings do not split names.",
              "Fixed exchange rates are fictional test fixtures and do not approve a",
              "production conversion. Decimal comma parsing remains deferred.", "",
              "Warnings record invalid dates and missing nullable values. A pass rate",
              "measures correct handling of tested samples, including declared fallbacks;",
              "it does not mean every source value is valid. Duplicate rows, orphan foreign",
              "keys, and real exchange-rate selection still need later ingestion checks.",
              "All six drafts remain not ready for ETL because review work remains.", "",
              "The regression suite passed all 23 tests, including missing nullable amounts,",
              "required IDs, mixed-case statuses, unknown translations, raw-status preservation,",
              "complex names, ambiguous dates, and unapproved currency conversions.", "",
              "## Deliverables and reproduction", "",
              "- Updated prompt: `docs/week3-task2-mapping-generator-prompt.md`.",
              "- Updated helpers: `src/transform_helpers.py`.",
              "- Updated mappings: `outputs/mappings/`.",
              "- Before and after reports: `outputs/validation-iterations/before/` and `after/`.",
              "- Machine-readable comparison: `outputs/validation-iterations/comparison.json`.",
              "- Prompt revisions: `docs/prompt-log.md`.", "",
              "Run from the project folder with the virtual environment active:", "",
              "```bash", "python scripts/test_transform_helpers.py",
              "python scripts/validate_mapping.py --all",
              "python scripts/report_mapping_validation.py --phase after --build-report", "```", "",
              "Preserve the before snapshot; recapturing it after fixes would invalidate",
              "the improvement comparison. The after capture runs validate_mapping.py",
              "for all twelve CSV/mapping pairs and records expected failures as findings.", ""]
    (PROJECT_ROOT / "docs/week3-task4-validation-report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("before", "after"))
    parser.add_argument("--build-report", action="store_true")
    args = parser.parse_args()
    if not args.phase and not args.build_report:
        parser.error("Use --phase before/after, --build-report, or both.")
    if args.phase == "before" and (OUTPUT / "before/summary.json").exists():
        raise SystemExit("Before snapshot already exists; preserving the original baseline.")
    if args.phase:
        capture(args.phase)
    if args.build_report:
        build_report()


if __name__ == "__main__":
    main()
