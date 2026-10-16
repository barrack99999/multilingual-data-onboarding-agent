"""Ordered, auditable onboarding controller; produces drafts, never loads data."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from scripts.validate_mapping import save_json
from src.csv_profiler import profile_csv
from src.data_dictionary_generator import generate_data_dictionary, render_markdown, _schema
from src.etl_config_generator import generate_etl_config, source_slug
from src.field_analyzer import FieldAnalysisResult, analyze_fields
from src.mapping_generator import MappingDocument, generate_mapping, validate_mapping, write_mapping_yaml
from src.mapping_validator import UniqueKeyLoader, validate_sample_mapping
from src.schema_recommender import recommend_schema, validate_recommendation

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STEP_NAMES = ("discover_inputs", "csv_profiling", "field_analysis", "schema_recommendation",
              "mapping_generation", "mapping_validation", "etl_config_generation",
              "data_dictionary_generation", "export_outputs")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(path: str | Path) -> Path:
    path = Path(path).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def _safe_message(error: BaseException) -> str:
    """Record useful errors, not credentials or an unbounded provider response."""
    text = str(error) or type(error).__name__
    secret = os.getenv("OPENAI_API_KEY")
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", text)[:3000]


def _warning(code: str, message: str, location: str) -> dict:
    return {"code": code, "message": message, "location": location,
            "suggested_action": "Review the referenced artifact; drafts do not approve production loading."}


class OnboardingAgent:
    """Reuse modules through Python calls, with injectable LLM adapters for tests.

    Passing analysis_paths/mapping_dir explicitly selects artifact reuse, not
    a fresh LLM result. A supplied schema is checked and copied, never rewritten.
    An output directory must be empty to avoid mixing runs or overwriting work.
    """

    def __init__(self, source_system: str, input_dir: str | Path, output_dir: str | Path, *,
                 schema_path: str | Path | None = None,
                 customer_csv: str | Path | None = None, order_csv: str | Path | None = None,
                 analysis_paths: list[str | Path] | None = None,
                 mapping_dir: str | Path | None = None, sample_size: int = 100,
                 model: str | None = None, prompt_path: str | Path | None = None,
                 analyzer: Callable | None = None, mapper: Callable | None = None):
        self.source = source_system
        self.input_dir, self.output = _resolve(input_dir), _resolve(output_dir)
        self.schema_input = _resolve(schema_path) if schema_path is not None else None
        self.explicit_csv = {"customer": customer_csv, "order": order_csv}
        self.analysis_inputs = [_resolve(path) for path in analysis_paths] if analysis_paths is not None else None
        self.mapping_dir = _resolve(mapping_dir) if mapping_dir is not None else None
        self.sample_size, self.model = sample_size, model
        self.prompt = _resolve(prompt_path or "docs/week3-task2-mapping-generator-prompt.md")
        self.analyzer, self.mapper = analyzer or analyze_fields, mapper or generate_mapping
        self.csvs, self.profiles, self.analyses, self.mappings, self.reports = {}, {}, {}, [], []
        self.schema_file = self.output / "unified-schema.json"
        self.analysis_file = self.output / "field-analysis.json"
        self.log_path = self.output / "run_log.json"
        self.log = {"run_version": "1.0", "contract_version": "1.6", "run_id": uuid.uuid4().hex,
                    "source_system": source_system, "status": "pending", "started_at": None,
                    "finished_at": None, "production_ready": False,
                    "inputs": {"input_dir": str(self.input_dir), "schema": str(self.schema_input) if self.schema_input else None,
                               "analysis_files": [str(p) for p in self.analysis_inputs] if self.analysis_inputs is not None else [],
                               "mapping_dir": str(self.mapping_dir) if self.mapping_dir else None,
                               "model": model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), "sample_size": sample_size},
                    "steps": [{"name": name, "status": "pending", "mode": "local", "outputs": [],
                               "errors": [], "warnings": []} for name in STEP_NAMES],
                    "errors": [], "warnings": [], "final_outputs": {}}

    def _save_log(self):
        save_json(self.log_path, self.log)

    def _output(self, step: dict, path: Path):
        step["outputs"].append(str(path))
        self._save_log()

    def _warn(self, step: dict, code: str, message: str, location: str):
        warning = _warning(code, message, location)
        step["warnings"].append(warning)
        self.log["warnings"].append({"step": step["name"], **warning})

    def _discover_inputs(self, step):
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source_system must be a nonempty name.")
        self.slug = source_slug(self.source)
        if type(self.sample_size) is not int or self.sample_size < 1:
            raise ValueError("sample_size must be positive.")
        if not self.input_dir.is_dir():
            raise ValueError(f"Input directory does not exist: {self.input_dir}")
        if any(self.explicit_csv.values()) and not all(self.explicit_csv.values()):
            raise ValueError("Supply both customer_csv and order_csv, or neither.")
        if all(self.explicit_csv.values()):
            self.csvs = {kind: _resolve(path) for kind, path in self.explicit_csv.items()}
        else:
            # Exact names select only this customer when a folder contains A/B/C.
            self.csvs = {kind: self.input_dir / f"{self.slug}_{suffix}.csv"
                         for kind, suffix in (("customer", "customers"), ("order", "orders"))}
        if self.csvs["customer"] == self.csvs["order"]:
            raise ValueError("Customer and order CSVs must be different files.")
        metadata = []
        for kind, path in self.csvs.items():
            if not path.is_file() or path.suffix.lower() != ".csv":
                raise ValueError(f"Missing {kind} CSV: {path}. Use --customer-csv and --order-csv for other filenames.")
            with path.open(encoding="utf-8-sig", newline="") as handle:
                header = next(csv.reader(handle), [])
            if not header or any(not name.strip() for name in header) or len(header) != len(set(header)):
                raise ValueError(f"CSV header must contain nonempty unique column names: {path}")
            metadata.append({"table_type": kind, "path": str(path), "sha256": _digest(path)})
        if self.csvs["customer"].name == self.csvs["order"].name:
            raise ValueError("CSV basenames must be distinct for analysis joins.")
        self.log["inputs"]["csv_files"] = metadata

    def _csv_profiling(self, step):
        for kind, path in self.csvs.items():
            profile = profile_csv(path)
            if profile["row_count"] < 1:
                raise ValueError(f"CSV has no data rows: {path}")
            self.profiles[kind] = profile
            output = self.output / "profiles" / f"{path.stem}_profile.json"
            save_json(output, profile)
            self._output(step, output)

    def _field_analysis(self, step):
        cached = {}
        if self.analysis_inputs is not None:
            step["mode"] = "reused"
            for path in self.analysis_inputs:
                document = json.loads(path.read_text(encoding="utf-8"))
                entries = {document["file_name"]: document} if "file_name" in document else document
                for name, entry in entries.items():
                    if name in cached:
                        raise ValueError(f"Duplicate analysis filename: {name}")
                    cached[name] = entry
            self._warn(step, "REUSED_ANALYSIS", "Using supplied analysis. Names/order are checked, but semantic freshness for changed CSV values is not proven.", str(self.analysis_file))
        else:
            step["mode"] = "live_llm"
        for kind, path in self.csvs.items():
            if self.analysis_inputs is not None:
                if path.name not in cached:
                    raise ValueError(f"No supplied analysis for {path.name}")
                result = cached[path.name]
            else:
                result = self.analyzer(path, self.profiles[kind], model=self.model)
            result = FieldAnalysisResult.model_validate(result).model_dump()
            if result["file_name"] != path.name or result["table_type"] != kind:
                raise ValueError(f"Analysis filename/table_type disagrees with input: {path.name}")
            if [f["field_name"] for f in result["fields"]] != [f["field_name"] for f in self.profiles[kind]["fields"]]:
                raise ValueError(f"Analysis fields/order disagree with CSV profile: {path.name}")
            self.analyses[path.name] = result
            output = self.output / "analyses" / f"{path.stem}-analysis.json"
            save_json(output, result)
            self._output(step, output)
            for field in result["fields"]:
                if field["confidence"] < 0.70 or field["semantic_type"] == "unknown":
                    self._warn(step, "LOW_CONFIDENCE_FIELD", f"Uncertain analysis: {field['field_name']}", str(output))
        save_json(self.analysis_file, self.analyses)
        self._output(step, self.analysis_file)

    def _schema_recommendation(self, step):
        if self.schema_input is not None:
            step["mode"] = "reused"
            schema = _schema(self.schema_input)
            # Copy exact reviewed bytes. Never rewrite or regenerate this schema.
            self.schema_file.write_bytes(self.schema_input.read_bytes())
            self._warn(step, "REUSED_SCHEMA", "Using the reviewed schema unchanged, not a single-customer redesign.", str(self.schema_input))
        else:
            schema = recommend_schema(self.analyses, source_system=self.source)
            save_json(self.schema_file, schema)
        self._output(step, self.schema_file)
        checks = validate_recommendation(schema, expected_sources={self.source} if self.schema_input is None else None)
        failed = [check for check in checks if not check["passed"]]
        critical = [check for check in failed if check["check"] != "core_source_coverage_complete"]
        path = self.output / "schema-checks.json"
        save_json(path, {"mode": step["mode"], "checks": checks, "coverage_is_warning": True})
        self._output(step, path)
        if critical:
            raise ValueError(f"Schema policy checks failed: {[check['check'] for check in critical]}")
        for check in failed:
            self._warn(step, "PARTIAL_SOURCE_COVERAGE", check["detail"], str(path))

    def _mapping_generation(self, step):
        schema = json.loads(self.schema_file.read_text(encoding="utf-8"))
        cached = {}
        if self.mapping_dir is not None:
            step["mode"] = "reused"
            for path in sorted(self.mapping_dir.glob("*-mapping.yaml")):
                document = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
                if document.get("source_system") != self.source:
                    continue
                kind = document.get("table_type")
                if kind in cached:
                    raise ValueError(f"Duplicate supplied {kind} mapping for {self.source}")
                cached[kind] = document
            self._warn(step, "REUSED_MAPPING", "Using supplied mappings; runtime validation is rerun on the selected CSVs.", str(self.mapping_dir))
        else:
            step["mode"] = "live_llm"
        for kind, csv_path in self.csvs.items():
            analysis = self.analyses[csv_path.name]
            if self.mapping_dir is not None:
                if kind not in cached:
                    raise ValueError(f"No supplied {kind} mapping for {self.source}")
                mapping = cached[kind]
                if _resolve(mapping["source_file"]) != csv_path:
                    raise ValueError(f"Supplied mapping points at a different CSV: {mapping['source_file']}. Reuse cannot silently rebind source data.")
                source_file = mapping["source_file"]
            else:
                source_file = str(csv_path)
                mapping = self.mapper(analysis, schema, self.source, source_file, [],
                                      prompt_path=self.prompt, model=self.model)
            mapping = MappingDocument.model_validate(mapping).model_dump()
            errors = validate_mapping(mapping, analysis, schema, self.source, source_file)
            if errors:
                raise ValueError("Invalid mapping: " + "; ".join(errors))
            path = self.output / "mappings" / f"{self.slug}-{kind}-mapping.yaml"
            write_mapping_yaml(mapping, path)
            self.mappings.append(path)
            self._output(step, path)
            for rule in mapping["rules"]:
                if rule["manual_review"] or rule["status"] != "accepted":
                    self._warn(step, "MANUAL_REVIEW", f"{rule['target_field']}: {rule['review_reason'] or rule['status']}", str(path))

    def _mapping_validation(self, step):
        for (kind, csv_path), mapping_path in zip(self.csvs.items(), self.mappings):
            report = validate_sample_mapping(csv_path, mapping_path, self.schema_file, sample_size=self.sample_size)
            path = self.output / "validation" / f"{mapping_path.stem}-validation.json"
            save_json(path, report)
            self.reports.append(path)
            self._output(step, path)
            self.log["errors"].extend({"step": step["name"], "fatal": False, **error} for error in report["errors"])
            step["errors"].extend(report["errors"])
            for warning in report["warnings"]:
                self._warn(step, warning["code"], warning["message"], str(path))
            counts = report["summary"]
            if counts["rules_failed"] or counts["rules_manual_review"]:
                self._warn(step, "VALIDATION_FINDINGS", f"{kind}: {counts['rules_passed']} passed, {counts['rules_failed']} failed, {counts['rules_manual_review']} review rules. Drafting continues with review gates.", str(path))

    def _etl_config_generation(self, step):
        config = generate_etl_config(self.source, self.schema_file, self.mappings, self.reports)
        path = self.output / "etl-configs" / f"{self.slug}-etl-config.json"
        save_json(path, config)
        self._output(step, path)
        self.log["final_outputs"]["etl_config"] = str(path)
        self._warn(step, "DRAFT_ONLY", "Loading is disabled; manual-review steps are not executable.", str(path))

    def _data_dictionary_generation(self, step):
        dictionary = generate_data_dictionary(self.schema_file, [self.analysis_file], self.mappings)
        markdown = render_markdown(dictionary)
        json_path, md_path = self.output / "data-dictionary.json", self.output / "data-dictionary.md"
        save_json(json_path, dictionary)
        self._output(step, json_path)
        md_path.write_text(markdown, encoding="utf-8")
        self._output(step, md_path)
        self.log["final_outputs"].update(data_dictionary=str(md_path), data_dictionary_json=str(json_path))
        for warning in dictionary["warnings"]:
            self._warn(step, warning["code"], warning["message"], warning["location"])

    def _export_outputs(self, step):
        artifacts = sorted({path for item in self.log["steps"] for path in item["outputs"]})
        manifest = {"manifest_version": "1.0", "run_id": self.log["run_id"], "source_system": self.source,
                    "production_ready": False, "input_files": self.log["inputs"]["csv_files"],
                    "artifacts": [{"path": path, "sha256": _digest(Path(path))} for path in artifacts]}
        path = self.output / "output-manifest.json"
        save_json(path, manifest)
        self._output(step, path)
        self.log["final_outputs"].update(manifest=str(path), run_log=str(self.log_path), schema=str(self.schema_file))

    def run(self) -> dict:
        """Run all stages; return a persisted failure log instead of hiding errors."""
        if self.output.exists() and any(self.output.iterdir()):
            raise FileExistsError(f"Output directory is not empty: {self.output}. Choose a new --output-dir; previous work was preserved.")
        self.output.mkdir(parents=True, exist_ok=True)
        self.log.update(status="running", started_at=_now())
        # Exclusive creation also prevents two concurrent runs sharing a folder.
        with self.log_path.open("x", encoding="utf-8") as handle:
            json.dump(self.log, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
        for step in self.log["steps"]:
            step.update(status="running", started_at=_now())
            self._save_log()
            started = time.monotonic()
            try:
                for source in self.log["inputs"].get("csv_files", []):
                    if _digest(Path(source["path"])) != source["sha256"]:
                        raise ValueError(f"Input CSV changed during this run: {source['path']}. Start a new run after the input is stable.")
                getattr(self, "_" + step["name"])(step)
            except (Exception, KeyboardInterrupt) as error:
                item = {"code": "STEP_FAILED", "message": _safe_message(error), "location": step["name"], "retryable": False}
                step.update(status="failed", finished_at=_now())
                step["errors"].append(item)
                self.log["errors"].append({"step": step["name"], "fatal": True, **item})
                self.log.update(status="failed", failed_step=step["name"], finished_at=_now())
                for pending in self.log["steps"]:
                    if pending["status"] == "pending":
                        pending.update(status="skipped", reason=f"Blocked by {step['name']} failure.")
                step["duration_seconds"] = round(time.monotonic() - started, 3)
                self._save_log()
                return self.log
            step.update(status="warning" if step["warnings"] or step["errors"] else "success",
                        finished_at=_now(), duration_seconds=round(time.monotonic() - started, 3))
            self._save_log()
        self.log.update(status="completed_with_warnings" if self.log["warnings"] else "completed", finished_at=_now())
        self._save_log()
        return self.log
