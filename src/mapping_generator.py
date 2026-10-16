"""LLM-backed mapping generation with deterministic validation and YAML output."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from openai import DefaultHttpxClient, OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError


TransformationType = Literal[
    "direct",
    "rename",
    "parse_date",
    "map_value",
    "split",
    "currency_conversion",
    "default_value",
    "manual_review",
]
RuleStatus = Literal["accepted", "needs_review", "rejected"]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
)


class MappingRule(BaseModel):
    """One source-to-target rule in Mapping Format Version 1."""

    model_config = ConfigDict(extra="forbid")

    target_field: str
    source_fields: list[str]
    transformation_type: TransformationType
    expression: dict[str, Any]
    example_input: dict[str, Any]
    example_output: Any
    notes: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)
    status: RuleStatus
    manual_review: bool
    review_reason: str | None


class MappingDocument(BaseModel):
    """One mapping document for one source CSV table."""

    model_config = ConfigDict(extra="forbid")

    mapping_version: Literal["1.0"]
    source_system: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    table_type: Literal["customer", "order"]
    target_table: Literal["unified_customers", "unified_orders"]
    rules: list[MappingRule] = Field(min_length=1)
    unmapped_source_fields: list[str]
    unmapped_target_fields: list[str]
    warnings: list[str]


EXPRESSION_KEYS = {
    "direct": {"operation"},
    "rename": {"operation"},
    "parse_date": {"input_formats", "output_format", "on_error"},
    "map_value": {
        "value_map",
        "case_sensitive",
        "trim_before_match",
        "unmapped_action",
    },
    "split": {"delimiter", "part_index", "trim", "on_error"},
    "currency_conversion": {
        "amount_field",
        "currency_field",
        "target_currency",
        "rate_source",
        "conversion_date_field",
        "rounding_decimals",
        "on_missing_rate",
    },
    "default_value": {"value", "apply_when"},
    "manual_review": {"requested_operation", "proposed_logic"},
}


def load_system_prompt(path: str | Path) -> str:
    """Load the system prompt from the Task 2 Markdown deliverable."""
    text = Path(path).read_text(encoding="utf-8")
    start_marker = "## System prompt\n\n```text\n"
    start = text.find(start_marker)
    if start == -1:
        raise ValueError(f"System prompt start marker not found in {path}")
    start += len(start_marker)
    end = text.find("\n```", start)
    if end == -1:
        raise ValueError(f"System prompt closing fence not found in {path}")
    return text[start:end].strip()


def selected_target_table(
    unified_schema: dict[str, Any], table_type: str
) -> dict[str, Any]:
    """Return the unified table corresponding to a source table type."""
    expected_name = (
        "unified_customers" if table_type == "customer" else "unified_orders"
    )
    for table in unified_schema.get("tables", []):
        if table.get("name") == expected_name:
            return table
    raise ValueError(f"Unified schema does not contain {expected_name}.")


def _validate_expression(rule: MappingRule) -> list[str]:
    errors: list[str] = []
    kind = rule.transformation_type
    expression = rule.expression
    expected_keys = EXPRESSION_KEYS[kind]
    actual_keys = set(expression)
    if actual_keys != expected_keys:
        errors.append(
            f"{rule.target_field}: {kind} expression keys must be "
            f"{sorted(expected_keys)}, received {sorted(actual_keys)}."
        )
        return errors

    if kind in {"direct", "rename"} and expression.get("operation") != "copy":
        errors.append(f"{rule.target_field}: {kind}.operation must be copy.")

    if kind == "parse_date":
        formats = expression.get("input_formats")
        if not isinstance(formats, list) or not formats or not all(
            isinstance(item, str) and item for item in formats
        ):
            errors.append(
                f"{rule.target_field}: parse_date.input_formats must be a non-empty string list."
            )
        if expression.get("output_format") != "%Y-%m-%d":
            errors.append(
                f"{rule.target_field}: parse_date.output_format must be %Y-%m-%d."
            )
        if expression.get("on_error") not in {"null", "manual_review", "reject_row"}:
            errors.append(f"{rule.target_field}: invalid parse_date.on_error.")

    if kind == "map_value":
        value_map = expression.get("value_map")
        if not isinstance(value_map, dict) or not value_map:
            errors.append(f"{rule.target_field}: value_map must be a non-empty object.")
        if not isinstance(expression.get("case_sensitive"), bool):
            errors.append(f"{rule.target_field}: case_sensitive must be boolean.")
        if not isinstance(expression.get("trim_before_match"), bool):
            errors.append(f"{rule.target_field}: trim_before_match must be boolean.")
        if expression.get("unmapped_action") not in {
            "null",
            "manual_review",
            "reject_row",
            "preserve_original",
        }:
            errors.append(f"{rule.target_field}: invalid map_value.unmapped_action.")

    if kind == "split":
        if not isinstance(expression.get("delimiter"), str) or not expression.get(
            "delimiter"
        ):
            errors.append(f"{rule.target_field}: split.delimiter must be non-empty.")
        if not isinstance(expression.get("part_index"), int) or expression.get(
            "part_index", -1
        ) < 0:
            errors.append(f"{rule.target_field}: split.part_index must be >= 0.")
        if not isinstance(expression.get("trim"), bool):
            errors.append(f"{rule.target_field}: split.trim must be boolean.")
        if expression.get("on_error") not in {"null", "manual_review", "reject_row"}:
            errors.append(f"{rule.target_field}: invalid split.on_error.")

    if kind == "currency_conversion":
        for key in (
            "amount_field",
            "currency_field",
            "rate_source",
            "conversion_date_field",
        ):
            if not isinstance(expression.get(key), str) or not expression.get(key):
                errors.append(f"{rule.target_field}: {key} must be non-empty.")
        if expression.get("target_currency") != "USD":
            errors.append(f"{rule.target_field}: target_currency must be USD.")
        decimals = expression.get("rounding_decimals")
        if not isinstance(decimals, int) or not 0 <= decimals <= 6:
            errors.append(
                f"{rule.target_field}: rounding_decimals must be from 0 to 6."
            )
        if expression.get("on_missing_rate") not in {
            "null",
            "manual_review",
            "reject_row",
        }:
            errors.append(f"{rule.target_field}: invalid on_missing_rate.")

    if kind == "default_value" and expression.get("apply_when") not in {
        "source_missing",
        "source_null",
        "always",
    }:
        errors.append(f"{rule.target_field}: invalid default_value.apply_when.")

    if kind == "manual_review":
        if expression.get("requested_operation") not in {
            "merge",
            "prefix",
            "normalize_phone",
            "other",
        }:
            errors.append(f"{rule.target_field}: invalid requested_operation.")
        if not isinstance(expression.get("proposed_logic"), str) or not expression.get(
            "proposed_logic"
        ):
            errors.append(f"{rule.target_field}: proposed_logic must be non-empty.")

    return errors


def _read_source_values(source_file: str) -> dict[str, list[str]]:
    """Read unique non-empty source values for deterministic coverage checks."""
    path = Path(source_file)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_file():
        return {}
    values: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            for field, value in row.items():
                if value is None:
                    continue
                cleaned = value.strip()
                if not cleaned or cleaned.lower() in {"n/a", "null", "none"}:
                    continue
                values.setdefault(field, [])
                if cleaned not in values[field]:
                    values[field].append(cleaned)
    return values


def _matches_date(value: str, formats: list[str] | tuple[str, ...]) -> bool:
    for date_format in formats:
        try:
            datetime.strptime(value, date_format)
            return True
        except ValueError:
            continue
    return False


def _status_scope_errors(rule: MappingRule, observed: list[str]) -> list[str]:
    """Language hints are not approval to accept another source's categories."""
    if not observed:
        return []
    expression = rule.expression
    case_sensitive = expression.get("case_sensitive", True)
    trim = expression.get("trim_before_match", False)
    def canonical(value: Any) -> str:
        text = str(value).strip() if trim else str(value)
        return text if case_sensitive else text.casefold()
    keys = {canonical(key) for key in expression.get("value_map", {})}
    values = {canonical(value) for value in observed}
    errors = [f"order_status: observed status {value!r} is missing from value_map."
              for value in observed if canonical(value) not in keys]
    extra = keys - values
    if extra:
        errors.append("order_status: value_map contains statuses not observed in this source: "
                      f"{sorted(extra)}. Language hints are not source approval; remove these keys "
                      "and keep unfamiliar categories under manual_review.")
    return errors


