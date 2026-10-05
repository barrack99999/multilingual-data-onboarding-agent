"""Evaluate Indonesian and German/SAP field recognition for Customers B and C."""

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
    "customer_b_customers.csv": {
        "id_pelanggan": "customer_id",
        "nama_lengkap": "full_name",
        "email": "email",
        "no_hp": "phone",
        "tgl_daftar": "signup_date",
        "segmen": "customer_segment",
    },
    "customer_b_orders.csv": {
        "no_pesanan": "order_id",
        "id_pelanggan": "customer_id",
        "tgl_pesanan": "order_date",
        "total_harga": "amount",
        "mata_uang": "currency",
        "status_pesanan": "order_status",
    },
    "customer_c_customers.csv": {
        "Kundennummer": "customer_id",
        "Name1": "full_name",
        "EMail": "email",
        "Telefon": "phone",
        "Erfassungsdatum": "signup_date",
        "Kundengruppe": "customer_segment",
    },
    "customer_c_orders.csv": {
        "Bestellnummer": "order_id",
        "Kundennummer": "customer_id",
        "Bestelldatum": "order_date",
        "Betrag": "amount",
        "Währung": "currency",
        "StatusCode": "order_status",
    },
}

FOCUS_FIELDS = {
    "id_pelanggan",
    "tgl_daftar",
    "total_harga",
    "Kundennummer",
    "Bestelldatum",
    "Währung",
}

FALLBACK_ACCURACY_THRESHOLD = 0.80


def _has_actual_sample(evidence: list[dict], profile_field: dict) -> bool:
    details = " ".join(
        item["detail"] for item in evidence if item["source"] == "sample_values"
    ).lower()
    return any(str(value).lower() in details for value in profile_field["sample_values"])


def score_file(file_name: str, analysis: dict, profile: dict) -> list[dict]:
    actual = {field["field_name"]: field for field in analysis["fields"]}
    profiled = {field["field_name"]: field for field in profile["fields"]}
    rows = []

    for field_name, expected_type in EXPECTED[file_name].items():
        actual_field = actual[field_name]
        profile_field = profiled[field_name]
        actual_type = actual_field["semantic_type"]
        correct = actual_type == expected_type
        confidence = actual_field["confidence"]
        sources = {item["source"] for item in actual_field["evidence"]}

        confidence_reasonable = confidence >= 0.70 if correct else confidence < 0.70
        is_messy_date = (
            profile_field["patterns"]["looks_like_date"]
            and profile_field["null_rate"] >= 0.20
        )
        if correct and is_messy_date:
            confidence_reasonable = confidence_reasonable and confidence <= 0.90

        evidence_credible = (
            "field_name" in sources
            and "sample_values" in sources
            and _has_actual_sample(actual_field["evidence"], profile_field)
        )

        rows.append(
            {
                "file_name": file_name,
                "field_name": field_name,
                "focus_field": field_name in FOCUS_FIELDS,
                "expected_semantic_type": expected_type,
                "actual_semantic_type": actual_type,
                "correct": correct,
                "confidence": confidence,
                "confidence_reasonable": confidence_reasonable,
                "evidence_sources": sorted(sources),
                "evidence_credible": evidence_credible,
                "evidence": actual_field["evidence"],
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
            comparisons.extend(score_file(file_name, analysis, profile))
    except APIError as error:
        raise SystemExit(f"OpenAI API call failed: {error}") from error

    correct_count = sum(row["correct"] for row in comparisons)
    reasonable_count = sum(row["confidence_reasonable"] for row in comparisons)
    credible_count = sum(row["evidence_credible"] for row in comparisons)
    total_fields = len(comparisons)
    accuracy = correct_count / total_fields
    open_issues = [
        {
            "file_name": row["file_name"],
            "field_name": row["field_name"],
            "reason": "incorrect semantic type",
        }
        for row in comparisons
        if not row["correct"]
    ]

    evaluation = {
        "prompt_version": "multilingual-v2-with-explicit-evidence-sources",
        "reference": "data/examples/week1 fictional public Customer B and C CSV files",
        "scoring_method": "Exact semantic-type match across all 24 B/C fields",
        "fallback_accuracy_threshold": FALLBACK_ACCURACY_THRESHOLD,
        "correct_fields": correct_count,
        "total_fields": total_fields,
        "accuracy": round(accuracy, 4),
        "reasonable_confidence_fields": reasonable_count,
        "credible_evidence_fields": credible_count,
        "fallback_required": accuracy < FALLBACK_ACCURACY_THRESHOLD,
        "open_issues": open_issues,
        "comparisons": comparisons,
    }

    analysis_path = outputs_dir / "multilingual-field-analysis.json"
    evaluation_path = outputs_dir / "multilingual-field-analysis-evaluation.json"
    analysis_path.write_text(
        json.dumps(analyses, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    evaluation_path.write_text(
        json.dumps(evaluation, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"B/C accuracy: {correct_count}/{total_fields} ({accuracy:.1%})")
    print(f"Reasonable confidence: {reasonable_count}/{total_fields}")
    print(f"Credible evidence: {credible_count}/{total_fields}")
    print(f"Fallback required: {evaluation['fallback_required']}")
    for row in comparisons:
        if row["focus_field"]:
            print(
                f"- {row['field_name']}: expected={row['expected_semantic_type']} "
                f"actual={row['actual_semantic_type']} confidence={row['confidence']} "
                f"confidence_ok={row['confidence_reasonable']} "
                f"evidence_ok={row['evidence_credible']}"
            )
    print(f"Saved analysis to {analysis_path}")
    print(f"Saved evaluation to {evaluation_path}")


if __name__ == "__main__":
    main()
