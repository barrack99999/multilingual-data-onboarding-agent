"""Check original Week 1 A/B/C workflow runs against an independent answer key.

This fixture-specific test oracle is not a restriction on OnboardingAgent.
It reads completed runs; it never calls an API or edits source/mapping files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_mapping import save_json  # noqa: E402
from src.mapping_validator import UniqueKeyLoader  # noqa: E402


# Expected meanings from the Week 1 design note, not from LLM results.
FIELDS = {
    "a": {"customer": {"cust_id": "customer_id", "full_name": "full_name", "email_addr": "email",
                       "phone": "phone", "signup_dt": "signup_date", "loyalty_tier": "loyalty_tier"},
          "order": {"order_no": "order_id", "cust_id": "customer_id", "order_dt": "order_date",
                    "total_amt": "amount", "currency": "currency", "status": "order_status"}},
    "b": {"customer": {"id_pelanggan": "customer_id", "nama_lengkap": "full_name", "email": "email",
                       "no_hp": "phone", "tgl_daftar": "signup_date", "segmen": "customer_segment"},
          "order": {"no_pesanan": "order_id", "id_pelanggan": "customer_id", "tgl_pesanan": "order_date",
                    "total_harga": "amount", "mata_uang": "currency", "status_pesanan": "order_status"}},
    "c": {"customer": {"Kundennummer": "customer_id", "Name1": "full_name", "EMail": "email",
                       "Telefon": "phone", "Erfassungsdatum": "signup_date", "Kundengruppe": "customer_segment"},
          "order": {"Bestellnummer": "order_id", "Kundennummer": "customer_id", "Bestelldatum": "order_date",
                    "Betrag": "amount", "Währung": "currency", "StatusCode": "order_status"}},
}
SIGNUP_DATES = ["2024-01-15", "2024-01-22", "2024-02-03", "2024-02-14"]
ORDER_DATES = ["2024-02-01", "2024-02-05", "2024-02-11", "2024-02-16"]
STATUSES = ["paid", "shipped", "cancelled", "pending"]
AMOUNTS = {"a": ["129.99", "74.50", "0", "210.20"],
           "b": ["1500000", "750000", "0", "2200000"],
           "c": ["129.99", "74.50", "0.00", "210.20"]}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_run(run_dir: Path, letter: str) -> dict:
    run_dir = run_dir.resolve()
    source, slug = f"Customer {letter.upper()}", f"customer_{letter}"
    checks = []
    def check(name, passed, detail, *, review=False):
        checks.append({"check": name, "status": "review" if passed and review else "passed" if passed else "failed", "detail": detail})
    paths = [run_dir / "run_log.json", run_dir / "unified-schema.json", run_dir / "schema-checks.json",
             run_dir / "field-analysis.json", run_dir / "data-dictionary.json", run_dir / "data-dictionary.md",
             run_dir / "output-manifest.json", run_dir / "etl-configs" / f"{slug}-etl-config.json"]
    for kind, suffix in (("customer", "customers"), ("order", "orders")):
        paths.extend([run_dir / "profiles" / f"{slug}_{suffix}_profile.json",
                      run_dir / "analyses" / f"{slug}_{suffix}-analysis.json",
                      run_dir / "mappings" / f"{slug}-{kind}-mapping.yaml",
                      run_dir / "validation" / f"{slug}-{kind}-mapping-validation.json"])
    missing = [str(path) for path in paths if not path.is_file() or path.stat().st_size == 0]
    check("all_artifacts", not missing, f"{len(paths) - len(missing)}/{len(paths)} nonempty required artifacts; missing: {missing}")
    result = {"source_system": source, "run_dir": str(run_dir), "checks": checks,
              "artifact_count": len(paths) - len(missing), "artifacts_expected": len(paths),
              "input_files": [f"data/examples/week1/{slug}_{suffix}.csv" for suffix in ("customers", "orders")]}
    if missing:
        result.update(all_checks_passed=False, workflow_status="incomplete")
        return result
    log, analysis = read_json(run_dir / "run_log.json"), read_json(run_dir / "field-analysis.json")
    check("workflow_complete", log["status"] in {"completed", "completed_with_warnings"}
          and all(step["status"] in {"success", "warning"} for step in log["steps"]), log["status"])
    modes = {step["name"]: step["mode"] for step in log["steps"]}
    check("fresh_llm_stages", modes["field_analysis"] == modes["mapping_generation"] == "live_llm", str(modes))
    reviewed = PROJECT_ROOT / "schemas/unified-schema.json"
    check("reviewed_schema_unchanged", digest(reviewed) == digest(run_dir / "unified-schema.json"), "Run schema equals reviewed shared schema byte-for-byte.")
    manifest = read_json(run_dir / "output-manifest.json")
    check("artifact_hashes", all(Path(item["path"]).is_file() and digest(item["path"]) == item["sha256"]
                                 for item in manifest["artifacts"]), "Manifest hashes agree with generated artifacts.")
    config = read_json(run_dir / "etl-configs" / f"{slug}-etl-config.json")
    check("loading_disabled", config["production_ready"] is False and config["loading_behavior"]["enabled"] is False
          and all(job["loading_behavior"]["enabled"] is False for job in config["jobs"]), "Draft only; no database loading.")
    jobs = {job["table_type"]: job for job in config["jobs"]}
    reports, mappings, source_rows = {}, {}, {}
    correct_fields, total_fields = 0, 0
    counts = {"passed": 0, "failed": 0, "manual_review": 0}
    for kind, suffix in (("customer", "customers"), ("order", "orders")):
        csv_path = PROJECT_ROOT / "data/examples/week1" / f"{slug}_{suffix}.csv"
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        source_rows[kind] = rows
        metadata = next(item for item in log["inputs"]["csv_files"] if item["table_type"] == kind)
        check(f"{kind}_input", Path(metadata["path"]).resolve() == csv_path.resolve() and metadata["sha256"] == digest(csv_path), "Original Week 1 CSV path and hash match.")
        fields = analysis[csv_path.name]["fields"]
        expected = FIELDS[letter][kind]
        correct = sum(expected.get(field["field_name"]) == field["semantic_type"] for field in fields)
        correct_fields += correct
        total_fields += len(expected)
        check(f"{kind}_field_meanings", correct == len(expected) and [field["field_name"] for field in fields] == list(expected),
              f"{correct}/{len(expected)} source meanings correct and in original order.")
        mapping = yaml.load((run_dir / "mappings" / f"{slug}-{kind}-mapping.yaml").read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        mappings[kind] = {rule["target_field"]: rule for rule in mapping["rules"]}
        report = read_json(run_dir / "validation" / f"{slug}-{kind}-mapping-validation.json")
        reports[kind] = {rule["target_field"]: rule for rule in report["rules"]}
        check(f"{kind}_all_rows_checked", report["sampling"]["rows_checked"] == len(rows) == 4, "All four original data rows were validated.")
        for state in counts:
            counts[state] += report["summary"][f"rules_{state}"]
        expected_ids = {"source_customer_id": next(key for key, meaning in expected.items() if meaning == "customer_id")}
        if kind == "order":
            expected_ids["source_order_id"] = next(key for key, meaning in expected.items() if meaning == "order_id")
        expected_ids["source_system"] = None
        for target, original in expected_ids.items():
            rule = mappings[kind][target]
            expected_values = [row[original] if original else source for row in rows]
            actual = reports[kind][target]
            check(f"{kind}_{target}", actual["status"] == "passed" and
                  [item["value"] for item in actual["row_results"]] == expected_values and
                  rule["source_fields"] == ([original] if original else []),
                  f"Exact source ID/provenance values preserved: {expected_values}.")
        target = "signup_date" if kind == "customer" else "order_date"
        expected_dates = list(SIGNUP_DATES if kind == "customer" else ORDER_DATES)
        if letter == "a":
            expected_dates[-1] = None
        actual = reports[kind][target]
        check(f"{kind}_dates", actual["status"] == "passed" and [item["value"] for item in actual["row_results"]] == expected_dates,
              f"Expected ISO dates: {expected_dates}; A invalid values must yield warned nulls, not invented dates.")
        if letter == "a":
            check(f"{kind}_invalid_date_warning", bool(actual["row_results"][-1]["warnings"]), "Invalid A date is explicitly warned.")
        generated = ["unified_customer_id", "phone"] if kind == "customer" else ["unified_customer_id", "unified_order_id"]
        for target in generated:
            rule = mappings[kind][target]
            gated = next(field for field in jobs[kind]["field_mappings"] if field["target_field"] == target)
            check(f"{kind}_{target}_review", rule["manual_review"] and bool(rule["review_reason"])
                  and gated["manual_review"] and gated["enabled_for_dry_run"] is False,
                  rule["review_reason"], review=True)
    status_field = next(key for key, meaning in FIELDS[letter]["order"].items() if meaning == "order_status")
    check("status_translation", reports["order"]["order_status"]["status"] == "passed" and
          [item["value"] for item in reports["order"]["order_status"]["row_results"]] == STATUSES,
          f"All four source statuses map to {STATUSES}.")
    check("raw_status_preserved", [item["value"] for item in reports["order"]["status_raw"]["row_results"]] == [row[status_field] for row in source_rows["order"]], "Original statuses remain unchanged for auditing.")
    status_rule = mappings["order"]["order_status"]
    expression = status_rule["expression"]
    def normalize_status(value):
        text = str(value).strip() if expression["trim_before_match"] else str(value)
        return text if expression["case_sensitive"] else text.casefold()
    observed = {normalize_status(row[status_field]) for row in source_rows["order"]}
    mapped = {normalize_status(key) for key in expression["value_map"]}
    check("status_source_scope", mapped == observed and expression["unmapped_action"] == "manual_review",
          f"No unapproved foreign categories; observed={sorted(observed)}, mapped={sorted(mapped)}. Unknown values require review.")
    currency_field = next(key for key, meaning in FIELDS[letter]["order"].items() if meaning == "currency")
    currency_rule, currency_result = mappings["order"]["currency_code"], reports["order"]["currency_code"]
    check("source_currency_preserved", currency_rule["source_fields"] == [currency_field]
          and currency_result["status"] == "passed"
          and [item["value"] for item in currency_result["row_results"]] == [row[currency_field] for row in source_rows["order"]],
          "Original currency codes are preserved; IDR/EUR are not relabelled as USD.")
    for target in ("amount_original", "amount_usd"):
        rule, execution = mappings["order"][target], reports["order"][target]
        gated = next(field for field in jobs["order"]["field_mappings"] if field["target_field"] == target)
        deferred = (letter == "c" and target == "amount_original") or (letter in "bc" and target == "amount_usd")
        if deferred:
            check(target, rule["manual_review"] and bool(rule["review_reason"]) and execution["status"] == "manual_review"
                  and gated["manual_review"] and gated["enabled_for_dry_run"] is False,
                  "Not executed: " + (rule["review_reason"] or "Missing review reason."), review=True)
        else:
            values = [item["value"] for item in execution["row_results"]]
            try:
                exact = [Decimal(str(value)) for value in values] == [Decimal(value) for value in AMOUNTS[letter]]
            except ArithmeticError:
                exact = False
            check(target, execution["status"] == "passed" and exact, f"Expected exact decimals {AMOUNTS[letter]}; zero must remain zero.")
    schema, dictionary = read_json(run_dir / "unified-schema.json"), read_json(run_dir / "data-dictionary.json")
    schema_fields = {(table["name"], field["name"]): field for table in schema["tables"] for field in table["fields"]}
    dictionary_fields = {(table["name"], field["name"]): field for table in dictionary["tables"] for field in table["fields"]}
    check("dictionary_schema_consistency", schema_fields.keys() == dictionary_fields.keys() and
          all(all(field[key] == dictionary_fields[name][key] for key in ("name", "type", "nullable", "description")) for name, field in schema_fields.items()),
          "All 20 target definitions match schema; nullable unmapped targets are still documented.")
    check("no_failed_validation_rules", counts["failed"] == 0, str(counts))
    result.update(all_checks_passed=all(item["status"] != "failed" for item in checks), workflow_status=log["status"],
                  field_meanings={"correct": correct_fields, "total": total_fields}, rule_counts=counts,
                  checks_passed=sum(item["status"] == "passed" for item in checks),
                  checks_review=sum(item["status"] == "review" for item in checks),
                  checks_failed=sum(item["status"] == "failed" for item in checks))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--customer", choices=list(FIELDS), required=True)
    parser.add_argument("--output", type=Path, required=True, help="Test record JSON, separate from the run manifest")
    args = parser.parse_args()
    try:
        result = check_run(args.run_dir, args.customer)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        result = {"source_system": f"Customer {args.customer.upper()}", "run_dir": str(args.run_dir),
                  "all_checks_passed": False, "check_error": str(error)}
    save_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key not in {"checks", "input_files"}}, indent=2))
    if not result["all_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