def validate_mapping(
    mapping: dict[str, Any],
    field_analysis: dict[str, Any],
    unified_schema: dict[str, Any],
    source_system: str,
    source_file: str,
) -> list[str]:
    """Validate format and cross-file references with ordinary Python."""
    try:
        document = MappingDocument.model_validate(mapping)
    except ValidationError as error:
        return [f"Pydantic validation: {item['loc']}: {item['msg']}" for item in error.errors()]

    errors: list[str] = []
    expected_table = selected_target_table(unified_schema, field_analysis["table_type"])
    source_names = [field["field_name"] for field in field_analysis.get("fields", [])]
    source_set = set(source_names)
    target_names = [field["name"] for field in expected_table.get("fields", [])]
    target_set = set(target_names)
    currency_analysis = next(
        (
            field
            for field in field_analysis.get("fields", [])
            if field.get("semantic_type") == "currency"
        ),
        None,
    )
    currency_evidence = json.dumps(currency_analysis or {}, ensure_ascii=False).upper()
    source_currency_is_usd = "USD" in currency_evidence
    source_values = _read_source_values(source_file)

    if document.source_system != source_system:
        errors.append(
            f"source_system must be {source_system!r}, received {document.source_system!r}."
        )
    if document.source_file != source_file:
        errors.append(
            f"source_file must be {source_file!r}, received {document.source_file!r}."
        )
    if document.table_type != field_analysis["table_type"]:
        errors.append(
            f"table_type must be {field_analysis['table_type']!r}, received {document.table_type!r}."
        )
    if document.target_table != expected_table["name"]:
        errors.append(
            f"target_table must be {expected_table['name']!r}, received {document.target_table!r}."
        )

    mapped_targets = [rule.target_field for rule in document.rules]
    rules_by_target = {rule.target_field: rule for rule in document.rules}
    if len(mapped_targets) != len(set(mapped_targets)):
        errors.append("Each target field may appear in only one rule.")
    unknown_targets = set(mapped_targets) - target_set
    if unknown_targets:
        errors.append(f"Unknown target fields: {sorted(unknown_targets)}.")

    unknown_unmapped_targets = set(document.unmapped_target_fields) - target_set
    if unknown_unmapped_targets:
        errors.append(
            f"Unknown unmapped target fields: {sorted(unknown_unmapped_targets)}."
        )
    target_overlap = set(mapped_targets) & set(document.unmapped_target_fields)
    if target_overlap:
        errors.append(
            f"Targets cannot be mapped and unmapped together: {sorted(target_overlap)}."
        )
    missing_target_accounting = target_set - set(mapped_targets) - set(
        document.unmapped_target_fields
    )
    if missing_target_accounting:
        errors.append(
            f"Target fields not accounted for: {sorted(missing_target_accounting)}."
        )

    source_system_rule = rules_by_target.get("source_system")
    if source_system_rule is None:
        errors.append(
            "source_system must be mapped with default_value; it may not be left unmapped."
        )
    elif not (
        source_system_rule.transformation_type == "default_value"
        and source_system_rule.expression.get("value") == source_system
        and source_system_rule.expression.get("apply_when") == "always"
    ):
        errors.append(
            "source_system must use default_value with the supplied source name and apply_when always."
        )

    generated_targets = {expected_table.get("primary_key")}
    if document.table_type == "order":
        generated_targets.add("unified_customer_id")
    for target in sorted(item for item in generated_targets if item):
        rule = rules_by_target.get(target)
        if rule is None:
            errors.append(
                f"{target} must have an explicit manual_review rule describing key generation or lookup."
            )
        elif not (
            rule.transformation_type == "manual_review"
            and rule.expression.get("requested_operation") == "other"
        ):
            errors.append(
                f"{target} must use manual_review with requested_operation other."
            )
    if document.table_type == "order" and "amount_usd" not in rules_by_target:
        errors.append(
            "amount_usd must have an explicit currency_conversion rule; use "
            "manual_review when no approved exchange-rate data is supplied."
        )

    used_sources: set[str] = set()
    for rule in document.rules:
        used_sources.update(rule.source_fields)
        unknown_sources = set(rule.source_fields) - source_set
        if unknown_sources:
            errors.append(
                f"{rule.target_field}: unknown source fields {sorted(unknown_sources)}."
            )
        if rule.transformation_type == "default_value":
            if rule.source_fields:
                errors.append(
                    f"{rule.target_field}: default_value must have no source fields."
                )
            if rule.example_input:
                errors.append(
                    f"{rule.target_field}: source-free default example_input must be empty."
                )
        elif not rule.source_fields:
            errors.append(
                f"{rule.target_field}: {rule.transformation_type} needs a source field."
            )
        if rule.transformation_type == "direct" and len(rule.source_fields) == 1:
            if rule.source_fields[0] != rule.target_field:
                errors.append(
                    f"{rule.target_field}: use rename because source and target names differ."
                )
        if rule.transformation_type == "rename" and len(rule.source_fields) == 1:
            if rule.source_fields[0] == rule.target_field:
                errors.append(
                    f"{rule.target_field}: use direct because source and target names are identical."
                )
        if rule.transformation_type in {"direct", "rename"} and len(
            rule.source_fields
        ) == 1:
            source_example = rule.example_input.get(rule.source_fields[0])
            if source_example != rule.example_output:
                errors.append(
                    f"{rule.target_field}: direct/rename must preserve the example value exactly."
                )
        if set(rule.example_input) != set(rule.source_fields):
            errors.append(
                f"{rule.target_field}: example_input keys must equal source_fields."
            )
        for example_field, example_value in rule.example_input.items():
            observed = source_values.get(example_field, [])
            if observed and example_value is not None and str(example_value) not in observed:
                errors.append(
                    f"{rule.target_field}: example input {example_field}={example_value!r} "
                    "does not appear in the source CSV."
                )
        if rule.manual_review:
            if not rule.review_reason:
                errors.append(f"{rule.target_field}: review_reason is required.")
            if rule.status != "needs_review":
                errors.append(
                    f"{rule.target_field}: manual-review rules must use needs_review status."
                )
        else:
            if rule.review_reason is not None:
                errors.append(
                    f"{rule.target_field}: accepted rule review_reason must be null."
                )
            if rule.status != "accepted":
                errors.append(
                    f"{rule.target_field}: non-review rules must use accepted status."
                )
        if rule.transformation_type == "manual_review" and not rule.manual_review:
            errors.append(
                f"{rule.target_field}: manual_review transformation must set manual_review true."
            )
        if rule.target_field == "phone" and rule.transformation_type != "manual_review":
            errors.append(
                "phone: Version 1 defers phone normalization; use manual_review "
                "with requested_operation normalize_phone."
            )
        if rule.target_field == "amount_usd":
            if rule.transformation_type != "currency_conversion":
                errors.append(
                    "amount_usd must use the supported currency_conversion transformation."
                )
            elif not source_currency_is_usd and not rule.manual_review:
                errors.append(
                    "amount_usd must remain needs_review because no approved non-USD "
                    "exchange-rate data was supplied."
                )
            if rule.transformation_type == "currency_conversion":
                referenced_sources = {
                    rule.expression.get("amount_field"),
                    rule.expression.get("currency_field"),
                    rule.expression.get("conversion_date_field"),
                }
                if not referenced_sources.issubset(set(rule.source_fields)):
                    errors.append(
                        "amount_usd expression fields must reference the listed source_fields."
                    )
        if rule.transformation_type == "parse_date" and len(rule.source_fields) == 1:
            input_formats = rule.expression.get("input_formats", [])
            for value in source_values.get(rule.source_fields[0], []):
                if _matches_date(value, COMMON_DATE_FORMATS) and not _matches_date(
                    value, input_formats
                ):
                    errors.append(
                        f"{rule.target_field}: observed date {value!r} is not covered "
                        f"by input_formats {input_formats}."
                    )
        if rule.target_field == "order_status" and rule.transformation_type == "map_value":
            errors.extend(_status_scope_errors(rule, source_values.get(rule.source_fields[0], [])))
        errors.extend(_validate_expression(rule))

    if len(document.unmapped_source_fields) != len(
        set(document.unmapped_source_fields)
    ):
        errors.append("unmapped_source_fields contains duplicates.")
    unknown_unmapped_sources = set(document.unmapped_source_fields) - source_set
    if unknown_unmapped_sources:
        errors.append(
            f"Unknown unmapped source fields: {sorted(unknown_unmapped_sources)}."
        )
    source_overlap = used_sources & set(document.unmapped_source_fields)
    if source_overlap:
        errors.append(
            f"Sources cannot be used and unmapped together: {sorted(source_overlap)}."
        )
    missing_source_accounting = source_set - used_sources - set(
        document.unmapped_source_fields
    )
    if missing_source_accounting:
        errors.append(
            f"Source fields not accounted for: {sorted(missing_source_accounting)}."
        )

    return errors


