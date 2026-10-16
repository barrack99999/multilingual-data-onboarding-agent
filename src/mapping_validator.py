"""Execute mapping rules on sample rows without an LLM or a database."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from itertools import islice
from pathlib import Path
from typing import Any

import yaml

from src.transform_helpers import (
    MISSING, TEST_FIXED_RATES, ManualReviewRequired, TransformationError,
    convert_currency, decimal_value, default_value, is_missing, map_status, normalize_missing,
    parse_date, split_name,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPRESSION_KEYS = {
    "direct": {"operation"},
    "rename": {"operation"},
    "parse_date": {"input_formats", "output_format", "on_error"},
    "map_value": {"value_map", "case_sensitive", "trim_before_match", "unmapped_action"},
    "split": {"delimiter", "part_index", "trim", "on_error"},
    "currency_conversion": {"amount_field", "currency_field", "target_currency", "rate_source",
                            "conversion_date_field", "rounding_decimals", "on_missing_rate"},
    "default_value": {"value", "apply_when"},
    "manual_review": {"requested_operation", "proposed_logic"},
}
RULE_KEYS = {"target_field", "source_fields", "transformation_type", "expression",
             "example_input", "example_output", "notes", "confidence", "evidence",
             "status", "manual_review", "review_reason"}
DOCUMENT_KEYS = {"mapping_version", "source_system", "source_file", "table_type", "target_table",
                 "rules", "unmapped_source_fields", "unmapped_target_fields", "warnings"}


class UniqueKeyLoader(yaml.SafeLoader):
    """Prevent silent loss of duplicate YAML keys."""


def _unique_mapping(loader: UniqueKeyLoader, node: Any, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Duplicate YAML key {key!r}; quote status keys such as OFF.")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def json_ready(value: Any) -> Any:
    """Keep decimals exact in reports and turn YAML date objects into strings."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def _schema_value(value: Any, field: dict) -> None:
    """Check target compatibility; CSV decimal strings may remain strings."""
    if value is None:
        if not field["nullable"]:
            raise TransformationError(f"Required target {field['name']} cannot be null.")
        return
    kind = field["type"]
    if kind == "date":
        if not isinstance(value, str):
            raise TransformationError("Target date must be an ISO string.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise TransformationError(f"Target date {value!r} is invalid.") from error
        if parsed.isoformat() != value:
            raise TransformationError("Target date must use YYYY-MM-DD.")
    elif kind.startswith("decimal("):
        number = decimal_value(value)
        precision, scale = map(int, re.fullmatch(r"decimal\((\d+),(\d+)\)", kind).groups())
        if number != number.quantize(Decimal(1).scaleb(-scale)):
            raise TransformationError(f"Value {value!r} exceeds target scale {scale}.")
        if abs(number) >= Decimal(10) ** (precision - scale):
            raise TransformationError(f"Value {value!r} exceeds target precision {precision}.")
    elif kind.startswith("enum("):
        allowed = [item.strip() for item in kind[5:-1].split(",")]
        if value not in allowed:
            raise TransformationError(f"Target value {value!r} is outside enum {allowed}.")
    elif kind.startswith("string"):
        if not isinstance(value, str):
            raise TransformationError(f"Target {field['name']} must contain a string.")
        limit = re.fullmatch(r"string\((\d+)\)", kind)
        if limit and len(value) != int(limit.group(1)):
            raise TransformationError(f"Target {field['name']} requires {limit.group(1)} characters.")
        if not field["nullable"] and is_missing(value):
            raise TransformationError(f"Required target {field['name']} is empty.")
    else:
        raise TransformationError(f"Unsupported schema type {kind!r}.")


def _config_errors(rule: Any, columns: list[str], targets: dict) -> list[str]:
    if not isinstance(rule, dict):
        return ["Rule must be an object."]
    errors = []
    if set(rule) != RULE_KEYS:
        errors.append(f"Rule keys: missing={sorted(RULE_KEYS - set(rule))}; extra={sorted(set(rule) - RULE_KEYS)}.")
    target = rule.get("target_field")
    if not isinstance(target, str) or target not in targets:
        errors.append(f"Unknown target field {target!r}.")
    sources = rule.get("source_fields")
    if not isinstance(sources, list) or not all(isinstance(item, str) for item in sources):
        return errors + ["source_fields must be a list of strings."]
    if len(sources) != len(set(sources)):
        errors.append("source_fields contains duplicates.")
    unknown = set(sources) - set(columns)
    if unknown:
        errors.append(f"Source columns do not exist: {sorted(unknown)}.")
    example = rule.get("example_input")
    if not isinstance(example, dict) or set(example) != set(sources):
        errors.append("example_input keys must match source_fields exactly.")
    if type(rule.get("manual_review")) is not bool:
        errors.append("manual_review must be a boolean.")
    confidence = rule.get("confidence")
    if type(confidence) not in {int, float} or not 0 <= confidence <= 1:
        errors.append("confidence must be between 0 and 1.")
    if not isinstance(rule.get("evidence"), list) or not rule["evidence"] or not all(
        isinstance(item, str) and item for item in rule["evidence"]
    ):
        errors.append("evidence must be a non-empty list of strings.")
    if not isinstance(rule.get("notes"), str):
        errors.append("notes must be a string.")
    if rule.get("status") not in {"accepted", "needs_review", "rejected"}:
        errors.append("Invalid rule status.")
    if rule.get("manual_review") or rule.get("status") == "needs_review":
        if not isinstance(rule.get("review_reason"), str) or not rule["review_reason"].strip():
            errors.append("A review rule must have a review_reason.")
    elif rule.get("review_reason") is not None:
        errors.append("Non-review rules must use review_reason: null.")
    kind = rule.get("transformation_type")
    if not isinstance(kind, str):
        return errors + ["transformation_type must be a string."]
    expression = rule.get("expression")
    if not isinstance(expression, dict):
        return errors + ["expression must be an object."]
    if kind not in EXPRESSION_KEYS:
        # Unsupported transformations are reported for review, not executed.
        return errors
    if set(expression) != EXPRESSION_KEYS[kind]:
        return errors + [f"{kind} expression must have exactly {sorted(EXPRESSION_KEYS[kind])}."]
    if kind == "default_value":
        if sources:
            errors.append("Version 1 default_value must be source-free.")
        try:
            default_value(expression["value"], expression["apply_when"])
        except ManualReviewRequired:
            pass
        except TransformationError as error:
            errors.append(str(error))
    elif not sources:
        errors.append(f"{kind} requires at least one source field.")
    if kind in {"direct", "rename", "parse_date", "split", "map_value"} and len(sources) != 1:
        errors.append(f"{kind} requires exactly one source field.")
    if kind in {"direct", "rename"} and expression["operation"] != "copy":
        errors.append("direct and rename support operation: copy only.")
    if kind in {"direct", "rename"} and len(sources) == 1:
        if (kind == "direct") != (sources[0] == target):
            errors.append("Use direct for identical names and rename for different names.")
    if kind in {"parse_date", "split", "map_value", "currency_conversion"}:
        key = {"parse_date": "on_error", "split": "on_error", "map_value": "unmapped_action",
               "currency_conversion": "on_missing_rate"}[kind]
        actions = {"null", "manual_review", "reject_row"}
        if kind == "map_value":
            actions.add("preserve_original")
        if expression[key] not in actions:
            errors.append(f"{key} must be an action string such as \"null\"; quote it in YAML.")
    if kind == "parse_date":
        formats = expression["input_formats"]
        if not isinstance(formats, list) or not formats or not all(isinstance(item, str) and item for item in formats):
            errors.append("input_formats must be a non-empty string list.")
        if expression["output_format"] != "%Y-%m-%d":
            errors.append("Unified date output_format must be %Y-%m-%d.")
    if kind == "map_value":
        if not isinstance(expression["value_map"], dict) or not expression["value_map"]:
            errors.append("value_map must be a non-empty object.")
        if any(type(expression[key]) is not bool for key in ("case_sensitive", "trim_before_match")):
            errors.append("Status normalization flags must be booleans.")
    if kind == "currency_conversion":
        for key in ("amount_field", "currency_field", "conversion_date_field"):
            if expression[key] not in sources:
                errors.append(f"{key} must name a listed source field.")
        if not isinstance(expression["rate_source"], str) or not expression["rate_source"]:
            errors.append("rate_source must name a rate source.")
        if not isinstance(expression["target_currency"], str) or not re.fullmatch(r"[A-Z]{3}", expression["target_currency"]):
            errors.append("target_currency must be a three-letter uppercase currency code.")
        if type(expression["rounding_decimals"]) is not int or not 0 <= expression["rounding_decimals"] <= 6:
            errors.append("rounding_decimals must be an integer from 0 to 6.")
    if kind == "split":
        if not isinstance(expression["delimiter"], str) or not expression["delimiter"]:
            errors.append("split delimiter must be a non-empty string.")
        if type(expression["part_index"]) is not int or expression["part_index"] < 0:
            errors.append("split part_index must be a non-negative integer.")
        if type(expression["trim"]) is not bool:
            errors.append("split trim must be boolean.")
    if kind == "manual_review":
        if expression["requested_operation"] not in {"merge", "prefix", "normalize_phone", "other"}:
            errors.append("Unsupported manual-review requested_operation.")
        if not isinstance(expression["proposed_logic"], str) or not expression["proposed_logic"].strip():
            errors.append("manual_review requires non-empty proposed_logic.")
    if kind == "manual_review" and not rule.get("manual_review"):
        errors.append("manual_review transformation must set manual_review: true.")
    return errors


def _execute(rule: dict, row: dict, *, preview_fixed_rates: bool = False) -> tuple[Any, list[str]]:
    kind, expression = rule["transformation_type"], rule["expression"]
    if kind not in EXPRESSION_KEYS or kind == "manual_review":
        raise ManualReviewRequired(rule.get("review_reason") or f"Unsupported transformation {kind!r}.")
    sources = rule["source_fields"]
    raw = row.get(sources[0]) if sources else None
    if kind in {"direct", "rename"}:
        return raw, []
    if kind == "default_value":
        return default_value(expression["value"], expression["apply_when"], row.get(rule["target_field"], MISSING)), []
    if kind == "currency_conversion":
        if is_missing(row[expression["amount_field"]]):
            return None, ["Source amount is missing; conversion yields null, subject to target nullability."]
        currency = row[expression["currency_field"]]
        target = expression["target_currency"]
        # Same-currency conversion is identity and needs no external dated rate.
        if str(currency).strip().upper() != str(target).strip().upper():
            if expression["rate_source"] != "test_fixed_rates" and not preview_fixed_rates:
                raise ManualReviewRequired("No approved dated rate table was supplied; test fixtures are available only as a preview.")
        rates = TEST_FIXED_RATES
        if str(currency).strip().upper() != str(target).strip().upper() and (
            str(currency).strip().upper() not in rates or str(target).strip().upper() not in rates
        ):
            message = f"No fictional fixed rate is configured for {currency} to {target}."
            action = expression["on_missing_rate"]
            if action == "null":
                return None, [message + " Applied declared null policy."]
            if action == "manual_review":
                raise ManualReviewRequired(message)
            raise TransformationError(message + " Row rejected by declared policy.")
        value = convert_currency(row[expression["amount_field"]], currency, target, rates,
                                 expression["rounding_decimals"])
        warnings = [] if str(currency).strip().upper() == str(target).strip().upper() else [
            "Used fictional fixed-rate test fixtures; this is not a production exchange-rate result."
        ]
        return value, warnings
    try:
        if kind == "parse_date":
            return parse_date(raw, expression["input_formats"], expression["output_format"]), []
        if kind == "split":
            return split_name(raw, expression["delimiter"], expression["part_index"], expression["trim"]), []
        if kind == "map_value":
            return map_status(raw, expression["value_map"], expression["case_sensitive"], expression["trim_before_match"]), []
    except ManualReviewRequired:
        # Ambiguous dates and complex names are always surfaced for human review.
        raise
    except TransformationError as error:
        action = expression.get("on_error", expression.get("unmapped_action"))
        if action == "null":
            return None, [f"{error} Applied declared null policy."]
        if action == "preserve_original":
            return raw, [f"{error} Applied preserve_original policy."]
        if action == "manual_review":
            raise ManualReviewRequired(str(error)) from error
        raise TransformationError(f"{error} Row rejected by declared policy.") from error
    raise TransformationError(f"No executor for {kind!r}.")


def _execute_checked(rule: dict, row: dict, field: dict, *, preview_fixed_rates: bool = False) -> tuple[Any, list[str]]:
    value, warnings = _execute(rule, row, preview_fixed_rates=preview_fixed_rates)
    if field["name"] != "status_raw" and is_missing(value):
        previous = value
        value = normalize_missing(value, field["nullable"], field["name"])
        if previous is not None:
            warnings.append(f"Normalized missing marker {previous!r} to null for nullable target {field['name']}.")
    _schema_value(value, field)
    return value, warnings


def _equal_example(actual: Any, expected: Any) -> bool:
    if isinstance(actual, Decimal):
        try:
            return actual == decimal_value(expected)
        except TransformationError:
            return False
    return type(actual) is type(expected) and actual == expected


def validate_sample_mapping(
    csv_path: str | Path,
    mapping_path: str | Path,
    schema_path: str | Path,
    *,
    sample_size: int = 20,
    preview_review_currency: bool = False,
) -> dict:
    """Return exclusive rule totals plus row results, diagnostics and sample output."""
    if type(sample_size) is not int or sample_size < 1:
        raise ValueError("sample_size must be a positive integer.")
    csv_path, mapping_path = Path(csv_path), Path(mapping_path)
    mapping = yaml.load(mapping_path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    if not isinstance(mapping, dict) or set(mapping) != DOCUMENT_KEYS:
        raise ValueError("Mapping document must contain exactly the Version 1 top-level keys.")
    if mapping["mapping_version"] != "1.0":
        raise ValueError("Only mapping_version '1.0' is supported.")
    for key in ("source_file", "source_system"):
        if not isinstance(mapping[key], str) or not mapping[key].strip():
            raise ValueError(f"{key} must be a non-empty string.")
    expected_table = {"customer": "unified_customers", "order": "unified_orders"}.get(mapping["table_type"])
    if expected_table is None or mapping["target_table"] != expected_table:
        raise ValueError("table_type and target_table do not agree.")
    if not isinstance(mapping["rules"], list) or not mapping["rules"]:
        raise ValueError("Mapping must contain a non-empty rules list.")
    for key in ("unmapped_source_fields", "unmapped_target_fields", "warnings"):
        if not isinstance(mapping[key], list) or not all(isinstance(item, str) for item in mapping[key]):
            raise ValueError(f"{key} must be a list of strings.")
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    table = next((item for item in schema["tables"] if item["name"] == expected_table), None)
    if table is None:
        raise ValueError(f"Unified schema has no table {expected_table}.")
    targets = {item["name"]: item for item in table["fields"]}
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        if not columns or len(columns) != len(set(columns)):
            raise ValueError("CSV must contain a header with unique column names.")
        rows = list(islice(reader, sample_size))
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("CSV contains a row whose width differs from the header.")

    errors, warnings, rule_reports = [], [], []
    previews = [{"csv_row": index + 2, "values": {}, "field_statuses": {}} for index in range(len(rows))]

    def diagnostic(code: str, message: str, location: str, *, warning: bool = False) -> None:
        item = {"code": code, "message": message, "location": location}
        item.update({"suggested_action": "Inspect the affected rule or source value."} if warning else {"retryable": False})
        (warnings if warning else errors).append(item)

    target_counts = Counter(rule.get("target_field") for rule in mapping["rules"] if isinstance(rule, dict))
    mapped_targets = set(target_counts)
    unmapped_targets = set(mapping["unmapped_target_fields"])
    for target, field in targets.items():
        if target not in mapped_targets:
            if target not in unmapped_targets or not field["nullable"]:
                diagnostic("UNMAPPED_TARGET", f"Target {target!r} needs an explicit rule or a nullable unmapped declaration.", "unmapped_target_fields")
            else:
                diagnostic("NULLABLE_UNMAPPED_TARGET", f"Nullable target {target!r} has no source mapping.", "unmapped_target_fields", warning=True)
                for preview in previews:
                    preview["values"][target] = None
                    preview["field_statuses"][target] = "unmapped"
    if unmapped_targets - set(targets) or unmapped_targets & mapped_targets:
        diagnostic("INVALID_UNMAPPED_TARGET", "unmapped_target_fields includes an unknown or mapped target.", "unmapped_target_fields")
    used_sources = {source for rule in mapping["rules"] if isinstance(rule, dict)
                    for source in (rule.get("source_fields") or []) if isinstance(source, str)}
    unmapped_sources = set(mapping["unmapped_source_fields"])
    if set(columns) - used_sources - unmapped_sources or unmapped_sources - set(columns) or used_sources & unmapped_sources:
        diagnostic("INVALID_SOURCE_COVERAGE", "Source fields are unaccounted for, unknown, or both used and unmapped.", "unmapped_source_fields")
    for message in mapping["warnings"]:
        diagnostic("MAPPING_WARNING", message, "warnings", warning=True)

    for rule_index, rule in enumerate(mapping["rules"]):
        location = f"rules[{rule_index}]"
        target = rule.get("target_field", f"rule_{rule_index}") if isinstance(rule, dict) else f"rule_{rule_index}"
        kind = rule.get("transformation_type") if isinstance(rule, dict) else None
        config_errors = _config_errors(rule, columns, targets)
        if target_counts[target] > 1:
            config_errors.append("Duplicate target rules would overwrite each other's values.")
        report = {"target_field": target, "transformation_type": kind, "status": "passed",
                  "rows_passed": 0, "rows_failed": 0, "rows_manual_review": 0,
                  "rows_with_warnings": 0, "example_check": {"status": "not_executed"},
                  "configuration_errors": config_errors, "row_results": []}
        if config_errors:
            report["status"] = "failed"
            for message in config_errors:
                diagnostic("INVALID_RULE", message, location)
            rule_reports.append(report)
            for preview in previews:
                preview["values"][target] = None
                preview["field_statuses"][target] = "failed"
            continue
        review = rule["manual_review"] or rule["status"] == "needs_review" or kind == "manual_review" or kind not in EXPRESSION_KEYS
        if rule["status"] == "rejected":
            report["status"] = "failed"
            diagnostic("REJECTED_RULE", "A rejected rule cannot be executed.", location)
        elif review:
            report["status"] = "manual_review"
            diagnostic("MANUAL_REVIEW", rule["review_reason"] or f"Unsupported transformation {kind!r}.", location, warning=True)
        elif not rows:
            report["status"] = "manual_review"
            diagnostic("EMPTY_SAMPLE", "No data rows available to test this rule.", location, warning=True)
        else:
            try:
                actual, example_warnings = _execute_checked(rule, rule["example_input"], targets[target])
                matches = _equal_example(actual, rule["example_output"])
                report["example_check"] = {"status": "passed" if matches else "failed",
                                           "expected": rule["example_output"], "actual": actual,
                                           "warnings": example_warnings}
                if not matches:
                    report["status"] = "failed"
                    diagnostic("EXAMPLE_MISMATCH", "Executed example does not equal the declared example_output.", location)
            except ManualReviewRequired as error:
                report["example_check"] = {"status": "manual_review", "message": str(error)}
                report["status"] = "manual_review"
                diagnostic("EXAMPLE_REVIEW", str(error), location, warning=True)
            except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as error:
                report["example_check"] = {"status": "failed", "message": str(error)}
                report["status"] = "failed"
                diagnostic("EXAMPLE_FAILED", str(error), location)

        for row_index, row in enumerate(rows):
            result = {"csv_row": row_index + 2, "status": "passed", "value": None, "warnings": []}
            if rule["status"] == "rejected":
                result.update(status="failed", message="Rule is rejected.")
            elif review:
                result.update(status="manual_review", message=rule["review_reason"] or f"Unsupported transformation {kind!r}.")
                if preview_review_currency and kind == "currency_conversion":
                    try:
                        value, notes = _execute_checked(rule, row, targets[target], preview_fixed_rates=True)
                        result["test_preview"] = {"value": value, "warnings": notes,
                                                  "rate_source": "fictional_test_fixed_rates", "approved": False}
                    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as error:
                        result["test_preview"] = {"error": str(error), "approved": False}
            else:
                try:
                    result["value"], result["warnings"] = _execute_checked(rule, row, targets[target])
                except ManualReviewRequired as error:
                    result.update(status="manual_review", message=str(error))
                except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as error:
                    result.update(status="failed", message=str(error))
            report[f"rows_{result['status']}"] += 1
            if result["warnings"]:
                report["rows_with_warnings"] += 1
                for message in result["warnings"]:
                    diagnostic("HANDLED_VALUE", message, f"{location}.csv_row[{row_index + 2}]", warning=True)
            if result["status"] != "passed" and not review and rule["status"] != "rejected":
                diagnostic("TRANSFORMATION_FAILED" if result["status"] == "failed" else "VALUE_REVIEW",
                           result["message"], f"{location}.csv_row[{row_index + 2}]", warning=result["status"] == "manual_review")
            report["row_results"].append(result)
            previews[row_index]["values"][target] = result["value"]
            previews[row_index]["field_statuses"][target] = result["status"]
        if report["rows_failed"]:
            report["status"] = "failed"
        elif report["rows_manual_review"] and report["status"] != "failed":
            report["status"] = "manual_review"
        rule_reports.append(report)

    counts = Counter(report["status"] for report in rule_reports)
    summary = {"rules_total": len(rule_reports), "rules_passed": counts["passed"],
               "rules_failed": counts["failed"], "rules_manual_review": counts["manual_review"],
               "error_count": len(errors), "warning_count": len(warnings)}
    ready = not errors and not counts["failed"] and not counts["manual_review"] and bool(rows)
    for preview in previews:
        preview["all_mapped_fields_passed"] = all(status in {"passed", "unmapped"} for status in preview["field_statuses"].values())
    return json_ready({"report_version": "1.0", "source_system": mapping["source_system"],
                       "source_csv": str(csv_path), "mapping_yaml": str(mapping_path),
                       "target_table": expected_table, "sampling": {"method": "first_n_rows", "limit": sample_size, "rows_checked": len(rows)},
                       "status": "error" if errors else "warning" if warnings else "success",
                       "ready_for_etl": ready, "summary": summary, "rules": rule_reports,
                       "sample_transformed_rows": previews, "errors": errors, "warnings": warnings,
                       "test_rates": {"fictional": True, "usd_per_unit": TEST_FIXED_RATES,
                                      "review_currency_preview_enabled": preview_review_currency},
                       "input_sha256": {
                           "source_csv": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                           "mapping_yaml": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
                           "unified_schema": hashlib.sha256(Path(schema_path).read_bytes()).hexdigest(),
                           "validator": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           "transform_helpers": hashlib.sha256((PROJECT_ROOT / "src/transform_helpers.py").read_bytes()).hexdigest(),
                       }})
