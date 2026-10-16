"""Render reviewable documentation from schema, analyses and mapping drafts.

The schema owns target definitions; mappings own lineage and transformations.
Analysis supplies source interpretations, never overrides target definitions.
No LLM, source-row execution, or database access is required.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
from pathlib import Path
from typing import Any

import yaml

from src.mapping_validator import DOCUMENT_KEYS, EXPRESSION_KEYS, UniqueKeyLoader, _config_errors, json_ready

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "1.5"


class DictionaryInputError(ValueError):
    """Input problem with a stable diagnostics code and location."""

    def __init__(self, code: str, message: str, location: str):
        super().__init__(message)
        self.code, self.location = code, location


def _resolve(path: str | Path) -> Path:
    path = Path(path)
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def _display(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _fail(code: str, message: str, location: str) -> None:
    raise DictionaryInputError(code, f"{location}: {message}", location)


def _read_json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _fail(code, str(error), _display(path))
    if not isinstance(value, dict):
        _fail(code, "Expected a JSON object.", _display(path))
    return value


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(_text(item) for item in value) and len(value) == len(set(value))


def _schema(path: Path) -> dict:
    schema = _read_json(path, "INVALID_SCHEMA")
    tables = schema.get("tables")
    if not _text(schema.get("schema_version")) or not isinstance(tables, list) or not tables:
        _fail("INVALID_SCHEMA", "Require schema_version and nonempty tables.", _display(path))
    names = set()
    for table in tables:
        if not isinstance(table, dict) or not _text(table.get("name")) or table["name"] in names:
            _fail("INVALID_SCHEMA", "Table names must be nonempty and unique.", _display(path))
        names.add(table["name"])
        fields, field_names = table.get("fields"), set()
        if not isinstance(fields, list) or not fields:
            _fail("INVALID_SCHEMA", "Require nonempty fields.", table["name"])
        for field in fields:
            if not isinstance(field, dict) or not _text(field.get("name")) or field["name"] in field_names:
                _fail("INVALID_SCHEMA", "Field names must be nonempty and unique.", table["name"])
            location = f"{table['name']}.{field['name']}"
            field_names.add(field["name"])
            if not _text(field.get("description")):
                _fail("MISSING_REQUIRED_DESCRIPTION", "Schema business description is required.", location)
            if not _text(field.get("type")) or type(field.get("nullable")) is not bool:
                _fail("INVALID_SCHEMA", "Require a type string and boolean nullable.", location)
            coverage = field.get("source_coverage", {})
            if not isinstance(coverage, dict) or not _strings(coverage.get("sources", [])) or not _strings(coverage.get("source_fields", [])):
                _fail("INVALID_SCHEMA", "Invalid source coverage.", location)
        if table.get("primary_key") not in field_names:
            _fail("INVALID_SCHEMA", "Primary key must name an existing field.", table["name"])
    return schema


def _analyses(paths: list[Path]) -> dict:
    analyses = {}
    if not paths:
        _fail("INVALID_ANALYSIS", "Supply field analysis JSON.", "field_analyses")
    for path in paths:
        document = _read_json(path, "INVALID_ANALYSIS")
        entries = {document["file_name"]: document} if "file_name" in document else document
        if not entries:
            _fail("INVALID_ANALYSIS", "Analysis input is empty.", _display(path))
        for key, entry in entries.items():
            if not isinstance(entry, dict) or not _text(entry.get("file_name")) or entry["file_name"] != key:
                _fail("INVALID_ANALYSIS", "Analysis key must match file_name.", _display(path))
            if key in analyses:
                _fail("INVALID_ANALYSIS", "Duplicate analysis file_name.", key)
            if entry.get("table_type") not in {"customer", "order", "unknown"} or not isinstance(entry.get("fields"), list) or not entry["fields"]:
                _fail("INVALID_ANALYSIS", "Require table_type and nonempty fields.", key)
            fields = {}
            for field in entry["fields"]:
                if not isinstance(field, dict) or not _text(field.get("field_name")) or field["field_name"] in fields:
                    _fail("INVALID_ANALYSIS", "Source field names must be nonempty and unique.", key)
                if not _text(field.get("description")) or not _text(field.get("semantic_type")):
                    _fail("INVALID_ANALYSIS", "Require source description and semantic_type.", key)
                confidence = field.get("confidence")
                if type(confidence) not in {int, float} or not 0 <= confidence <= 1 or not isinstance(field.get("evidence"), list) or not field["evidence"]:
                    _fail("INVALID_ANALYSIS", "Require confidence 0..1 and evidence.", key)
                for evidence in field["evidence"]:
                    if not (_text(evidence) or (isinstance(evidence, dict) and _text(evidence.get("source")) and _text(evidence.get("detail")))):
                        _fail("INVALID_ANALYSIS", "Evidence must be text or source/detail objects.", key)
                fields[field["field_name"]] = field
            analyses[key] = {"entry": entry, "fields": fields, "analysis_file": _display(path)}
    return analyses


def _warning(code: str, message: str, location: str) -> dict:
    return {"code": code, "message": message, "location": location,
            "suggested_action": "Review source coverage or resolve the documented mapping issue; regenerate the dictionary after changes."}


def generate_data_dictionary(
    schema_path: str | Path,
    analysis_paths: list[str | Path],
    mapping_paths: list[str | Path],
) -> dict[str, Any]:
    """Return schema-ordered fields with all supplied customer/order lineage.

    Source-system labels and source fields are input data, not a customer
    whitelist. Pass another customer's analyses and mappings to reuse this
    function; no source-specific code changes are necessary. Analysis CSV
    filenames must be unique within one invocation and match mapping basenames.
    """
    schema_path = _resolve(schema_path)
    analysis_paths = sorted(_resolve(path) for path in analysis_paths)
    mapping_paths = sorted(_resolve(path) for path in mapping_paths)
    schema, analyses = _schema(schema_path), _analyses(analysis_paths)
    if not mapping_paths:
        _fail("INVALID_MAPPING", "Supply at least one mapping YAML.", "mappings")
    tables = {table["name"]: table for table in schema["tables"]}
    mappings, pairs, warnings = [], set(), []
    for path in mapping_paths:
        location = _display(path)
        try:
            mapping = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        except (OSError, ValueError, yaml.YAMLError) as error:
            _fail("INVALID_MAPPING", str(error), location)
        if not isinstance(mapping, dict) or set(mapping) != DOCUMENT_KEYS or mapping.get("mapping_version") != "1.0":
            _fail("INVALID_MAPPING", "Expected mapping version 1.0 with its documented keys.", location)
        if not _text(mapping.get("source_system")) or not _text(mapping.get("source_file")):
            _fail("INVALID_MAPPING", "Require source_system and source_file.", location)
        target = mapping.get("target_table")
        expected_table = {"customer": "unified_customers", "order": "unified_orders"}.get(mapping.get("table_type"))
        if target not in tables or target != expected_table:
            _fail("INVALID_MAPPING", "Unknown target table or conflicting table_type.", location)
        pair = (mapping["source_system"], target)
        if pair in pairs:
            _fail("INVALID_MAPPING", "Duplicate source-system/target-table mapping.", location)
        pairs.add(pair)
        filename = Path(mapping["source_file"]).name
        analysis = analyses.get(filename)
        if not analysis or analysis["entry"]["table_type"] != mapping["table_type"]:
            _fail("INVALID_ANALYSIS", "No matching filename/table-type analysis for mapping.", location)
        fields = {field["name"]: field for field in tables[target]["fields"]}
        rules = mapping.get("rules")
        if not isinstance(rules, list) or not rules:
            _fail("INVALID_MAPPING", "Require nonempty mapping rules.", location)
        by_target = {}
        for rule in rules:
            try:
                errors = _config_errors(rule, list(analysis["fields"]), fields)
            except (KeyError, TypeError, ValueError) as error:
                _fail("INVALID_MAPPING", f"Malformed rule: {error}", location)
            if errors:
                _fail("INVALID_MAPPING", "; ".join(errors), location)
            name = rule["target_field"]
            if name in by_target:
                _fail("INVALID_MAPPING", f"Duplicate target {name}.", location)
            if rule["transformation_type"] not in EXPRESSION_KEYS:
                _fail("INVALID_MAPPING", "Deferred operations must use explicit manual_review.", location)
            if name == "source_system" and not (rule["transformation_type"] == "default_value" and rule["expression"] == {"value": mapping["source_system"], "apply_when": "always"}):
                _fail("INVALID_MAPPING", "source_system constant disagrees with mapping source.", location)
            by_target[name] = rule
        unmapped = mapping.get("unmapped_target_fields")
        unused = mapping.get("unmapped_source_fields")
        if not _strings(unmapped) or set(unmapped) != set(fields) - set(by_target):
            _fail("INVALID_MAPPING", "Unmapped targets must exactly describe absent rules.", location)
        if any(not fields[name]["nullable"] for name in unmapped):
            _fail("INVALID_MAPPING", "Required schema fields cannot be unmapped.", location)
        used = {name for rule in rules for name in rule["source_fields"]}
        if not _strings(unused) or set(unused) & used or set(unused) | used != set(analysis["fields"]):
            _fail("INVALID_MAPPING", "Analysis fields must be mapped or explicitly unmapped.", location)
        if not isinstance(mapping["warnings"], list) or not all(_text(item) for item in mapping["warnings"]):
            _fail("INVALID_MAPPING", "Mapping warnings must be a list of strings.", location)
        for note in mapping["warnings"]:
            warnings.append(_warning("OPEN_ISSUE", note, location))
        for name in unused:
            warnings.append(_warning("OPEN_ISSUE", f"Unmapped source field: {name}.", location))
        mappings.append((path, mapping, by_target, analysis))

    result_tables = []
    for table in schema["tables"]:
        table_mappings = [item for item in mappings if item[1]["target_table"] == table["name"]]
        fields = []
        for field in table["fields"]:
            name, location = field["name"], f"{table['name']}.{field['name']}"
            lineages, examples, notes, comments, source_fields = [], [], [], [], []
            if field.get("rationale"):
                comments.append(field["rationale"])
            coverage = copy.deepcopy(field.get("source_coverage", {}))
            if coverage.get("coverage_note"):
                comments.append(coverage["coverage_note"])
            missing_sources = set(coverage.get("sources", [])) - {item[1]["source_system"] for item in table_mappings}
            if not table_mappings or missing_sources:
                message = "Missing mapping files for " + (", ".join(sorted(missing_sources)) or table["name"]) + "."
                comments.append(message)
                warnings.append(_warning("PARTIAL_LINEAGE", message, location))
            for path, mapping, by_target, analysis in table_mappings:
                source = mapping["source_system"]
                rule = by_target.get(name)
                lineage = {"source_system": source, "source_file": mapping["source_file"],
                           "mapping_file": _display(path), "analysis_file": analysis["analysis_file"],
                           "target_field": name, "source_fields": []}
                if rule is None:
                    message = f"{source}: explicitly unmapped nullable target; no transformation or example is supplied."
                    lineage.update({"mapping_status": "unmapped", "manual_review": False,
                                    "transformation_type": None, "expression": None,
                                    "notes": message, "field_analysis": [], "review_reason": None})
                    comments.append(message)
                    notes.append(message)
                    warnings.append(_warning("MISSING_OPTIONAL_MAPPING", message, location))
                else:
                    interpretations = [copy.deepcopy(analysis["fields"][key]) for key in rule["source_fields"]]
                    reasons = []
                    if rule["manual_review"] or rule["status"] != "accepted":
                        reasons.append(rule["review_reason"] or f"Mapping status is {rule['status']}.")
                    if rule["confidence"] < 0.70:
                        reasons.append("Mapping confidence is below 0.70.")
                    for item in interpretations:
                        if item["confidence"] < 0.70 or item["semantic_type"] == "unknown":
                            reasons.append(f"Source analysis is uncertain for {item['field_name']}.")
                    lineage.update({"source_fields": copy.deepcopy(rule["source_fields"]),
                                    "mapping_status": rule["status"], "manual_review": bool(reasons),
                                    "review_reason": "; ".join(reasons) or None,
                                    "transformation_type": rule["transformation_type"],
                                    "expression": json_ready(copy.deepcopy(rule["expression"])),
                                    "notes": rule["notes"], "confidence": rule["confidence"],
                                    "evidence": copy.deepcopy(rule["evidence"]), "field_analysis": interpretations,
                                    "example_input": json_ready(copy.deepcopy(rule["example_input"])),
                                    "example_output": json_ready(copy.deepcopy(rule["example_output"]))})
                    source_fields.extend(f"{source}: {key}" for key in rule["source_fields"])
                    notes.append(f"{source}: {rule['transformation_type']}. {rule['notes']}")
                    examples.append({"source_system": source, "input": lineage["example_input"],
                                     "output": lineage["example_output"], "origin": "mapping_example",
                                     "status": "proposed_not_validated" if reasons else "documented_not_validated"})
                    if reasons:
                        message = f"{source}: manual review — {lineage['review_reason']}"
                        comments.append(message)
                        warnings.append(_warning("OPEN_ISSUE", message, location))
                    if not rule["source_fields"]:
                        comments.append(f"{source}: source-free default, not a CSV column.")
                lineages.append(lineage)
            documented = set(source_fields)
            missing_fields = set(coverage.get("source_fields", [])) - documented
            if missing_fields:
                message = "Schema coverage not present in mapping lineage: " + ", ".join(sorted(missing_fields)) + "."
                comments.append(message)
                warnings.append(_warning("PARTIAL_LINEAGE", message, location))
            fields.append({"table_name": table["name"], "name": name, "type": field["type"],
                           "nullable": field["nullable"], "description": field["description"],
                           "source_coverage": coverage, "source_fields": list(dict.fromkeys(source_fields)),
                           "source_lineage": lineages, "transformation_notes": notes,
                           "example_values": examples, "comments": comments})
        result_tables.append({"name": table["name"], "grain": table.get("grain", ""),
                              "primary_key": table["primary_key"], "fields": fields})

    input_paths = [schema_path, *analysis_paths, *mapping_paths]
    return {"dictionary_version": "1.0", "contract_version": CONTRACT_VERSION,
            "schema_version": schema["schema_version"], "status": "review_draft",
            "tables": result_tables, "warnings": warnings,
            "summary": {"tables": len(result_tables), "fields": sum(len(t["fields"]) for t in result_tables),
                        "mapping_files": len(mappings), "source_systems": sorted({m[1]["source_system"] for m in mappings}),
                        "manual_review_lineages": sum(lineage["manual_review"] for t in result_tables for f in t["fields"] for lineage in f["source_lineage"]),
                        "unmapped_lineages": sum(lineage["mapping_status"] == "unmapped" for t in result_tables for f in t["fields"] for lineage in f["source_lineage"])},
            "provenance": [{"path": _display(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in input_paths],
            "limitations": ["This is documentation, not validation evidence or an executable ETL configuration.",
                            "Examples are copied from mapping drafts, not computed or independently verified. A null example for a review rule is not an approved null default.",
                            "Accepted mapping status does not imply that runtime validation passed; this generator does not read validation reports.",
                            "Shared missing-value policy 1.1: nullable blank/N/A/null/none markers become null with warnings; required missing values fail; status_raw preserves original text.",
                            "Generated keys, phone normalization, lookups, decimal-comma parsing and real exchange-rate policies remain subject to the supplied mapping review flags."]}


def _md(value: Any) -> str:
    """Escape source text so it cannot break Markdown tables or become HTML."""
    text = html.escape(str(value), quote=False).replace("\\", "\\\\")
    for character in "|`*_[]":
        text = text.replace(character, "\\" + character)
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def render_markdown(dictionary: dict) -> str:
    """Render the JSON dictionary without inferring or executing anything."""
    summary = dictionary["summary"]
    lines = ["# Data Dictionary", "", f"Schema version: {_md(dictionary['schema_version'])}. Status: review draft.", "",
             f"{summary['tables']} tables; {summary['fields']} target fields; {summary['mapping_files']} mapping files.", "",
             "Target definitions are copied from the unified schema. Source lineage and example values come from mapping drafts; source interpretations come from field analysis.", "",
             "Examples are documented, not executed or validated. Manual-review outputs are proposals, including null placeholders.", ""]
    for table in dictionary["tables"]:
        title = {"unified_customers": "Unified Customers", "unified_orders": "Unified Orders"}.get(table["name"], table["name"])
        lines += [f"## {_md(title)}", "", f"Grain: {_md(table['grain'])} Primary key: {_md(table['primary_key'])}.", "",
                  "| Table | Field | Data type | Nullable | Business meaning | Source fields | Transformation notes | Example values (not validated) | Comments |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for field in table["fields"]:
            examples = [f"{item['source_system']}: {_json(item['input'])} → {_json(item['output'])} ({item['status']})" for item in field["example_values"]]
            values = [field["table_name"], field["name"], field["type"], "yes" if field["nullable"] else "no", field["description"],
                      "\n".join(field["source_fields"]) or "No source columns documented (see lineage).",
                      "\n".join(field["transformation_notes"]), "\n".join(examples) or "No example supplied.", "\n".join(field["comments"])]
            lines.append("| " + " | ".join(_md(value) for value in values) + " |")
        lines.append("")
    lines += ["## Source Lineage", "", "Exact expressions below are copied from YAML. Field-analysis interpretations support review but do not override target definitions or approve transformations.", ""]
    for table in dictionary["tables"]:
        for field in table["fields"]:
            lines += [f"### {_md(table['name'])}.{_md(field['name'])}", "",
                      "| Source system / file | Source fields | Mapping status / review | Transformation and exact expression | Source interpretations |",
                      "|---|---|---|---|---|"]
            for lineage in field["source_lineage"]:
                interpretation = [f"{item['field_name']}: {item['semantic_type']} (confidence {item['confidence']}); {item['description']}; evidence: {_json(item['evidence'])}" for item in lineage["field_analysis"]]
                values = [f"{lineage['source_system']}: {lineage['source_file']}", ", ".join(lineage["source_fields"]) or "None",
                          f"{lineage['mapping_status']}; " + (f"MANUAL REVIEW: {lineage['review_reason']}" if lineage["manual_review"] else "Not independently validated"),
                          f"{lineage['transformation_type'] or 'unmapped'}: {_json(lineage['expression'])}",
                          "\n".join(interpretation) or "No source-field interpretation (default or unmapped)."]
                lines.append("| " + " | ".join(_md(value) for value in values) + " |")
            lines.append("")
    lines += ["## Known Limitations", ""]
    lines += [f"- {_md(note)}" for note in dictionary["limitations"]]
    lines += ["", "### Review comments and coverage warnings", ""]
    lines += [f"- {_md(w['code'])} — {_md(w['location'])}: {_md(w['message'])}" for w in dictionary["warnings"]] or ["No input-specific warnings."]
    lines += ["", "## Input Provenance", "", "Regenerate after changing any input. JSON output records the same input hashes.", ""]
    lines += [f"- {_md(item['path'])} — SHA-256: {_md(item['sha256'])}" for item in dictionary["provenance"]]
    return "\n".join(lines) + "\n"
