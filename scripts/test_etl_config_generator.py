"""Offline tests for ETL drafts, review gates and stale validation inputs."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.etl_config_generator import generate_etl_config  # noqa: E402
from src.mapping_validator import validate_sample_mapping  # noqa: E402
from scripts.test_support import make_stress_data  # noqa: E402


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.schema = PROJECT_ROOT / "schemas/unified-schema.json"
        stress_data = make_stress_data(self.folder / "generated")
        self.mappings, self.reports, self.extras = [], [], []
        for table, csv_table in (("customer", "customers"), ("order", "orders")):
            csv = self.folder / f"customer_a_{csv_table}.csv"
            csv.write_bytes((PROJECT_ROOT / f"data/examples/week1/{csv.name}").read_bytes())
            mapping = yaml.safe_load((PROJECT_ROOT / f"examples/mappings/customer_a-{table}-mapping.yaml").read_text())
            mapping["source_file"] = str(csv)
            path = self.folder / f"customer_a-{table}-mapping.yaml"
            path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
            report_path = self.folder / f"{path.stem}-validation.json"
            report_path.write_text(json.dumps(validate_sample_mapping(csv, path, self.schema)), encoding="utf-8")
            stress_path = self.folder / f"{path.stem}-stress.json"
            stress_csv = stress_data / f"customer_a_{csv_table}.csv"
            stress_path.write_text(json.dumps(validate_sample_mapping(stress_csv, path, self.schema, sample_size=100)), encoding="utf-8")
            self.mappings.append(path)
            self.reports.append(report_path)
            self.extras.append(stress_path)

    def generate(self, extras=None, source="Customer A"):
        return generate_etl_config(source, self.schema, self.mappings, self.reports,
                                   additional_validation_paths=extras)

    def test_one_customer_file_contains_two_jobs_and_loading_disabled(self):
        config = self.generate()
        self.assertEqual(config["target_tables"], ["unified_customers", "unified_orders"])
        self.assertEqual(len(config["input_files"]), 2)
        self.assertFalse(config["production_ready"])
        self.assertFalse(config["loading_behavior"]["enabled"])
        self.assertEqual(config["summary"]["fields_manual_review"], 4)
        for job in config["jobs"]:
            self.assertFalse(job["loading_behavior"]["enabled"])
            self.assertIn("primary_key", job["validation_rules"])
            self.assertFalse(job["reject_policy"]["drop_silently"])

    def test_manual_rules_never_become_executable(self):
        config = self.generate()
        for job in config["jobs"]:
            for rule in job["field_mappings"]:
                if rule["manual_review"]:
                    self.assertEqual(rule["transformation_type"], "manual_review")
                    self.assertTrue(rule["review_reason"])
                    self.assertFalse(rule["enabled_for_dry_run"])
        self.assertEqual(config["jobs"][1]["validation_rules"]["foreign_key"]["status"], "manual_review")

    def test_stress_failures_disable_the_affected_rule(self):
        config = self.generate(self.extras)
        order = config["jobs"][1]
        rule = next(rule for rule in order["field_mappings"] if rule["target_field"] == "source_customer_id")
        self.assertEqual(rule["status"], "manual_review")
        self.assertFalse(rule["enabled_for_dry_run"])
        self.assertEqual(rule["proposed_transformation"]["transformation_type"], "rename")
        self.assertIn("5 failed rows", rule["review_reason"])
        self.assertEqual(config["summary"]["fields_manual_review"], 5)

    def test_usd_identity_has_an_explicit_currency_guard(self):
        config = self.generate()
        step = next(step for step in config["jobs"][1]["transformation_steps"] if step["target_field"] == "amount_usd")
        self.assertTrue(step["enabled_for_dry_run"])
        self.assertEqual(step["execution_guard"]["required_source_currency"], "USD")
        self.assertEqual(step["execution_guard"]["on_non_identity"], "manual_review")
        self.assertFalse(step["execution_guard"]["external_rates_available"])

    def test_stale_mapping_and_missing_fingerprints_are_rejected(self):
        original = self.mappings[0].read_text()
        self.mappings[0].write_text(original + "\n# changed mapping\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stale"):
            self.generate()
        self.mappings[0].write_text(original, encoding="utf-8")
        report = json.loads(self.reports[0].read_text())
        del report["input_sha256"]
        self.reports[0].write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fingerprints"):
            self.generate()

    def test_changed_csv_or_schema_invalidates_report(self):
        data = yaml.safe_load(self.mappings[0].read_text())
        csv = Path(data["source_file"])
        csv.write_text(csv.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stale"):
            self.generate()
        schema = self.folder / "changed-schema.json"
        value = json.loads(self.schema.read_text())
        value["schema_version"] = "future_version"
        schema.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stale"):
            generate_etl_config("Customer A", schema, self.mappings, self.reports)

    def test_wrong_source_and_swapped_primary_reports_fail(self):
        with self.assertRaisesRegex(ValueError, "Mapping source"):
            self.generate(source="Customer B")
        with self.assertRaisesRegex(ValueError, "source or target"):
            generate_etl_config("Customer A", self.schema, self.mappings, self.reports[::-1])

    def test_primary_report_cannot_be_a_different_csv(self):
        with self.assertRaisesRegex(ValueError, "configured input CSV"):
            generate_etl_config("Customer A", self.schema, self.mappings, self.extras)

    def test_false_pass_claim_is_rejected(self):
        report = json.loads(self.reports[0].read_text())
        report["rules"][0]["rows_failed"] = 1
        self.reports[0].write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            self.generate()

    def test_low_confidence_is_reviewed_even_if_sample_values_pass(self):
        mapping = yaml.safe_load(self.mappings[0].read_text())
        mapping["rules"][0]["confidence"] = 0.50
        self.mappings[0].write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
        report = validate_sample_mapping(mapping["source_file"], self.mappings[0], self.schema)
        self.reports[0].write_text(json.dumps(report), encoding="utf-8")
        config = self.generate()
        rule = config["jobs"][0]["field_mappings"][0]
        self.assertTrue(rule["manual_review"])
        self.assertFalse(rule["enabled_for_dry_run"])
        self.assertIn("0.70 review threshold", rule["review_reason"])

    def test_test_rates_stay_manual_review_even_after_sample_pass(self):
        mapping = yaml.safe_load(self.mappings[1].read_text())
        rule = next(rule for rule in mapping["rules"] if rule["target_field"] == "amount_usd")
        rule["expression"]["rate_source"] = "test_fixed_rates"
        self.mappings[1].write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
        report = validate_sample_mapping(mapping["source_file"], self.mappings[1], self.schema)
        self.reports[1].write_text(json.dumps(report), encoding="utf-8")
        config = self.generate()
        result = next(rule for rule in config["jobs"][1]["field_mappings"] if rule["target_field"] == "amount_usd")
        self.assertTrue(result["manual_review"])
        self.assertIn("test fixtures", result["review_reason"])

    def test_cli_bad_inputs_preserve_previous_config(self):
        output = self.folder / "configs/customer_a-etl-config.json"
        output.parent.mkdir()
        output.write_text('{"keep": true}\n', encoding="utf-8")
        mapping = yaml.safe_load(self.mappings[0].read_text())
        mapping["source_system"] = "Wrong Customer"
        self.mappings[0].write_text(yaml.safe_dump(mapping), encoding="utf-8")
        result = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/etl_config_generator.py"),
            "--source-system", "Customer A", "--mapping-dir", str(self.folder),
            "--validation-dir", str(self.folder), "--output-dir", str(output.parent)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(output.read_text()), {"keep": True})
        diagnostics = json.loads(Path(str(output) + ".diagnostics.json").read_text())
        self.assertEqual(diagnostics["status"], "error")


if __name__ == "__main__":
    unittest.main()
