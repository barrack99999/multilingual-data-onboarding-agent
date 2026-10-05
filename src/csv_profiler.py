"""Profile CSV fields with deterministic Python code and no LLM calls."""

from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


NULL_MARKERS = {"", "n/a", "na", "null", "none", "nan", "missing"}

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
)

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")

DATE_NAME_HINTS = ("date", "_dt", "datum", "tgl")
EMAIL_NAME_HINTS = ("email", "e_mail")
AMOUNT_NAME_HINTS = ("amount", "amt", "total", "price", "harga", "betrag")
STATUS_NAME_HINTS = ("status",)
TEXT_NAME_HINTS = ("id", "number", "nummer", "phone", "telefon", "no_hp")

STATUS_VALUES = {
    "active", "inactive", "pending", "complete", "completed", "cancelled",
    "canceled", "paid", "shipped", "open", "closed", "dibayar", "dikirim",
    "dibatalkan", "menunggu", "bez", "vers", "stor", "off",
}


def is_null(value: str | None) -> bool:
    """Return True for blank cells and common text placeholders for missing data."""
    return value is None or value.strip().lower() in NULL_MARKERS


def _is_date(value: str) -> bool:
    for date_format in DATE_FORMATS:
        try:
            datetime.strptime(value.strip(), date_format)
            return True
        except ValueError:
            continue
    return False


def _number_value(value: str) -> float | None:
    """Parse common U.S. and European number formats for detection only."""
    cleaned = re.sub(r"[$€£¥]|\b(?:USD|EUR|IDR)\b", "", value, flags=re.IGNORECASE)
    cleaned = cleaned.strip().replace(" ", "")
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        if re.search(r",\d{1,2}$", cleaned):
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def _ratio(values: list[str], check: Any) -> float:
    if not values:
        return 0.0
    return sum(bool(check(value)) for value in values) / len(values)


def _infer_type(field_name: str, values: list[str]) -> str:
    """Infer a practical field type from non-null values."""
    if not values:
        return "unknown"

    lowered_name = field_name.lower()
    if any(hint in lowered_name for hint in TEXT_NAME_HINTS):
        return "string"

    date_ratio = _ratio(values, _is_date)
    if date_ratio >= 0.70:
        return "date"

    lowered_values = [value.strip().lower() for value in values]
    if all(value in {"true", "false", "yes", "no", "y", "n"} for value in lowered_values):
        return "boolean"

    if all(INTEGER_PATTERN.fullmatch(value.strip()) for value in values):
        return "integer"

    if _ratio(values, lambda value: _number_value(value) is not None) >= 0.90:
        return "number"

    return "string"


def _looks_like_status(field_name: str, values: list[str]) -> bool:
    lowered_name = field_name.lower()
    if any(hint in lowered_name for hint in STATUS_NAME_HINTS):
        return True
    if not values:
        return False
    normalized = {value.strip().lower() for value in values}
    return len(normalized) <= 20 and normalized.issubset(STATUS_VALUES)


def profile_csv(
    file_path: str | Path,
    *,
    sample_size: int = 5,
    top_n: int = 5,
) -> dict[str, Any]:
    """Return file-level facts and one compact summary for each CSV field."""
    path = Path(file_path).expanduser()
    if path.suffix.lower() != ".csv":
        raise ValueError("The input file must have a .csv extension.")
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")
    if sample_size < 1 or top_n < 1:
        raise ValueError("sample_size and top_n must be at least 1.")

    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError("The CSV must contain a header row.")
        rows = [dict(row) for row in reader]

    row_count = len(rows)
    duplicate_row_count = row_count - len({tuple(row.items()) for row in rows})
    fields = []

    for field_name in reader.fieldnames:
        raw_values = [row.get(field_name, "") or "" for row in rows]
        non_null_values = [value.strip() for value in raw_values if not is_null(value)]
        value_counts = Counter(non_null_values)

        sample_values = list(dict.fromkeys(non_null_values))[:sample_size]
        top_values = [
            {"value": value, "count": count}
            for value, count in value_counts.most_common(top_n)
        ]
        null_count = row_count - len(non_null_values)
        lowered_name = field_name.lower()
        date_ratio = _ratio(non_null_values, _is_date)
        email_ratio = _ratio(non_null_values, lambda value: EMAIL_PATTERN.fullmatch(value) is not None)

        fields.append(
            {
                "field_name": field_name,
                "inferred_type": _infer_type(field_name, non_null_values),
                "sample_values": sample_values,
                "null_count": null_count,
                "null_rate": round(null_count / row_count, 4) if row_count else 0.0,
                "unique_count": len(value_counts),
                "top_values": top_values,
                "patterns": {
                    "looks_like_date": (
                        any(hint in lowered_name for hint in DATE_NAME_HINTS)
                        or date_ratio >= 0.60
                    ),
                    "looks_like_email": (
                        any(hint in lowered_name for hint in EMAIL_NAME_HINTS)
                        or email_ratio >= 0.60
                    ),
                    "looks_like_amount": any(
                        hint in lowered_name for hint in AMOUNT_NAME_HINTS
                    ),
                    "looks_like_status": _looks_like_status(field_name, non_null_values),
                },
            }
        )

    return {
        "file_name": path.name,
        "row_count": row_count,
        "column_count": len(reader.fieldnames),
        "duplicate_row_count": duplicate_row_count,
        "fields": fields,
    }
