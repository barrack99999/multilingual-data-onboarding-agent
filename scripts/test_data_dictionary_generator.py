"""Offline, self-contained checks for dictionary consistency and review flags."""

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

from src.data_dictionary_generator import DictionaryInputError, generate_data_dictionary, render_markdown  # noqa: E402


class DictionaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.schema_path = self.folder / "schema.json"
        self.analysis_path = self.folder / "analysis.json"
        self.mapping_paths = [self.folder / f"{source}-mapping.yaml" for source in ("a", "b")]
        self.schema = {"schema_version": "1.1", "tables": [{"name": "unified_customers",
            "grain": "One customer per source.", "primary_key": "source_customer_id", "fields": [
                {"name": name, "type": kind, "nullable": nullable, "description": description,
                 "rationale": "Schema policy.", "source_coverage": {"sources": ["Customer A", "Customer B"], "source_fields": []}}
                for name, kind, nullable, description in [
                    ("source_customer_id", "string", False, "Source customer ID."),
                    ("source_system", "string", False, "System of origin."),
                    ("phone", "string", True, "International phone when approved."),
                    ("customer_segment", "string", True, "Optional segment.")]]}]}
        self.analyses, self.mappings = {}, []
        for letter, source in (("a", "Customer A"), ("b", "Customer B")):
            filename = f"{letter}_customers.csv"
            fields = [{"field_name": name, "semantic_type": semantic, "description": description,
                       "confidence": 0.9, "evidence": [{"source": "field_name", "detail": "Name clue."}]}
                      for name, semantic, description in [("cust_id", "customer_id", "Source ID interpretation."),
                                                           ("phone", "phone", "Source phone interpretation.")]]
            self.analyses[filename] = {"file_name": filename, "table_type": "customer", "fields": fields}
            def rule(target, sources, kind, expression, sample, output, review=False):
                return {"target_field": target, "source_fields": sources, "transformation_type": kind,
                        "expression": expression, "example_input": sample, "example_output": output,
                        "notes": "Documented mapping.", "confidence": 0.95, "evidence": ["Example clue."],
                        "status": "needs_review" if review else "accepted", "manual_review": review,
                        "review_reason": "Phone normalization deferred." if review else None}
            rules = [rule("source_customer_id", ["cust_id"], "rename", {"operation": "copy"}, {"cust_id": "001"}, "001"),
                     rule("source_system", [], "default_value", {"value": source, "apply_when": "always"}, {}, source),
                     rule("phone", ["phone"], "manual_review", {"requested_operation": "normalize_phone", "proposed_logic": "Normalize after review."},
                          {"phone": "+49 123"}, None, True)]
            self.mappings.append({"mapping_version": "1.0", "source_system": source,
                "source_file": f"data/{filename}", "table_type": "customer", "target_table": "unified_customers",
                "rules": rules, "unmapped_source_fields": [], "unmapped_target_fields": ["customer_segment"], "warnings": []})
        self.write()

    def write(self):
        self.schema_path.write_text(json.dumps(self.schema), encoding="utf-8")
        self.analysis_path.write_text(json.dumps(self.analyses), encoding="utf-8")
        for path, mapping in zip(self.mapping_paths, self.mappings):
            path.write_text(yaml.safe_dump(mapping, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def generate(self, paths=None):
        return generate_data_dictionary(self.schema_path, [self.analysis_path], self.mapping_paths if paths is None else paths)

    def field(self, name):
        return next(field for field in self.generate()["tables"][0]["fields"] if field["name"] == name)

    def assert_code(self, code):
        with self.assertRaises(DictionaryInputError) as error:
            self.generate()
        self.assertEqual(error.exception.code, code)

    def cli(self):
        return subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/data_dictionary_generator.py"),
            "--schema", str(self.schema_path), "--analysis", str(self.analysis_path),
            "--mappings", *(str(path) for path in self.mapping_paths), "--output-dir", str(self.folder / "out")],
            capture_output=True, text=True)

    def test_every_schema_field_once_in_order_with_exact_metadata(self):
        fields = self.generate()["tables"][0]["fields"]
        self.assertEqual(len(fields), 4)
        for expected, actual in zip(self.schema["tables"][0]["fields"], fields):
            for key in ("name", "type", "nullable", "description"):
                self.assertEqual(actual[key], expected[key])
            for key in ("table_name", "source_fields", "transformation_notes", "example_values", "comments"):
                self.assertIn(key, actual)

    def test_source_analysis_is_linked_without_overriding_business_meaning(self):
        field = self.field("source_customer_id")
        self.assertEqual(field["description"], "Source customer ID.")
        self.assertEqual(field["source_lineage"][0]["field_analysis"][0]["description"], "Source ID interpretation.")
        self.assertEqual(field["source_fields"], ["Customer A: cust_id", "Customer B: cust_id"])

    def test_manual_review_null_example_is_not_an_approved_default(self):
        field = self.field("phone")
        for lineage, example in zip(field["source_lineage"], field["example_values"]):
            self.assertTrue(lineage["manual_review"])
            self.assertEqual(lineage["expression"], self.mappings[0]["rules"][2]["expression"])
            self.assertEqual(example["status"], "proposed_not_validated")
            self.assertIsNone(example["output"])

    def test_default_is_source_free_and_examples_preserve_leading_zero(self):
        self.assertEqual(self.field("source_system")["source_fields"], [])
        self.assertEqual(self.field("source_customer_id")["example_values"][0]["output"], "001")

    def test_optional_unmapped_fields_remain_visible_without_invented_examples(self):
        field = self.field("customer_segment")
        self.assertEqual(field["example_values"], [])
        self.assertTrue(all(item["mapping_status"] == "unmapped" for item in field["source_lineage"]))
        self.assertEqual(self.generate()["summary"]["unmapped_lineages"], 2)

    def test_partial_customer_coverage_produces_warning_not_fake_lineage(self):
        dictionary = self.generate([self.mapping_paths[0]])
        self.assertTrue(any(w["code"] == "PARTIAL_LINEAGE" for w in dictionary["warnings"]))
        self.assertEqual(len(dictionary["tables"][0]["fields"][0]["source_lineage"]), 1)

    def test_missing_or_duplicate_mapping_inputs_are_rejected(self):
        for paths in ([], [self.mapping_paths[0], self.mapping_paths[0]]):
            with self.assertRaises(DictionaryInputError):
                self.generate(paths)

    def test_duplicate_yaml_keys_are_rejected(self):
        with self.mapping_paths[0].open("a", encoding="utf-8") as handle:
            handle.write("\nsource_system: Customer Z\n")
        self.assert_code("INVALID_MAPPING")

    def test_unknown_source_and_target_and_duplicate_targets_are_rejected(self):
        original = copy.deepcopy(self.mappings)
        for change in ("source", "target", "duplicate"):
            self.mappings = copy.deepcopy(original)
            rule = self.mappings[0]["rules"][0]
            if change == "source":
                rule["source_fields"] = ["nonexistent"]
            elif change == "target":
                rule["target_field"] = "nonexistent"
            else:
                self.mappings[0]["rules"].append(copy.deepcopy(rule))
            self.write()
            self.assert_code("INVALID_MAPPING")

    def test_source_constant_and_table_mismatches_are_rejected(self):
        original = copy.deepcopy(self.mappings)
        self.mappings[0]["rules"][1]["expression"]["value"] = "Wrong source"
        self.write()
        self.assert_code("INVALID_MAPPING")
        self.mappings = original
        self.mappings[0]["table_type"] = "order"
        self.write()
        self.assert_code("INVALID_MAPPING")

    def test_missing_analysis_and_wrong_table_type_are_rejected(self):
        self.analyses["a_customers.csv"]["table_type"] = "order"
        self.write()
        self.assert_code("INVALID_ANALYSIS")
        del self.analyses["a_customers.csv"]
        self.write()
        self.assert_code("INVALID_ANALYSIS")

    def test_blank_business_meaning_and_bad_nullable_are_rejected(self):
        self.schema["tables"][0]["fields"][0]["description"] = ""
        self.write()
        self.assert_code("MISSING_REQUIRED_DESCRIPTION")
        self.schema["tables"][0]["fields"][0]["description"] = "Restored"
        self.schema["tables"][0]["fields"][0]["nullable"] = "false"
        self.write()
        self.assert_code("INVALID_SCHEMA")

    def test_required_unmapped_and_unsupported_transforms_are_rejected(self):
        self.schema["tables"][0]["fields"][3]["nullable"] = False
        self.write()
        self.assert_code("INVALID_MAPPING")
        self.schema["tables"][0]["fields"][3]["nullable"] = True
        self.mappings[0]["rules"][0]["transformation_type"] = "prefix"
        self.write()
        self.assert_code("INVALID_MAPPING")

    def test_uncertain_analysis_and_mapping_are_flagged(self):
        self.analyses["a_customers.csv"]["fields"][0]["confidence"] = 0.4
        self.mappings[1]["rules"][0]["confidence"] = 0.5
        self.write()
        self.assertTrue(all(item["manual_review"] for item in self.field("source_customer_id")["source_lineage"]))

    def test_invalid_analysis_confidence_and_evidence_are_rejected(self):
        self.analyses["a_customers.csv"]["fields"][0]["confidence"] = 2
        self.write()
        self.assert_code("INVALID_ANALYSIS")
        self.analyses["a_customers.csv"]["fields"][0]["confidence"] = 0.9
        self.analyses["a_customers.csv"]["fields"][0]["evidence"] = [{}]
        self.write()
        self.assert_code("INVALID_ANALYSIS")

    def test_schema_coverage_disagreement_is_visible(self):
        self.schema["tables"][0]["fields"][0]["source_coverage"]["source_fields"] = ["Customer A: different_id"]
        self.write()
        self.assertTrue(any("different_id" in w["message"] for w in self.generate()["warnings"]))

    def test_markdown_escapes_data_and_preserves_unicode(self):
        self.schema["tables"][0]["fields"][0]["description"] = "Währung | [x]\n<script>bad</script>"
        self.write()
        markdown = render_markdown(self.generate())
        self.assertIn("Währung \\| \\[x\\]<br>&lt;script&gt;", markdown)
        self.assertNotIn("<script>", markdown)
        for section in ("Unified Customers", "Source Lineage", "Known Limitations", "Input Provenance"):
            self.assertIn(section, markdown)

    def test_output_is_deterministic_and_tracks_input_changes(self):
        before = self.generate()
        self.assertEqual(before, self.generate())
        self.schema["tables"][0]["fields"][0]["description"] = "New definition"
        self.write()
        after = self.generate()
        self.assertNotEqual(before["provenance"], after["provenance"])
        self.assertEqual(after["tables"][0]["fields"][0]["description"], "New definition")

    def test_cli_writes_both_outputs_and_shared_diagnostics(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = self.folder / "out"
        self.assertTrue((folder / "data-dictionary.md").is_file())
        self.assertEqual(json.loads((folder / "data-dictionary.json").read_text())["summary"]["fields"], 4)
        diagnostics = json.loads((folder / "data-dictionary.md.diagnostics.json").read_text())
        self.assertEqual(diagnostics["module"], "DataDictionaryGenerator")
        self.assertEqual(diagnostics["status"], "warning")
        self.assertEqual(diagnostics["errors"], [])

    def test_cli_invalid_input_preserves_previous_outputs(self):
        self.assertEqual(self.cli().returncode, 0)
        outputs = [self.folder / "out" / f"data-dictionary.{extension}" for extension in ("md", "json")]
        before = [path.read_bytes() for path in outputs]
        self.mappings[0]["rules"][0]["target_field"] = "wrong"
        self.write()
        result = self.cli()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, [path.read_bytes() for path in outputs])
        diagnostics = json.loads((self.folder / "out/data-dictionary.md.diagnostics.json").read_text())
        self.assertEqual(diagnostics["errors"][0]["code"], "INVALID_MAPPING")

    def new_customer_inputs(self):
        """Build unrelated customer/order exports, with no A/B/C field names."""
        templates = copy.deepcopy(self.mappings[0]["rules"])
        self.analyses = {}
        self.mappings = []
        self.mapping_paths = []
        self.schema["tables"][0]["fields"].append({
            "name": "preferred_language", "type": "string", "nullable": True,
            "description": "Customer's preferred contact language.",
            "source_coverage": {"sources": ["Maple Store", "Pearl Retail"], "source_fields": []}})
        order_fields = [
            {"name": "source_order_id", "type": "string", "nullable": False, "description": "Original order identifier."},
            {"name": "source_system", "type": "string", "nullable": False, "description": "System of origin."},
            {"name": "order_date", "type": "date", "nullable": True, "description": "Order placement date."}]
        self.schema["tables"].append({"name": "unified_orders", "primary_key": "source_order_id",
                                      "grain": "One order per source.", "fields": order_fields})
        for index, source in enumerate(("Maple Store", "Pearl Retail")):
            names = ["顧客番号", "連絡先", "言語"] if index == 0 else ["account_ref", "mobile_contact", "contact_language"]
            filename = f"export_{index}_clients.csv"
            fields = [{"field_name": name, "semantic_type": semantic, "description": description,
                       "confidence": 0.95, "evidence": ["Explicit source documentation and sample."]}
                      for name, semantic, description in zip(names, ["customer_id", "phone", "language"],
                                                             ["Customer reference.", "Contact phone.", "Contact language."])]
            self.analyses[filename] = {"file_name": filename, "table_type": "customer", "fields": fields}
            rules = copy.deepcopy(templates)
            for rule in rules:
                if rule["target_field"] == "source_system":
                    rule["expression"]["value"] = source
                    rule["example_output"] = source
                else:
                    source_field = names[0] if rule["target_field"] == "source_customer_id" else names[1]
                    rule["source_fields"] = [source_field]
                    rule["example_input"] = {source_field: "0007" if source_field == names[0] else "+81 123"}
                    if rule["target_field"] == "source_customer_id":
                        rule["example_output"] = "0007"
            language_rule = copy.deepcopy(rules[0])
            language_rule.update(target_field="preferred_language", source_fields=[names[2]],
                                 example_input={names[2]: "日本語"}, example_output="日本語")
            rules.append(language_rule)
            self.mappings.append({"mapping_version": "1.0", "source_system": source,
                "source_file": f"data/{source}/{filename}", "table_type": "customer", "target_table": "unified_customers",
                "rules": rules, "unmapped_source_fields": [], "unmapped_target_fields": ["customer_segment"], "warnings": []})
            self.mapping_paths.append(self.folder / f"export_{index}-customer-mapping.yaml")
            order_filename = f"export_{index}_transactions.csv"
            order_names = ["purchase_ref", "placed_on"]
            self.analyses[order_filename] = {"file_name": order_filename, "table_type": "order", "fields": [
                {"field_name": name, "semantic_type": semantic, "description": "Documented order attribute.",
                 "confidence": 0.9, "evidence": ["Documented sample."]}
                for name, semantic in zip(order_names, ["order_id", "order_date"])]}
            order_rules = copy.deepcopy(rules[:2])
            order_rules[0].update(target_field="source_order_id", source_fields=[order_names[0]],
                                  example_input={order_names[0]: "PO-001"}, example_output="PO-001")
            date_rule = copy.deepcopy(order_rules[0])
            date_rule.update(target_field="order_date", source_fields=[order_names[1]], transformation_type="parse_date",
                expression={"input_formats": ["%d/%m/%Y"], "output_format": "%Y-%m-%d", "on_error": "null"},
                example_input={order_names[1]: "16/10/2026"}, example_output="2026-10-16")
            order_rules.append(date_rule)
            self.mappings.append({"mapping_version": "1.0", "source_system": source,
                "source_file": f"data/{source}/{order_filename}", "table_type": "order", "target_table": "unified_orders",
                "rules": order_rules, "unmapped_source_fields": [], "unmapped_target_fields": [], "warnings": []})
            self.mapping_paths.append(self.folder / f"export_{index}-order-mapping.yaml")
        for table in self.schema["tables"]:
            for field in table["fields"]:
                field["source_coverage"] = {"sources": ["Maple Store", "Pearl Retail"], "source_fields": []}
        self.write()

    def test_reuse_with_new_customers_fields_and_schema_without_code_changes(self):
        self.new_customer_inputs()
        dictionary = self.generate()
        self.assertEqual(dictionary["summary"]["source_systems"], ["Maple Store", "Pearl Retail"])
        self.assertEqual(dictionary["summary"]["mapping_files"], 4)
        self.assertEqual(dictionary["summary"]["fields"], 8)
        field = dictionary["tables"][0]["fields"][-1]
        self.assertEqual(field["name"], "preferred_language")
        self.assertEqual(field["source_fields"], ["Maple Store: 言語", "Pearl Retail: contact_language"])
        self.assertEqual(field["example_values"][0]["output"], "日本語")
        self.assertNotIn("Customer A", render_markdown(dictionary))
        self.assertEqual(dictionary["tables"][1]["fields"][-1]["name"], "order_date")

    def test_reuse_accepts_separate_analysis_files(self):
        self.new_customer_inputs()
        paths = []
        for index, analysis in enumerate(self.analyses.values()):
            path = self.folder / f"analysis-{index}.json"
            path.write_text(json.dumps(analysis), encoding="utf-8")
            paths.append(path)
        dictionary = generate_data_dictionary(self.schema_path, paths, self.mapping_paths)
        self.assertEqual(dictionary["summary"]["source_systems"], ["Maple Store", "Pearl Retail"])

    def test_reuse_cli_keeps_customer_outputs_separate(self):
        self.assertEqual(self.cli().returncode, 0)
        original = (self.folder / "out/data-dictionary.md").read_bytes()
        self.new_customer_inputs()
        destination = self.folder / "new-customers"
        result = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/data_dictionary_generator.py"),
            "--schema", str(self.schema_path), "--analysis", str(self.analysis_path),
            "--mappings", *(str(path) for path in self.mapping_paths), "--output-dir", str(destination)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.folder / "out/data-dictionary.md").read_bytes(), original)
        dictionary = json.loads((destination / "data-dictionary.json").read_text())
        self.assertEqual(dictionary["summary"]["source_systems"], ["Maple Store", "Pearl Retail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
