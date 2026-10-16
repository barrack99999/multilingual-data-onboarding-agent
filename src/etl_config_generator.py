"""Draft one customer ETL config from mappings, schema and validation evidence."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from src.mapping_validator import UniqueKeyLoader, _config_errors

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE_TYPES = {"direct", "rename", "parse_date", "map_value", "split", "currency_conversion", "default_value"}


def source_slug(name: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not result:
        raise ValueError("Source system must contain a letter or number.")
    return result


def _resolve(path: str | Path) -> Path:
    path = Path(path)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _display_path(path: str | Path) -> str:
    resolved = _resolve(path)
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _warning(code: str, message: str, location: str) -> dict:
    return {"code": code, "message": message, "location": location,
            "suggested_action": "Review the evidence and approve a policy before enabling execution or loading."}


def _read_validation(
    report_path: Path, mapping_path: Path, schema_path: Path, mapping: dict, *, primary: bool
) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("report_version") != "1.0":
        raise ValueError(f"Unsupported validation report: {report_path}.")
    if report.get("source_system") != mapping["source_system"] or report.get("target_table") != mapping["target_table"]:
        raise ValueError(f"Validation source or target does not match mapping: {report_path}.")
    if _resolve(report["mapping_yaml"]) != mapping_path.resolve():
        raise ValueError(f"Validation belongs to a different mapping file: {report_path}.")
    source = _resolve(report["source_csv"])
    if primary and source != _resolve(mapping["source_file"]):
        raise ValueError(f"Primary validation must describe the configured input CSV: {report_path}.")
    expected = {"source_csv": _digest(source), "mapping_yaml": _digest(mapping_path),
                "unified_schema": _digest(schema_path),
                "validator": _digest(PROJECT_ROOT / "src/mapping_validator.py"),
                "transform_helpers": _digest(PROJECT_ROOT / "src/transform_helpers.py")}
    if report.get("input_sha256") != expected:
        raise ValueError(f"Missing or stale validation fingerprints in {report_path}; rerun validate_mapping.py.")
    rows_checked = report.get("sampling", {}).get("rows_checked")
    if type(rows_checked) is not int or rows_checked < 1:
        raise ValueError(f"Validation has no tested rows: {report_path}.")
    rules = report.get("rules", [])
    expected_targets = [rule["target_field"] for rule in mapping["rules"]]
    if [rule.get("target_field") for rule in rules] != expected_targets:
        raise ValueError(f"Validation rule coverage/order differs from mapping: {report_path}.")
    for mapping_rule, result in zip(mapping["rules"], rules):
        if result.get("transformation_type") != mapping_rule["transformation_type"]:
            raise ValueError(f"Validation transformation differs from mapping: {report_path}.")
        if result.get("status") not in {"passed", "failed", "manual_review"}:
            raise ValueError(f"Validation has an invalid rule status: {report_path}.")
        if result["status"] == "passed" and (
            result.get("rows_passed") != rows_checked
            or result.get("rows_failed") != 0 or result.get("rows_manual_review") != 0
            or result.get("configuration_errors")
            or result.get("example_check", {}).get("status") != "passed"
        ):
            raise ValueError(f"Validation claims a pass with inconsistent row/example results: {report_path}.")
    return report


def generate_etl_config(
    source_system: str,
    schema_path: str | Path,
    mapping_paths: list[str | Path],
    validation_paths: list[str | Path],
    *,
    additional_validation_paths: list[str | Path] | None = None,
) -> dict[str, Any]:
    """Build a deterministic draft; no LLM, executable ETL or database access."""
    schema_path = _resolve(schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    tables = {table["name"]: table for table in schema.get("tables", [])}
    if set(tables) != {"unified_customers", "unified_orders"}:
        raise ValueError("Unified schema must contain customer and order tables.")
    if len(mapping_paths) != 2 or len(validation_paths) != 2:
        raise ValueError("Supply exactly two mappings and their primary validations per customer.")
    additions = [_resolve(path) for path in additional_validation_paths or []]
    additional_reports = {path: json.loads(path.read_text(encoding="utf-8")) for path in additions}
    warnings = [_warning("DRAFT_ONLY", "Sample validation does not approve production loading.", "loading_behavior")]
    jobs, consumed_extra = [], set()
    for mapping_input, validation_input in zip(mapping_paths, validation_paths):
        mapping_path, validation_path = _resolve(mapping_input), _resolve(validation_input)
        mapping = yaml.load(mapping_path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        if not isinstance(mapping, dict) or mapping.get("mapping_version") != "1.0":
            raise ValueError(f"Unsupported mapping document: {mapping_path}.")
        if mapping.get("source_system") != source_system:
            raise ValueError(f"Mapping source must equal {source_system!r}: {mapping_path}.")
        table_name = {"customer": "unified_customers", "order": "unified_orders"}.get(mapping.get("table_type"))
        if table_name != mapping.get("target_table") or table_name not in tables:
            raise ValueError(f"Mapping table type and target disagree: {mapping_path}.")
        table = tables[table_name]
        fields = {field["name"]: field for field in table["fields"]}
        source_path = _resolve(mapping["source_file"])
        with source_path.open(encoding="utf-8-sig", newline="") as handle:
            columns = csv.DictReader(handle).fieldnames or []
        if not columns or len(columns) != len(set(columns)):
            raise ValueError(f"Source CSV requires unique column names: {source_path}.")
        source_rules = mapping.get("rules", [])
        if not source_rules or len({rule["target_field"] for rule in source_rules}) != len(source_rules):
            raise ValueError(f"Mapping requires rules with unique targets: {mapping_path}.")
        for rule in source_rules:
            errors = _config_errors(rule, columns, fields)
            if errors:
                raise ValueError(f"Invalid mapping rule {rule.get('target_field')}: {'; '.join(errors)}")
            if rule["target_field"] == "source_system" and not (
                rule["transformation_type"] == "default_value"
                and rule["expression"].get("value") == source_system
                and rule["expression"].get("apply_when") == "always"
            ):
                raise ValueError("source_system must be a constant equal to the supplied source name.")
        missing = set(fields) - {rule["target_field"] for rule in source_rules}
        if missing != set(mapping.get("unmapped_target_fields", [])) or any(not fields[name]["nullable"] for name in missing):
            raise ValueError(f"Missing targets must be explicitly nullable/unmapped: {mapping_path}.")
        used_sources = {name for rule in source_rules for name in rule["source_fields"]}
        unmapped_sources = set(mapping.get("unmapped_source_fields", []))
        if used_sources & unmapped_sources or unmapped_sources - set(columns) or set(columns) - used_sources - unmapped_sources:
            raise ValueError(f"Source fields must be mapped or explicitly unmapped: {mapping_path}.")

        primary = _read_validation(validation_path, mapping_path, schema_path, mapping, primary=True)
        evidence = [(validation_path, primary, "configured_input")]
        for path, extra in additional_reports.items():
            if _resolve(extra["mapping_yaml"]) == mapping_path:
                checked = _read_validation(path, mapping_path, schema_path, mapping, primary=False)
                evidence.append((path, checked, "additional_test_dataset"))
                consumed_extra.add(path)
        field_mappings, steps = [], []
        for index, rule in enumerate(source_rules):
            results = [(path, report["rules"][index]) for path, report, _ in evidence]
            reasons = []
            if rule.get("manual_review") or rule.get("status") != "accepted":
                reasons.append(rule.get("review_reason") or f"Mapping status is {rule.get('status')}.")
            if rule["transformation_type"] not in EXECUTABLE_TYPES:
                reasons.append(f"Transformation {rule['transformation_type']!r} is not executable in the MVP.")
            if rule["confidence"] < 0.70:
                reasons.append(f"Mapping confidence {rule['confidence']} is below the 0.70 review threshold.")
            for path, result in results:
                if result["status"] != "passed":
                    reasons.append(f"{_display_path(path)}: {result['status']} "
                                   f"({result['rows_failed']} failed rows, {result['rows_manual_review']} review rows).")
            if rule["transformation_type"] == "currency_conversion" and rule["expression"].get("rate_source") == "test_fixed_rates":
                reasons.append("Fictional fixed exchange rates are test fixtures and cannot approve an ETL conversion.")
            blocked = bool(reasons)
            target = rule["target_field"]
            expression = copy.deepcopy(rule["expression"])
            if blocked:
                expression = {"requested_operation": rule["expression"].get("requested_operation", "other"),
                              "proposed_logic": rule["expression"].get("proposed_logic", rule["notes"] or "Review original rule and validation evidence.")}
                warnings.append(_warning("MANUAL_REVIEW", f"{target}: {' '.join(reasons)}", f"jobs.{table_name}.field_mappings.{target}"))
            item = {"source_fields": rule["source_fields"], "target_field": target,
                    "transformation_type": "manual_review" if blocked else rule["transformation_type"],
                    "expression": expression, "target_type": fields[target]["type"],
                    "nullable": fields[target]["nullable"], "status": "manual_review" if blocked else "validated_sample",
                    "confidence": rule["confidence"], "evidence": rule["evidence"],
                    "manual_review": blocked, "review_reason": " ".join(reasons) if blocked else None,
                    "enabled_for_dry_run": not blocked,
                    "proposed_transformation": {"transformation_type": rule["transformation_type"], "expression": rule["expression"]},
                    "example_input": rule["example_input"], "example_output": rule["example_output"],
                    "notes": rule["notes"]}
            field_mappings.append(item)
            steps.append({"step_id": f"{mapping['table_type']}_{index + 1:02d}",
                          "source_fields": item["source_fields"], "target_field": target,
                          "operation": item["transformation_type"], "parameters": item["expression"],
                          "enabled_for_dry_run": not blocked, "manual_review": blocked,
                          "on_uncertain_value": "manual_review"})
            if not blocked and rule["transformation_type"] == "currency_conversion":
                steps[-1]["execution_guard"] = {"mode": "same_currency_identity_only",
                                                "required_source_currency": rule["expression"]["target_currency"],
                                                "on_non_identity": "manual_review", "external_rates_available": False}

        job_warnings = []
        for path, report, _ in evidence:
            for warning in report["warnings"]:
                job_warnings.append({**warning, "validation_report": _display_path(path)})
            for error in report["errors"]:
                job_warnings.append(_warning("VALIDATION_FAILURE", f"{_display_path(path)}: {error['message']}", error["location"]))
        guard_rules = [{"target_field": field["name"], "type": field["type"], "nullable": field["nullable"],
                        "on_null": "allow_with_warning" if field["nullable"] else "quarantine_row",
                        "on_type_error": "quarantine_row",
                        "allowed_values": [value.strip() for value in field["type"][5:-1].split(",")] if field["type"].startswith("enum(") else None}
                       for field in table["fields"]]
        foreign_key = {"field": "unified_customer_id", "references": "unified_customers.unified_customer_id",
                       "source_lookup_fields": ["source_system", "source_customer_id"],
                       "status": "manual_review", "enabled": False} if mapping["table_type"] == "order" else None
        jobs.append({"source_file": _display_path(source_path), "target_table": table_name,
                     "table_type": mapping["table_type"], "read_options": {"format": "csv", "encoding": "utf-8-sig",
                         "delimiter": ",", "header": True, "preserve_source_column_names": True},
                     "field_mappings": field_mappings, "transformation_steps": steps,
                     "missing_value_policy": {"version": "1.1", "markers": ["", "N/A", "null", "none"],
                         "case_sensitive": False, "nullable_target_action": "set_null_with_warning",
                         "required_target_action": "quarantine_row", "preserve_raw_targets": ["status_raw"]},
                     "validation_rules": {"fields": guard_rules, "primary_key": {"field": table["primary_key"],
                         "required": True, "unique": True, "on_violation": "quarantine_row"},
                         "foreign_key": foreign_key,
                         "conditional_currency_requirement": {"amount_field": "amount_original", "currency_field": "currency_code",
                             "when": "amount_original is not null", "on_missing_currency": "quarantine_row"} if mapping["table_type"] == "order" else None},
                     "reject_policy": {"status": "draft_policy", "on_missing_required_field": "quarantine_row",
                         "on_invalid_type": "quarantine_row", "on_manual_review": "hold_for_review", "drop_silently": False},
                     "loading_behavior": {"enabled": False, "mode": "dry_run_only", "destination": None,
                         "write_strategy": "manual_review", "duplicate_policy": "hold_for_review",
                         "idempotency_fields": ["source_system", "source_customer_id" if mapping["table_type"] == "customer" else "source_order_id"],
                         "status": "manual_review", "reason": "Loading needs resolved required rules and human approval; no database integration in the MVP."},
                     "unmapped_target_fields": mapping["unmapped_target_fields"], "warnings": job_warnings,
                     "validation_evidence": [{"report": _display_path(path), "scope": scope,
                          "source_csv": _display_path(report["source_csv"]), "rows_checked": report["sampling"]["rows_checked"],
                          "summary": report["summary"], "input_sha256": report["input_sha256"]} for path, report, scope in evidence]})
    if {job["table_type"] for job in jobs} != {"customer", "order"}:
        raise ValueError("A customer config needs one customer job and one order job.")
    if set(additions) != consumed_extra:
        raise ValueError("Additional validation reports must all belong to this customer's mappings.")
    jobs.sort(key=lambda job: 0 if job["table_type"] == "customer" else 1)
    review_count = sum(field["manual_review"] for job in jobs for field in job["field_mappings"])
    return {"config_version": "2.0", "contract_version": "1.4", "source_system": source_system,
            "schema_version": schema["schema_version"], "status": "draft", "production_ready": False,
            "review_policy": {"minimum_confidence": 0.70, "all_validation_datasets_must_pass": True,
                              "production_approval_from_samples": False},
            "input_files": [job["source_file"] for job in jobs], "target_tables": [job["target_table"] for job in jobs],
            "jobs": jobs, "loading_behavior": {"enabled": False, "mode": "dry_run_only", "destination": None,
                "load_order": ["unified_customers", "unified_orders"], "requires_human_approval": True,
                "required_review_fields": review_count},
            "summary": {"tables": len(jobs), "fields_total": sum(len(job["field_mappings"]) for job in jobs),
                "fields_validated_for_dry_run": sum(field["enabled_for_dry_run"] for job in jobs for field in job["field_mappings"]),
                "fields_manual_review": review_count},
            "provenance": {"unified_schema": _display_path(schema_path), "unified_schema_sha256": _digest(schema_path),
                "mapping_files": [_display_path(path) for path in mapping_paths]}, "warnings": warnings}
