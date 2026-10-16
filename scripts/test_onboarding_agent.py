"""Offline controller tests: real local modules, simulated LLM adapters."""

from __future__ import annotations

import copy
import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.csv_profiler import profile_csv  # noqa: E402
from src.onboarding_agent import OnboardingAgent, STEP_NAMES  # noqa: E402
from src.schema_recommender import recommend_schema  # noqa: E402
from scripts.validate_mapping import save_json  # noqa: E402


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.inputs = self.folder / "input"
        self.inputs.mkdir()
        self.customer = self.inputs / "clients_export.csv"
        self.order = self.inputs / "transactions_export.csv"
        self.customer.write_text("client_ref,name_text,email_text,phone_text,registered_on,tier_code\n"
            "C1,Example Person,person@example.com,+1 555 0100,2026-10-01,gold\n", encoding="utf-8")
        self.order.write_text("sale_ref,client_ref,placed_on,amount_text,currency_text,state_text\n"
            "S1,C1,2026-10-02,10.00,USD,paid\n", encoding="utf-8")
        self.output = self.folder / "run"
        self.calls = []
        self.analyses = {path.name: self.analysis(path, profile_csv(path)) for path in (self.customer, self.order)}
        self.calls.clear()
        self.schema = self.folder / "schema.json"
        self.schema.write_text(json.dumps(recommend_schema(self.analyses, source_system="Maple Store")), encoding="utf-8")

    def analysis(self, path, profile, **kwargs):
        self.calls.append(("analysis", Path(path).name))
        meanings = {"client_ref": "customer_id", "name_text": "full_name", "email_text": "email",
                    "phone_text": "phone", "registered_on": "signup_date", "tier_code": "loyalty_tier",
                    "sale_ref": "order_id", "placed_on": "order_date", "amount_text": "amount",
                    "currency_text": "currency", "state_text": "order_status"}
        return {"file_name": Path(path).name, "table_type": "customer" if Path(path) == self.customer else "order",
                "table_confidence": 0.95, "fields": [{"field_name": field["field_name"],
                "semantic_type": meanings[field["field_name"]], "description": "Documented test meaning.", "confidence": 0.95,
                "evidence": [{"source": "field_name", "detail": "Documented source name."},
                             {"source": "sample_values", "detail": json.dumps(field["sample_values"])}]}
                for field in profile["fields"]]}

    def mapping(self, analysis, schema, source, source_file, issues, **kwargs):
        self.calls.append(("mapping", analysis["file_name"]))
        kind = analysis["table_type"]
        fields = {field["semantic_type"]: field["field_name"] for field in analysis["fields"]}
        with Path(source_file).open(encoding="utf-8") as handle:
            row = next(csv.DictReader(handle))
        rules, unmapped = [], []
        def add(target, sources, transform, expression, output, *, review=False):
            rules.append({"target_field": target, "source_fields": sources, "transformation_type": transform,
                "expression": expression, "example_input": {name: row[name] for name in sources}, "example_output": output,
                "notes": "Explicit test rule.", "confidence": 0.95, "evidence": ["Documented source examples."],
                "status": "needs_review" if review else "accepted", "manual_review": review,
                "review_reason": "Deferred operation requires review." if review else None})
        target = "unified_customers" if kind == "customer" else "unified_orders"
        for field in next(table for table in schema["tables"] if table["name"] == target)["fields"]:
            name = field["name"]
            if name == "source_system":
                add(name, [], "default_value", {"value": source, "apply_when": "always"}, source)
            elif name.startswith("unified_") or name == "phone":
                key = fields["order_id"] if name == "unified_order_id" else fields["phone"] if name == "phone" else fields["customer_id"]
                add(name, [key], "manual_review", {"requested_operation": "normalize_phone" if name == "phone" else "other",
                                                    "proposed_logic": "Implement after review."}, None, review=True)
            elif name == "amount_usd":
                keys = [fields[semantic] for semantic in ("amount", "currency", "order_date")]
                add(name, keys, "currency_conversion", {"amount_field": keys[0], "currency_field": keys[1],
                    "conversion_date_field": keys[2], "target_currency": "USD", "rate_source": "same_currency_identity",
                    "rounding_decimals": 2, "on_missing_rate": "manual_review"}, "10.00")
            else:
                semantic = {"source_customer_id": "customer_id", "source_order_id": "order_id",
                            "amount_original": "amount", "currency_code": "currency", "status_raw": "order_status"}.get(name, name)
                if semantic not in fields:
                    unmapped.append(name)
                    continue
                key = fields[semantic]
                if name in {"signup_date", "order_date"}:
                    add(name, [key], "parse_date", {"input_formats": ["%Y-%m-%d"], "output_format": "%Y-%m-%d", "on_error": "null"}, row[key])
                elif name == "order_status":
                    add(name, [key], "map_value", {"value_map": {"paid": "paid"}, "case_sensitive": False,
                        "trim_before_match": True, "unmapped_action": "manual_review"}, "paid")
                else:
                    add(name, [key], "direct" if name == key else "rename", {"operation": "copy"}, row[key])
        return {"mapping_version": "1.0", "source_system": source, "source_file": source_file,
                "table_type": kind, "target_table": target, "rules": rules,
                "unmapped_source_fields": [], "unmapped_target_fields": unmapped, "warnings": []}

    def agent(self, **kwargs):
        defaults = dict(schema_path=self.schema, customer_csv=self.customer, order_csv=self.order,
                        analyzer=self.analysis, mapper=self.mapping)
        defaults.update(kwargs)
        return OnboardingAgent("Maple Store", self.inputs, self.output, **defaults)

    def caches(self):
        bundle = self.folder / "analysis.json"
        bundle.write_text(json.dumps(self.analyses), encoding="utf-8")
        directory = self.folder / "mappings"
        directory.mkdir()
        schema = json.loads(self.schema.read_text())
        for path in (self.customer, self.order):
            analysis = self.analyses[path.name]
            mapping = self.mapping(analysis, schema, "Maple Store", str(path), [])
            (directory / f"{analysis['table_type']}-mapping.yaml").write_text(yaml.safe_dump(mapping), encoding="utf-8")
        self.calls.clear()
        return bundle, directory

    def test_all_modules_in_order_with_simulated_llm_and_real_local_modules(self):
        log = self.agent().run()
        self.assertEqual(log["status"], "completed_with_warnings", log["errors"])
        self.assertEqual([step["name"] for step in log["steps"]], list(STEP_NAMES))
        self.assertEqual([kind for kind, _ in self.calls], ["analysis", "analysis", "mapping", "mapping"])
        self.assertTrue(all(step["status"] in {"success", "warning"} for step in log["steps"]))
        self.assertEqual(log["steps"][2]["mode"], "live_llm")
        config = json.loads(Path(log["final_outputs"]["etl_config"]).read_text())
        self.assertFalse(config["loading_behavior"]["enabled"])
        self.assertFalse(config["production_ready"])
        self.assertEqual(config["source_system"], "Maple Store")

    def test_reviewed_schema_is_copied_exactly_and_input_is_unchanged(self):
        before = self.schema.read_bytes()
        log = self.agent().run()
        self.assertEqual(log["steps"][3]["mode"], "reused")
        self.assertEqual((self.output / "unified-schema.json").read_bytes(), before)
        self.assertEqual(self.schema.read_bytes(), before)

    def test_explicit_schema_generation_uses_arbitrary_source_name(self):
        log = self.agent(schema_path=None).run()
        self.assertNotEqual(log["status"], "failed", log["errors"])
        schema = json.loads((self.output / "unified-schema.json").read_text())
        for table in schema["tables"]:
            for field in table["fields"]:
                self.assertNotIn("Customer A", field["source_coverage"]["sources"])
        self.assertEqual(log["steps"][3]["mode"], "local")

    def test_second_analysis_failure_keeps_profiles_and_first_analysis(self):
        def failing(path, profile, **kwargs):
            if Path(path) == self.order:
                raise RuntimeError("Simulated provider outage")
            return self.analysis(path, profile)
        log = self.agent(analyzer=failing).run()
        self.assertEqual(log["failed_step"], "field_analysis")
        self.assertTrue((self.output / "analyses/clients_export-analysis.json").exists())
        self.assertEqual(len(list((self.output / "profiles").glob("*.json"))), 2)
        self.assertEqual(log["steps"][3]["status"], "skipped")
        self.assertIn("outage", log["errors"][-1]["message"])

    def test_second_mapping_failure_keeps_first_yaml_and_schema(self):
        def failing(*args, **kwargs):
            if args[0]["table_type"] == "order":
                raise ValueError("Simulated invalid mapping")
            return self.mapping(*args, **kwargs)
        log = self.agent(mapper=failing).run()
        self.assertEqual(log["failed_step"], "mapping_generation")
        self.assertTrue((self.output / "mappings/maple_store-customer-mapping.yaml").exists())
        self.assertTrue((self.output / "unified-schema.json").exists())

    def test_wrong_analysis_field_order_is_a_logged_failure(self):
        def wrong(path, profile, **kwargs):
            result = self.analysis(path, profile)
            result["fields"].reverse()
            return result
        log = self.agent(analyzer=wrong).run()
        self.assertEqual(log["failed_step"], "field_analysis")
        self.assertIn("order", log["errors"][-1]["message"])

    def test_missing_input_is_logged_and_stops_before_api_work(self):
        self.order.unlink()
        log = self.agent().run()
        self.assertEqual(log["failed_step"], "discover_inputs")
        self.assertEqual(self.calls, [])
        self.assertTrue((self.output / "run_log.json").exists())

    def test_invalid_schema_keeps_completed_analysis(self):
        self.schema.write_text("{}", encoding="utf-8")
        log = self.agent().run()
        self.assertEqual(log["failed_step"], "schema_recommendation")
        self.assertTrue((self.output / "field-analysis.json").exists())

    def test_existing_output_directory_is_not_overwritten(self):
        self.output.mkdir()
        marker = self.output / "previous.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.agent().run()
        self.assertEqual(marker.read_text(), "keep")

    def test_reuse_is_explicit_and_performs_no_llm_calls(self):
        bundle, mappings = self.caches()
        def forbidden(*args, **kwargs):
            raise AssertionError("LLM must not run")
        log = self.agent(analysis_paths=[bundle], mapping_dir=mappings, analyzer=forbidden, mapper=forbidden).run()
        self.assertNotEqual(log["status"], "failed", log["errors"])
        self.assertEqual(log["steps"][2]["mode"], "reused")
        self.assertEqual(log["steps"][4]["mode"], "reused")

    def test_reused_mapping_cannot_silently_point_to_another_csv(self):
        bundle, mappings = self.caches()
        path = mappings / "customer-mapping.yaml"
        mapping = yaml.safe_load(path.read_text())
        mapping["source_file"] = str(self.folder / "different.csv")
        path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
        log = self.agent(analysis_paths=[bundle], mapping_dir=mappings).run()
        self.assertEqual(log["failed_step"], "mapping_generation")
        self.assertIn("different CSV", log["errors"][-1]["message"])

    def test_manifest_records_real_artifact_hashes(self):
        log = self.agent().run()
        manifest = json.loads(Path(log["final_outputs"]["manifest"]).read_text())
        for item in manifest["artifacts"]:
            self.assertEqual(item["sha256"], hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest())
        self.assertFalse(manifest["production_ready"])

    def test_runtime_failures_continue_as_disabled_review_drafts(self):
        with self.order.open("a", encoding="utf-8") as handle:
            handle.write("S2,,2026-10-03,10.00,USD,paid\n")
        log = self.agent().run()
        self.assertNotEqual(log["status"], "failed", log["errors"])
        self.assertTrue(any(not error["fatal"] for error in log["errors"]))
        config = json.loads(Path(log["final_outputs"]["etl_config"]).read_text())
        order = next(job for job in config["jobs"] if job["table_type"] == "order")
        rule = next(rule for rule in order["field_mappings"] if rule["target_field"] == "source_customer_id")
        self.assertTrue(rule["manual_review"])
        self.assertFalse(rule["enabled_for_dry_run"])

    def test_changing_csv_during_a_run_is_a_logged_failure(self):
        def changing(path, profile, **kwargs):
            result = self.analysis(path, profile)
            if Path(path) == self.order:
                with self.order.open("a", encoding="utf-8") as handle:
                    handle.write("S2,C1,2026-10-03,10.00,USD,paid\n")
            return result
        log = self.agent(analyzer=changing).run()
        self.assertEqual(log["failed_step"], "schema_recommendation")
        self.assertIn("changed during", log["errors"][-1]["message"])
        self.assertTrue((self.output / "field-analysis.json").exists())

    def test_default_discovery_selects_exact_source_filenames(self):
        self.customer = self.customer.rename(self.inputs / "maple_store_customers.csv")
        self.order = self.order.rename(self.inputs / "maple_store_orders.csv")
        (self.inputs / "other_store_customers.csv").write_text("other\nvalue\n", encoding="utf-8")
        log = self.agent(customer_csv=None, order_csv=None).run()
        self.assertNotEqual(log["status"], "failed", log["errors"])
        self.assertEqual(len(log["inputs"]["csv_files"]), 2)
        self.assertTrue(all("maple_store" in item["path"] for item in log["inputs"]["csv_files"]))

    def test_failure_log_redacts_key_like_strings(self):
        fake_key = "sk-" + "test_private_secret_" + "123"
        def failing(*args, **kwargs):
            raise RuntimeError("invalid credential " + fake_key)
        log = self.agent(analyzer=failing).run()
        text = (self.output / "run_log.json").read_text()
        self.assertNotIn(fake_key, text)
        self.assertIn("[REDACTED]", text)

    def test_cli_reuse_run_and_reject_overwrite(self):
        bundle, mappings = self.caches()
        command = [sys.executable, str(PROJECT_ROOT / "onboarding_agent.py"), "--source-system", "Maple Store",
            "--input-dir", str(self.inputs), "--output-dir", str(self.output), "--schema", str(self.schema),
            "--customer-csv", str(self.customer), "--order-csv", str(self.order),
            "--analysis", str(bundle), "--mapping-dir", str(mappings)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        before = (self.output / "run_log.json").read_bytes()
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 1)
        self.assertEqual((self.output / "run_log.json").read_bytes(), before)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--results", type=Path, help="Optional machine-readable test results")
    options, remaining = parser.parse_known_args()
    result = unittest.main(argv=[sys.argv[0], *remaining], verbosity=2, exit=False).result
    if options.results:
        save_json(options.results, {"suite": "OnboardingAgent", "api_calls_made": False,
            "llm_adapters": "simulated", "tests_run": result.testsRun,
            "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
            "passed": result.wasSuccessful(), "implementation_sha256": {
                name: hashlib.sha256((PROJECT_ROOT / name).read_bytes()).hexdigest()
                for name in ("src/onboarding_agent.py", "onboarding_agent.py", "src/schema_recommender.py",
                             "scripts/test_onboarding_agent.py")}})
    raise SystemExit(0 if result.wasSuccessful() else 1)
