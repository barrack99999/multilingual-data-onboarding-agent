"""Offline checks for transformations and sample-validation failure paths."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.mapping_validator import validate_sample_mapping  # noqa: E402
from scripts.test_support import make_stress_data  # noqa: E402
from src.transform_helpers import (  # noqa: E402
    TEST_FIXED_RATES, ManualReviewRequired, TransformationError, convert_currency,
    default_value, map_status, normalize_missing, parse_date, split_name,
)


class HelperTests(unittest.TestCase):
    def test_dates_and_ambiguous_formats(self):
        self.assertEqual(parse_date("22/01/2024", ["%d/%m/%Y"]), "2024-01-22")
        self.assertEqual(parse_date("15.01.2024", ["%d.%m.%Y"]), "2024-01-15")
        self.assertIsNone(parse_date("N/A", ["%Y-%m-%d"]))
        with self.assertRaises(TransformationError):
            parse_date("2024-02-30", ["%Y-%m-%d"])
        with self.assertRaises(ManualReviewRequired):
            parse_date("03/04/2024", ["%m/%d/%Y", "%d/%m/%Y"])

    def test_name_splitting_limits(self):
        self.assertEqual(split_name("Emma   Johnson", part_index=1), "Johnson")
        for value in ("Maria del Carmen", "Sukarno", "Emma "):
            with self.subTest(name=value), self.assertRaises(ManualReviewRequired):
                split_name(value)

    def test_status_map_and_conflicts(self):
        self.assertEqual(map_status(" DIBAYAR ", {"dibayar": "paid"}), "paid")
        self.assertEqual(map_status("BEZ", {"BEZ": "paid"}, True), "paid")
        with self.assertRaises(TransformationError):
            map_status("new_status", {"paid": "paid"})
        with self.assertRaises(TransformationError):
            map_status("paid", {"paid": "paid", "PAID": "pending"})

    def test_fixed_rates_and_precision(self):
        self.assertEqual(convert_currency("1500000", "IDR", rates=TEST_FIXED_RATES), Decimal("97.50"))
        self.assertEqual(convert_currency("129.99", "EUR", rates=TEST_FIXED_RATES), Decimal("142.99"))
        self.assertEqual(convert_currency("0", "USD"), Decimal("0.00"))
        with self.assertRaises(ManualReviewRequired):
            convert_currency("129,99", "EUR", rates=TEST_FIXED_RATES)
        with self.assertRaises(ManualReviewRequired):
            convert_currency("100", "GBP", rates=TEST_FIXED_RATES)
        for value in ("NaN", "Infinity", True):
            with self.subTest(value=value), self.assertRaises(TransformationError):
                convert_currency(value, "USD")

    def test_default_conditions(self):
        self.assertEqual(default_value("Customer A", "always"), "Customer A")
        self.assertEqual(default_value("unknown", "source_null", "N/A"), "unknown")
        self.assertEqual(default_value("unknown", "source_missing", "paid"), "paid")
        with self.assertRaises(TransformationError):
            default_value({"bad": "object"}, "always")
        with self.assertRaises(TransformationError):
            default_value("x", "if_needed")
        with self.assertRaises(ManualReviewRequired):
            default_value("x", "source_null")

    def test_missing_markers_nullable_and_required(self):
        for marker in ("", " N/A ", "NULL", "none", None):
            with self.subTest(marker=marker):
                self.assertIsNone(normalize_missing(marker, True, "email"))
                with self.assertRaises(TransformationError):
                    normalize_missing(marker, False, "source_customer_id")
        self.assertEqual(normalize_missing("0", True, "amount_original"), "0")
        self.assertEqual(normalize_missing(0, True, "amount_original"), 0)
        self.assertEqual(normalize_missing("129,99", True, "amount_original"), "129,99")

    def test_missing_amounts_never_become_zero(self):
        for marker in ("", "N/A", "null", None):
            self.assertIsNone(convert_currency(marker, "USD"))
        self.assertEqual(convert_currency("0", "USD"), Decimal("0.00"))


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.schema = PROJECT_ROOT / "schemas/unified-schema.json"
        self.mapping = yaml.safe_load((PROJECT_ROOT / "examples/mappings/customer_a-order-mapping.yaml").read_text())
        self.stress_data = make_stress_data(self.folder / "generated")
        self.csv = PROJECT_ROOT / "data/examples/week1/customer_a_orders.csv"

    def validate(self, mapping=None, csv=None, schema=None, preview=False):
        path = self.folder / "mapping.yaml"
        path.write_text(yaml.safe_dump(mapping or self.mapping, sort_keys=False), encoding="utf-8")
        return validate_sample_mapping(csv or self.csv, path, schema or self.schema,
                                       preview_review_currency=preview)

    def find_rule(self, mapping, field):
        return next(rule for rule in mapping["rules"] if rule["target_field"] == field)

    def test_original_data_handles_invalid_date_with_warning(self):
        report = self.validate()
        self.assertEqual(report["summary"]["rules_failed"], 0)
        self.assertFalse(report["ready_for_etl"])
        date_rule = self.find_rule(report, "order_date")
        self.assertEqual(date_rule["rows_with_warnings"], 1)
        self.assertEqual(date_rule["row_results"][-1]["value"], None)

    def test_wrong_format_fails_declared_example(self):
        mapping = copy.deepcopy(self.mapping)
        rule = self.find_rule(mapping, "order_date")
        rule["expression"]["input_formats"] = ["%d.%m.%Y"]
        report = self.validate(mapping)
        self.assertEqual(self.find_rule(report, "order_date")["status"], "failed")
        self.assertIn("EXAMPLE_MISMATCH", [error["code"] for error in report["errors"]])

    def test_missing_status_translation_requires_review_or_fails(self):
        for policy, expected in (("manual_review", "manual_review"), ("reject_row", "failed")):
            mapping = copy.deepcopy(self.mapping)
            rule = self.find_rule(mapping, "order_status")
            del rule["expression"]["value_map"]["shipped"]
            rule["expression"]["unmapped_action"] = policy
            report = self.validate(mapping)
            self.assertEqual(self.find_rule(report, "order_status")["status"], expected)

    def test_default_bad_type_and_duplicate_targets_fail(self):
        mapping = copy.deepcopy(self.mapping)
        self.find_rule(mapping, "source_system")["expression"]["value"] = ["Customer A"]
        report = self.validate(mapping)
        self.assertEqual(self.find_rule(report, "source_system")["status"], "failed")
        mapping = copy.deepcopy(self.mapping)
        mapping["rules"].append(copy.deepcopy(mapping["rules"][0]))
        report = self.validate(mapping)
        self.assertEqual(report["summary"]["rules_failed"], 2)

    def test_nonnullable_null_is_failed(self):
        mapping = copy.deepcopy(self.mapping)
        rule = self.find_rule(mapping, "order_status")
        rule["expression"]["value_map"]["paid"] = None
        rule["example_output"] = None
        report = self.validate(mapping)
        self.assertEqual(self.find_rule(report, "order_status")["status"], "failed")

    def test_complex_name_is_a_review_rule(self):
        mapping = yaml.safe_load((PROJECT_ROOT / "examples/mappings/customer_a-customer-mapping.yaml").read_text())
        rule = self.find_rule(mapping, "full_name")
        rule.update(transformation_type="split", expression={"delimiter": " ", "part_index": 0, "trim": True, "on_error": "manual_review"},
                    example_input={"full_name": "Emma Johnson"}, example_output="Emma")
        csv = self.folder / "names.csv"
        csv.write_text("cust_id,full_name,email_addr,phone,signup_dt,loyalty_tier\nC1,Maria del Carmen,m@example.com,,2024-01-01,gold\n", encoding="utf-8")
        report = self.validate(mapping, csv)
        self.assertEqual(self.find_rule(report, "full_name")["rows_manual_review"], 1)

    def test_currency_preview_does_not_approve_review(self):
        mapping = yaml.safe_load((PROJECT_ROOT / "examples/mappings/customer_b-order-mapping.yaml").read_text())
        csv = PROJECT_ROOT / "data/examples/week1/customer_b_orders.csv"
        report = self.validate(mapping, csv, preview=True)
        rule = self.find_rule(report, "amount_usd")
        self.assertEqual(rule["status"], "manual_review")
        self.assertEqual(rule["row_results"][0]["test_preview"]["value"], "97.50")
        self.assertFalse(rule["row_results"][0]["test_preview"]["approved"])

    def test_unsupported_transform_is_reviewed(self):
        mapping = copy.deepcopy(self.mapping)
        self.find_rule(mapping, "source_order_id")["transformation_type"] = "prefix"
        report = self.validate(mapping)
        self.assertEqual(self.find_rule(report, "source_order_id")["status"], "manual_review")

    def test_explicit_fixed_rate_mapping_and_missing_rate_policies(self):
        mapping = yaml.safe_load((PROJECT_ROOT / "examples/mappings/customer_b-order-mapping.yaml").read_text())
        rule = self.find_rule(mapping, "amount_usd")
        rule.update(status="accepted", manual_review=False, review_reason=None, example_output=97.50)
        rule["expression"]["rate_source"] = "test_fixed_rates"
        original_csv = PROJECT_ROOT / "data/examples/week1/customer_b_orders.csv"
        report = self.validate(mapping, original_csv)
        self.assertEqual(self.find_rule(report, "amount_usd")["status"], "passed")
        self.assertEqual(self.find_rule(report, "amount_usd")["rows_with_warnings"], 4)
        csv = self.folder / "unknown-currency.csv"
        csv.write_text(original_csv.read_text().replace(",IDR,", ",GBP,"), encoding="utf-8")
        for policy, expected in (("null", "passed"), ("manual_review", "manual_review"), ("reject_row", "failed")):
            rule["expression"]["on_missing_rate"] = policy
            report = self.validate(mapping, csv)
            self.assertEqual(self.find_rule(report, "amount_usd")["status"], expected)

    def test_invalid_default_condition_is_failed(self):
        mapping = copy.deepcopy(self.mapping)
        self.find_rule(mapping, "source_system")["expression"]["apply_when"] = "when_empty"
        report = self.validate(mapping)
        self.assertEqual(self.find_rule(report, "source_system")["status"], "failed")

    def test_duplicate_yaml_keys_are_rejected(self):
        path = self.folder / "duplicate.yaml"
        path.write_text("mapping_version: '1.0'\nmapping_version: '1.0'\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate YAML key"):
            validate_sample_mapping(self.csv, path, self.schema)

    def test_empty_samples_are_not_passed(self):
        path = self.folder / "empty.csv"
        path.write_text("order_no,cust_id,order_dt,total_amt,currency,status\n", encoding="utf-8")
        report = self.validate(csv=path)
        self.assertEqual(report["summary"]["rules_passed"], 0)
        self.assertFalse(report["ready_for_etl"])

    def test_synthetic_null_amounts_pass_and_required_ids_still_fail(self):
        csv = self.stress_data / "customer_a_orders.csv"
        # The default sample includes intentionally missing amounts and customer IDs.
        report = self.validate(csv=csv)
        amount = self.find_rule(report, "amount_original")
        self.assertEqual(amount["status"], "passed")
        self.assertGreater(amount["rows_with_warnings"], 0)
        self.assertIsNone(amount["row_results"][0]["value"])
        self.assertEqual(self.find_rule(report, "amount_usd")["status"], "passed")
        self.assertEqual(self.find_rule(report, "source_customer_id")["status"], "failed")

    def test_raw_status_is_not_null_normalized(self):
        csv = self.folder / "raw-status.csv"
        csv.write_text("order_no,cust_id,order_dt,total_amt,currency,status\nA-1,C1,2024-01-01,0,USD,N/A\n", encoding="utf-8")
        report = self.validate(csv=csv)
        self.assertEqual(self.find_rule(report, "status_raw")["row_results"][0]["value"], "N/A")
        self.assertEqual(self.find_rule(report, "order_status")["status"], "manual_review")

    def test_b_and_c_mixed_case_statuses_are_verified(self):
        for source in ("b", "c"):
            mapping = yaml.safe_load((PROJECT_ROOT / f"examples/mappings/customer_{source}-order-mapping.yaml").read_text())
            csv = self.stress_data / f"customer_{source}_orders.csv"
            report = self.validate(mapping, csv)
            self.assertEqual(self.find_rule(report, "order_status")["status"], "passed")
            self.assertEqual(self.find_rule(report, "order_status")["rows_manual_review"], 0)

    def test_malformed_yaml_does_not_overwrite_existing_report(self):
        mapping = self.folder / "bad.yaml"
        mapping.write_text("rules: [unclosed", encoding="utf-8")
        output = self.folder / "existing.json"
        output.write_text('{"keep": true}\n', encoding="utf-8")
        result = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/validate_mapping.py"),
                                 str(self.csv), str(mapping), "--output", str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(output.read_text()), {"keep": True})
        self.assertEqual(json.loads(Path(str(output) + ".diagnostics.json").read_text())["status"], "error")


if __name__ == "__main__":
    unittest.main()
