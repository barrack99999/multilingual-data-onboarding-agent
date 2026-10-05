"""Evaluate Customer A field meanings against the Week 1 answer key."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.csv_profiler import profile_csv  # noqa: E402
from src.field_analyzer import analyze_fields  # noqa: E402


EXPECTED = {
    "customer_a_customers.csv": {
        "cust_id": "customer_id",
        "full_name": "full_name",
        "email_addr": "email",
        "phone": "phone",
        "signup_dt": "signup_date",
        "loyalty_tier": "loyalty_tier",
    },
    "customer_a_orders.csv": {
        "order_no": "order_id",
        "cust_id": "customer_id",
        "order_dt": "order_date",
        "total_amt": "amount",
        "currency": "currency",
        "status": "order_status",
    },
}


def score_file(file_name: str, analysis: dict) -> list[dict]:
    actual = {field["field_name"]: field for field in analysis["fields"]}
    rows = []
    for field_name, expected_type in EXPECTED[file_name].items():
        actual_field = actual.get(field_name, {})
        actual_type = actual_field.get("semantic_type", "missing")
        rows.append(
            {
                "file_name": file_name,
                "field_name": field_name,
                "expected_semantic_type": expected_type,
                "actual_semantic_type": actual_type,
                "confidence": actual_field.get("confidence"),
                "correct": actual_type == expected_type,
            }
        )
    return rows


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not configured in .env.")

    data_dir = PROJECT_ROOT / "data" / "examples" / "week1"
    outputs_dir = PROJECT_ROOT / "outputs"
    analyses = {}
    comparisons = []

    try:
        for file_name in EXPECTED:
            csv_path = data_dir / file_name
            profile = profile_csv(csv_path)
            analysis = analyze_fields(csv_path, profile)
            analyses[file_name] = analysis
            comparisons.extend(score_file(file_name, analysis))
    except APIError as error:
        raise SystemExit(f"OpenAI API call failed: {error}") from error

    correct_count = sum(row["correct"] for row in comparisons)
    total_fields = len(comparisons)
    evaluation = {
        "reference": "data/examples/week1 fictional public Customer A CSV files",
        "scoring_method": "Exact semantic-type match for all 12 Customer A fields",
        "correct_fields": correct_count,
        "total_fields": total_fields,
        "accuracy": round(correct_count / total_fields, 4),
        "comparisons": comparisons,
    }

    analysis_path = outputs_dir / "customer-a-field-analysis.json"
    evaluation_path = outputs_dir / "customer-a-field-analysis-evaluation.json"
    analysis_path.write_text(
        json.dumps(analyses, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    evaluation_path.write_text(
        json.dumps(evaluation, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Customer A accuracy: {correct_count}/{total_fields} ({evaluation['accuracy']:.1%})")
    for row in comparisons:
        status = "PASS" if row["correct"] else "FAIL"
        print(
            f"- {status} {row['file_name']}:{row['field_name']} "
            f"expected={row['expected_semantic_type']} actual={row['actual_semantic_type']} "
            f"confidence={row['confidence']}"
        )
    print(f"Saved analysis to {analysis_path}")
    print(f"Saved evaluation to {evaluation_path}")


if __name__ == "__main__":
    main()
