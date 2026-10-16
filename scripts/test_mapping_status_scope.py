"""Regression tests for unapproved cross-customer status translations."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mapping_generator import MappingRule, _status_scope_errors  # noqa: E402


def rule(values, *, case_sensitive=False, trim=True):
    return MappingRule(target_field="order_status", source_fields=["status"], transformation_type="map_value",
        expression={"value_map": values, "case_sensitive": case_sensitive, "trim_before_match": trim,
                    "unmapped_action": "manual_review"}, example_input={"status": next(iter(values))},
        example_output=next(iter(values.values())), notes="Documented statuses.", confidence=0.95,
        evidence=["Observed source values."], status="accepted", manual_review=False, review_reason=None)


class StatusScopeTests(unittest.TestCase):
    def test_local_categories_are_accepted(self):
        self.assertEqual(_status_scope_errors(rule({"paid": "paid", "pending": "pending"}), ["paid", "pending"]), [])

    def test_foreign_hints_do_not_authorize_extra_categories(self):
        errors = _status_scope_errors(rule({"paid": "paid", "BEZ": "paid", "dibayar": "paid"}), ["paid"])
        self.assertTrue(any("not observed" in error and "bez" in error and "dibayar" in error for error in errors))

    def test_casing_and_whitespace_variants_are_not_foreign(self):
        self.assertEqual(_status_scope_errors(rule({" BEZ ": "paid", "bez": "paid"}), ["Bez", " BEZ "]), [])

    def test_missing_observed_category_is_rejected(self):
        self.assertTrue(any("missing from" in error for error in _status_scope_errors(rule({"paid": "paid"}), ["paid", "pending"])))

    def test_case_sensitive_policy_is_respected(self):
        self.assertTrue(_status_scope_errors(rule({"paid": "paid"}, case_sensitive=True), ["PAID"]))

    def test_indonesian_source_does_not_accept_sap_code(self):
        self.assertTrue(_status_scope_errors(rule({"dibayar": "paid", "BEZ": "paid"}), ["dibayar"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
