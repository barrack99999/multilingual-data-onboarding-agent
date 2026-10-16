"""Compare multilingual CSV fields with a pretrained embedding model."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
NULL_MARKERS = {"", "n/a", "na", "null", "none", "nan", "missing"}

# Week 1 data-design note, represented as a machine-checkable answer key.
EXPECTED_SEMANTICS = {
    "customer_a_customers.csv": {
        "cust_id": "customer_id", "full_name": "full_name",
        "email_addr": "email", "phone": "phone",
        "signup_dt": "signup_date", "loyalty_tier": "loyalty_tier",
    },
    "customer_a_orders.csv": {
        "order_no": "order_id", "cust_id": "customer_id",
        "order_dt": "order_date", "total_amt": "amount",
        "currency": "currency", "status": "order_status",
    },
    "customer_b_customers.csv": {
        "id_pelanggan": "customer_id", "nama_lengkap": "full_name",
        "email": "email", "no_hp": "phone",
        "tgl_daftar": "signup_date", "segmen": "customer_segment",
    },
    "customer_b_orders.csv": {
        "no_pesanan": "order_id", "id_pelanggan": "customer_id",
        "tgl_pesanan": "order_date", "total_harga": "amount",
        "mata_uang": "currency", "status_pesanan": "order_status",
    },
    "customer_c_customers.csv": {
        "Kundennummer": "customer_id", "Name1": "full_name",
        "EMail": "email", "Telefon": "phone",
        "Erfassungsdatum": "signup_date", "Kundengruppe": "customer_segment",
    },
    "customer_c_orders.csv": {
        "Bestellnummer": "order_id", "Kundennummer": "customer_id",
        "Bestelldatum": "order_date", "Betrag": "amount",
        "Währung": "currency", "StatusCode": "order_status",
    },
}


def _customer_name(file_name: str) -> str:
    return {
        "customer_a": "Customer A",
        "customer_b": "Customer B",
        "customer_c": "Customer C",
    }["_".join(file_name.lower().split("_")[:2])]


def _table_type(file_name: str) -> str:
    return "customer" if "_customers." in file_name.lower() else "order"


def _samples(path: Path, field_name: str, limit: int = 3) -> list[str]:
    values: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            value = (row.get(field_name) or "").strip()
            if value.lower() not in NULL_MARKERS and value not in values:
                values.append(value)
            if len(values) == limit:
                break
    return values


def load_field_records(data_dir: Path) -> list[dict[str, Any]]:
    """Load field names, sample values, and answer-key meanings."""
    records: list[dict[str, Any]] = []
    for file_name, fields in EXPECTED_SEMANTICS.items():
        csv_path = data_dir / file_name
        if not csv_path.is_file():
            raise FileNotFoundError(f"Required generated CSV not found: {csv_path}")
        for field_name, semantic_type in fields.items():
            records.append({
                "record_id": f"{file_name}::{field_name}",
                "file_name": file_name,
                "customer": _customer_name(file_name),
                "table_type": _table_type(file_name),
                "field_name": field_name,
                "semantic_type": semantic_type,
                "sample_values": _samples(csv_path, field_name),
            })
    return records


def _text(record: dict[str, Any], include_samples: bool) -> str:
    readable_name = record["field_name"].replace("_", " ")
    if not include_samples:
        return readable_name
    samples = "; ".join(record["sample_values"])
    return f"field name: {readable_name}. sample values: {samples}"


def _schema_lineage(schema: dict[str, Any]) -> dict[tuple[str, str, str], str]:
    """Map each directly covered source field to its unified target field."""
    lineage: dict[tuple[str, str, str], str] = {}
    for table in schema["tables"]:
        table_type = "customer" if table["name"] == "unified_customers" else "order"
        for target in table["fields"]:
            for item in target["source_coverage"]["source_fields"]:
                if ": " not in item:
                    continue
                customer, field_name = item.split(": ", 1)
                lineage[(customer, table_type, field_name)] = target["name"]
    return lineage


def _llm_semantics(analyses: dict[str, Any]) -> dict[tuple[str, str], str]:
    return {
        (file_name, field["field_name"]): field["semantic_type"]
        for file_name, analysis in analyses.items()
        for field in analysis["fields"]
    }


def compare_embeddings(
    records: list[dict[str, Any]],
    embeddings: Any,
    *,
    threshold: float,
    schema: dict[str, Any],
    analyses: dict[str, Any],
) -> dict[str, Any]:
    """Calculate cross-customer matches, groups, and measured accuracy."""
    similarities = embeddings @ embeddings.T
    lineage = _schema_lineage(schema)
    llm_meanings = _llm_semantics(analyses)
    top_matches: list[dict[str, Any]] = []
    correct_fields = 0

    for index, record in enumerate(records):
        matches = []
        for other_customer in ("Customer A", "Customer B", "Customer C"):
            if other_customer == record["customer"]:
                continue
            candidates = [
                other_index for other_index, other in enumerate(records)
                if other["customer"] == other_customer
                and other["table_type"] == record["table_type"]
            ]
            best_index = max(candidates, key=lambda candidate: float(similarities[index, candidate]))
            best = records[best_index]
            similarity = float(similarities[index, best_index])
            matches.append({
                "customer": best["customer"],
                "file_name": best["file_name"],
                "field_name": best["field_name"],
                "semantic_type": best["semantic_type"],
                "similarity": round(similarity, 4),
                "correct": best["semantic_type"] == record["semantic_type"],
                "above_threshold": similarity >= threshold,
            })
        field_correct = all(match["correct"] for match in matches)
        correct_fields += int(field_correct)
        top_matches.append({
            "source": record,
            "matches": matches,
            "both_other_customers_correct": field_correct,
        })

    candidate_pairs: list[tuple[int, int, float]] = []
    for left in range(len(records)):
        for right in range(left + 1, len(records)):
            if records[left]["customer"] == records[right]["customer"]:
                continue
            if records[left]["table_type"] != records[right]["table_type"]:
                continue
            candidate_pairs.append((left, right, float(similarities[left, right])))

    predicted_pairs = {(left, right) for left, right, score in candidate_pairs if score >= threshold}
    expected_pairs = {
        (left, right) for left, right, _ in candidate_pairs
        if records[left]["semantic_type"] == records[right]["semantic_type"]
    }
    true_positive = len(predicted_pairs & expected_pairs)
    precision = true_positive / len(predicted_pairs) if predicted_pairs else 0.0
    recall = true_positive / len(expected_pairs) if expected_pairs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    adjacency: dict[int, set[int]] = defaultdict(set)
    for left, right in predicted_pairs:
        adjacency[left].add(right)
        adjacency[right].add(left)
    visited: set[int] = set()
    groups = []
    for start in sorted(adjacency):
        if start in visited:
            continue
        stack = [start]
        component: list[int] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)
        semantics = {records[item]["semantic_type"] for item in component}
        groups.append({
            "fields": [records[item] for item in sorted(component)],
            "semantic_types": sorted(semantics),
            "group_is_pure": len(semantics) == 1,
        })

    disagreements = []
    for result in top_matches:
        source = result["source"]
        source_key = (source["customer"], source["table_type"], source["field_name"])
        source_target = lineage.get(source_key)
        for match in result["matches"]:
            match_key = (match["customer"], source["table_type"], match["field_name"])
            match_target = lineage.get(match_key)
            if match["correct"] and (not source_target or source_target == match_target):
                continue
            disagreements.append({
                "source_field": source["field_name"],
                "source_customer": source["customer"],
                "table_type": source["table_type"],
                "expected_semantic_type": source["semantic_type"],
                "llm_semantic_type": llm_meanings.get(
                    (source["file_name"], source["field_name"]), "not_available"
                ),
                "schema_target": source_target,
                "embedding_suggestion": match["field_name"],
                "suggestion_customer": match["customer"],
                "suggestion_semantic_type": match["semantic_type"],
                "suggestion_schema_target": match_target,
                "similarity": match["similarity"],
            })

    return {
        "threshold": threshold,
        "field_accuracy": {
            "correct_fields": correct_fields,
            "total_fields": len(records),
            "accuracy": round(correct_fields / len(records), 4),
            "definition": "A field is correct only when its best match in both other customers has the same Week 1 meaning.",
        },
        "pair_grouping_quality": {
            "expected_equivalent_pairs": len(expected_pairs),
            "predicted_pairs_above_threshold": len(predicted_pairs),
            "true_positive_pairs": true_positive,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        },
        "top_matches": top_matches,
        "groups": groups,
        "disagreements_with_llm_or_schema": disagreements,
    }


def run_experiment(
    data_dir: Path,
    schema: dict[str, Any],
    analyses: dict[str, Any],
    *,
    model_name: str = MODEL_NAME,
    threshold: float = 0.60,
) -> dict[str, Any]:
    """Run name-only and name-plus-samples embedding comparisons."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError(
            "sentence-transformers is not installed. Run: pip install -r requirements.txt"
        ) from error

    records = load_field_records(data_dir)
    model = SentenceTransformer(model_name)
    approaches = {}
    for approach, include_samples in (("field_name_only", False), ("field_name_plus_samples", True)):
        texts = [_text(record, include_samples) for record in records]
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        approaches[approach] = compare_embeddings(
            records,
            embeddings,
            threshold=threshold,
            schema=schema,
            analyses=analyses,
        )

    return {
        "model": model_name,
        "training_performed": False,
        "record_count": len(records),
        "comparison_scope": "Fields are compared across customers within the same table type.",
        "approaches": approaches,
    }