def build_user_prompt(
    field_analysis: dict[str, Any],
    unified_schema: dict[str, Any],
    source_system: str,
    source_file: str,
    open_issues: list[dict[str, Any]],
) -> str:
    """Create the per-table user prompt from structured inputs."""
    return (
        "Create one Version 1 mapping for the following source table.\n\n"
        f"SOURCE SYSTEM:\n{source_system}\n\n"
        f"SOURCE FILE PATH:\n{source_file}\n\n"
        "FIELD ANALYSIS JSON:\n"
        f"{json.dumps(field_analysis, ensure_ascii=False, indent=2)}\n\n"
        "UNIFIED SCHEMA JSON:\n"
        f"{json.dumps(unified_schema, ensure_ascii=False, indent=2)}\n\n"
        "WEEK 2 OPEN ISSUES FOR THIS TABLE:\n"
        f"{json.dumps(open_issues, ensure_ascii=False, indent=2)}\n\n"
        "Return only the structured mapping object. The program will validate "
        "it and serialize it to YAML."
    )


def normalize_model_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Normalize JSON/YAML representation details without changing decisions."""
    for key in ("unmapped_source_fields", "unmapped_target_fields", "warnings"):
        if candidate.get(key) is None:
            candidate[key] = []
    for rule in candidate.get("rules", []):
        if not isinstance(rule, dict):
            continue
        if isinstance(rule.get("source_fields"), str):
            rule["source_fields"] = [rule["source_fields"]]
        if isinstance(rule.get("evidence"), str):
            rule["evidence"] = [rule["evidence"]]
        kind = rule.get("transformation_type")
        expression = rule.get("expression")
        if not isinstance(expression, dict):
            continue
        if kind in {"direct", "rename"} and not expression:
            expression["operation"] = "copy"
        nullable_action = {
            "parse_date": "on_error",
            "split": "on_error",
            "map_value": "unmapped_action",
            "currency_conversion": "on_missing_rate",
        }.get(kind)
        if nullable_action and expression.get(nullable_action) is None:
            expression[nullable_action] = "null"
        if kind in {"direct", "rename"}:
            source_fields = rule.get("source_fields") or []
            example_input = rule.get("example_input") or {}
            if len(source_fields) == 1 and source_fields[0] in example_input:
                rule["example_output"] = example_input[source_fields[0]]

    rules_by_target = {
        rule.get("target_field"): rule
        for rule in candidate.get("rules", [])
        if isinstance(rule, dict)
    }
    generated_sources = {
        "unified_customer_id": "source_customer_id",
        "unified_order_id": "source_order_id",
    }
    for generated_target, source_target in generated_sources.items():
        generated_rule = rules_by_target.get(generated_target)
        source_rule = rules_by_target.get(source_target)
        if not isinstance(generated_rule, dict) or not isinstance(source_rule, dict):
            continue
        if generated_rule.get("transformation_type") != "manual_review":
            continue
        if not generated_rule.get("source_fields"):
            generated_rule["source_fields"] = list(source_rule.get("source_fields", []))
        if not generated_rule.get("example_input"):
            generated_rule["example_input"] = dict(source_rule.get("example_input", {}))

    phone_rule = rules_by_target.get("phone")
    if isinstance(phone_rule, dict) and phone_rule.get(
        "transformation_type"
    ) != "manual_review":
        phone_rule["transformation_type"] = "manual_review"
        phone_rule["expression"] = {
            "requested_operation": "normalize_phone",
            "proposed_logic": (
                "Normalize valid phone values only after a source-specific country-code "
                "and missing-value policy is approved."
            ),
        }
        phone_rule["example_output"] = None
        phone_rule["notes"] = (
            "Phone normalization is deferred in Mapping Format Version 1."
        )
        phone_rule["status"] = "needs_review"
        phone_rule["manual_review"] = True
        phone_rule["review_reason"] = (
            "The source contains mixed phone formats and Version 1 does not support "
            "normalize_phone."
        )

    amount_usd_rule = rules_by_target.get("amount_usd")
    if isinstance(amount_usd_rule, dict):
        expression = amount_usd_rule.get("expression")
        if isinstance(expression, dict) and {
            "amount_field",
            "currency_field",
            "target_currency",
            "rate_source",
            "conversion_date_field",
            "rounding_decimals",
            "on_missing_rate",
        }.issubset(expression):
            amount_usd_rule["transformation_type"] = "currency_conversion"
            amount_usd_rule["expression"] = {
                key: expression[key] for key in EXPRESSION_KEYS["currency_conversion"]
            }
            if amount_usd_rule["expression"].get("on_missing_rate") is None:
                amount_usd_rule["expression"]["on_missing_rate"] = "null"
    return candidate


def generate_mapping(
    field_analysis: dict[str, Any],
    unified_schema: dict[str, Any],
    source_system: str,
    source_file: str,
    open_issues: list[dict[str, Any]],
    *,
    prompt_path: str | Path,
    client: OpenAI | None = None,
    model: str | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Generate, validate, and return one mapping document."""
    system_prompt = load_system_prompt(prompt_path)
    api_client = client or OpenAI(
        http_client=DefaultHttpxClient(trust_env=False),
    )
    selected_model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    user_prompt = build_user_prompt(
        field_analysis,
        unified_schema,
        source_system,
        source_file,
        open_issues,
    )
    validation_errors: list[str] = []
    previous_candidate: dict[str, Any] | None = None

    for attempt in range(1, max_attempts + 1):
        request_input = user_prompt
        if validation_errors:
            request_input += (
                "\n\nThe previous draft failed validation. Correct every error and "
                "return the complete mapping object again. Do not omit required "
                "expression keys. When an error action means a null result, use "
                "the JSON string \"null\", not JSON null.\n\nPREVIOUS DRAFT:\n"
                + json.dumps(previous_candidate, ensure_ascii=False, indent=2)
                + "\n\nVALIDATION ERRORS:\n- "
                + "\n- ".join(validation_errors)
            )

        response = api_client.responses.create(
            model=selected_model,
            instructions=system_prompt,
            input=request_input,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "mapping_document",
                    "description": "One Version 1 source-to-unified-schema mapping.",
                    "schema": MappingDocument.model_json_schema(),
                    "strict": False,
                }
            },
            temperature=0,
            max_output_tokens=8000,
            store=False,
        )
        try:
            candidate = json.loads(response.output_text)
        except json.JSONDecodeError as error:
            validation_errors = [f"Response was not valid JSON: {error}"]
            continue
        candidate = normalize_model_candidate(candidate)
        previous_candidate = candidate

        validation_errors = validate_mapping(
            candidate,
            field_analysis,
            unified_schema,
            source_system,
            source_file,
        )
        if not validation_errors:
            return MappingDocument.model_validate(candidate).model_dump()

    raise ValueError(
        f"Mapping generation failed after {max_attempts} attempts:\n- "
        + "\n- ".join(validation_errors)
    )


def write_mapping_yaml(mapping: dict[str, Any], path: str | Path) -> None:
    """Write a validated mapping while preserving key order and Unicode."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(
            mapping,
            sort_keys=False,
            allow_unicode=True,
            width=100,
        ),
        encoding="utf-8",
    )
