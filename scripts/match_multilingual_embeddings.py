"""Match multilingual CSV fields with a pretrained embedding model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.multilingual_matcher import MODEL_NAME, run_experiment  # noqa: E402


def _load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    outputs = PROJECT_ROOT / "outputs"
    schema_path = outputs / "unified-schema.json"
    analysis_paths = [
        outputs / "customer-a-field-analysis.json",
        outputs / "multilingual-field-analysis.json",
    ]
    for path in [schema_path, *analysis_paths]:
        if not path.is_file():
            raise SystemExit(f"Required input not found: {path}")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    analyses: dict[str, Any] = {}
    for path in analysis_paths:
        analyses.update(json.loads(path.read_text(encoding="utf-8")))
    return schema, analyses


def _field_case(result: dict[str, Any], field_name: str, customer: str) -> str:
    for item in result["top_matches"]:
        source = item["source"]
        if source["field_name"] == field_name and source["customer"] == customer:
            suggestions = ", ".join(
                f"{match['customer']} `{match['field_name']}` ({match['similarity']:.4f}, "
                f"{'correct' if match['correct'] else 'incorrect'})"
                for match in item["matches"]
            )
            return suggestions
    return "Not found"


def _report(result: dict[str, Any]) -> str:
    name_only = result["approaches"]["field_name_only"]
    with_samples = result["approaches"]["field_name_plus_samples"]
    important_cases = [
        ("Customer A", "cust_id", "English company abbreviation"),
        ("Customer B", "id_pelanggan", "Indonesian customer ID"),
        ("Customer B", "tgl_daftar", "Indonesian date abbreviation"),
        ("Customer C", "Kundennummer", "German customer number"),
        ("Customer C", "Bestelldatum", "German order date"),
        ("Customer C", "Name1", "SAP-style name field"),
    ]

    lines = [
        "# Week 2 — Optional Task 6: Multilingual Embedding Matching",
        "",
        "## Goal",
        "",
        "Test whether a pretrained multilingual embedding model can match English,",
        "Indonesian, and German/SAP-style field names that represent the same",
        "business concept. No model training or fine-tuning was performed.",
        "",
        "## Setup",
        "",
        f"- Model: `{result['model']}`",
        f"- Fields evaluated: {result['record_count']}",
        f"- Similarity threshold: {name_only['threshold']}",
        "- Similarity measure: cosine similarity on normalized embeddings",
        "- Comparison rule: compare fields across customers within the same table type",
        "- Answer key: Week 1 synthetic-data design note",
        "- LLM comparison: FieldAnalyzer results and Task 4 schema source coverage",
        "",
        "## Results",
        "",
        "| Approach | Fields correct in both other customers | Accuracy | Pair precision | Pair recall | Pair F1 | Disagreements |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, data in (("Field name only", name_only), ("Field name + samples", with_samples)):
        accuracy = data["field_accuracy"]
        pairs = data["pair_grouping_quality"]
        lines.append(
            f"| {label} | {accuracy['correct_fields']}/{accuracy['total_fields']} | "
            f"{accuracy['accuracy']:.1%} | {pairs['precision']:.1%} | "
            f"{pairs['recall']:.1%} | {pairs['f1']:.1%} | "
            f"{len(data['disagreements_with_llm_or_schema'])} |"
        )

    delta = with_samples["field_accuracy"]["accuracy"] - name_only["field_accuracy"]["accuracy"]
    lines.extend([
        "",
        "A field counts as correct only when its highest-similarity field in each",
        "of the other two customers has the same expected business meaning. Pair",
        "precision and recall measure all cross-customer pairs above the threshold.",
        "",
        "## Important Field Cases",
        "",
        "| Field | Why it matters | Name-only result | Name + samples result |",
        "|---|---|---|---|",
    ])
    for customer, field_name, reason in important_cases:
        lines.append(
            f"| `{field_name}` | {reason} | "
            f"{_field_case(name_only, field_name, customer)} | "
            f"{_field_case(with_samples, field_name, customer)} |"
        )

    lines.extend([
        "",
        "## Comparison with the LLM and Unified Schema",
        "",
        f"- Name-only embeddings produced {len(name_only['disagreements_with_llm_or_schema'])} "
        "top-match disagreements.",
        f"- Adding samples produced {len(with_samples['disagreements_with_llm_or_schema'])} "
        "top-match disagreements.",
        f"- The field-level accuracy change after adding samples was {delta:+.1%}.",
        "- The JSON result lists every disagreement with the expected meaning,",
        "  FieldAnalyzer semantic type, and unified-schema target.",
        "",
        "## What This Experiment Shows",
        "",
        "A multilingual embedding model is useful for generating candidate matches,",
        "especially when words have clear language meaning. It is not a safe final",
        "decision-maker. Short abbreviations, identifiers, generic value patterns,",
        "and company-specific fields such as `Name1` can produce plausible but wrong",
        "neighbors. Sample values may help descriptive fields, but may also make ID,",
        "date, currency, or status fields look similar for the wrong reason.",
        "",
        "The recommended workflow is therefore:",
        "",
        "1. Use embeddings to propose likely cross-language matches.",
        "2. Use the FieldAnalyzer or a human to judge ambiguous cases.",
        "3. Validate accepted mappings against the unified schema.",
        "4. Never accept a mapping only because its cosine similarity exceeds a threshold.",
        "",
        "## Files",
        "",
        "- Detailed metrics, matches, groups, and disagreements:",
        "  `outputs/week2-task6-multilingual-embeddings.json`",
        "- This report: `outputs/week2-task6-multilingual-embeddings-report.md`",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--threshold", type=float, default=0.60)
    args = parser.parse_args()
    if not 0.0 <= args.threshold <= 1.0:
        raise SystemExit("--threshold must be between 0 and 1.")

    schema, analyses = _load_inputs()
    result = run_experiment(
        PROJECT_ROOT / "data" / "generated",
        schema,
        analyses,
        model_name=args.model,
        threshold=args.threshold,
    )

    outputs = PROJECT_ROOT / "outputs"
    json_path = outputs / "week2-task6-multilingual-embeddings.json"
    report_path = outputs / "week2-task6-multilingual-embeddings-report.md"
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(_report(result), encoding="utf-8")

    for approach, data in result["approaches"].items():
        score = data["field_accuracy"]
        print(
            f"{approach}: {score['correct_fields']}/{score['total_fields']} "
            f"fields correct ({score['accuracy']:.1%})"
        )
    print(f"Saved detailed results to {json_path}")
    print(f"Saved report to {report_path}")


if __name__ == "__main__":
    main()
