"""LLM-backed semantic field analysis using a compact CSV profile."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from openai import DefaultHttpxClient, OpenAI
from pydantic import BaseModel, Field


SemanticType = Literal[
    "customer_id",
    "order_id",
    "full_name",
    "email",
    "phone",
    "signup_date",
    "order_date",
    "customer_segment",
    "loyalty_tier",
    "amount",
    "currency",
    "order_status",
    "unknown",
]


class EvidenceItem(BaseModel):
    """One traceable reason supporting a semantic judgment."""

    source: Literal["field_name", "sample_values", "profile_statistics"]
    detail: str


class FieldAnalysis(BaseModel):
    """Structured semantic judgment for one source field."""

    field_name: str
    semantic_type: SemanticType
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = Field(min_length=2)


class FieldAnalysisResult(BaseModel):
    """Structured result for one CSV file."""

    file_name: str
    table_type: Literal["customer", "order", "unknown"]
    table_confidence: float = Field(ge=0.0, le=1.0)
    fields: list[FieldAnalysis]


SYSTEM_PROMPT = """You are a data-onboarding FieldAnalyzer.

Infer the business meaning of every source field from the supplied CSV profile.

Common language and abbreviation hints:
- English: cust=customer, dt=date, amt=amount, no/num=number.
- Indonesian: pelanggan=customer, nama_lengkap=full name, no_hp=mobile phone,
  tgl or tanggal=date, daftar=register/signup, pesanan=order, harga=price/amount,
  mata_uang=currency, segmen=segment, status_pesanan=order status.
- German/SAP: Kunde=customer, Kundennummer=customer number, Name1=name,
  EMail=email, Telefon=phone, Erfassungsdatum=creation/registration date,
  Kundengruppe=customer group, Bestellung=order, Bestellnummer=order number,
  Bestelldatum=order date, Betrag=amount, Währung=currency,
  StatusCode=order status.

Treat these hints as clues, not automatic answers. Confirm them against values.

Rules:
1. Use BOTH the original field name and sample values as evidence.
2. Also use inferred types, null rates, unique counts, top values, and pattern flags.
3. Consider abbreviations and multilingual names, including English, Indonesian, and German.
4. Do not rely only on the field name and do not invent unsupported facts.
5. Analyze every field exactly once and preserve the original field order.
6. Use unknown when a reasonable semantic type cannot be determined.
7. Return lower confidence when evidence is weak, conflicting, or ambiguous.
8. Confidence guidance: 0.90-1.00 very strong; 0.70-0.89 likely;
   0.40-0.69 uncertain; 0.00-0.39 weak or unknown.
9. Evidence must contain at least one item with source=field_name and at least
   one item with source=sample_values. Cite actual sample values in the latter.
10. Label every evidence item with field_name, sample_values, or
    profile_statistics so its origin is explicit.
11. Return the required structured result only.
"""


def analyze_fields(
    csv_path: str | Path,
    profile: dict[str, Any],
    *,
    client: OpenAI | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Analyze one CSV profile and return validated structured JSON data."""
    path = Path(csv_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")
    if path.suffix.lower() != ".csv":
        raise ValueError("The input file must have a .csv extension.")

    profile_fields = profile.get("fields")
    if not isinstance(profile_fields, list) or not profile_fields:
        raise ValueError("The profiling result must contain a non-empty fields list.")

    expected_names = [field.get("field_name") for field in profile_fields]
    if any(not name for name in expected_names):
        raise ValueError("Every profiled field must contain field_name.")

    api_client = client or OpenAI(
        http_client=DefaultHttpxClient(trust_env=False),
    )
    selected_model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    user_prompt = (
        f"Analyze this CSV profile.\n\nCSV file name: {path.name}\n\n"
        f"Profiling result:\n{json.dumps(profile, ensure_ascii=False, indent=2)}"
    )

    response = api_client.responses.parse(
        model=selected_model,
        instructions=SYSTEM_PROMPT,
        input=user_prompt,
        text_format=FieldAnalysisResult,
        temperature=0,
        store=False,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("The model did not return a parsed FieldAnalyzer result.")

    result = parsed.model_dump()
    actual_names = [field["field_name"] for field in result["fields"]]
    if actual_names != expected_names:
        raise ValueError(
            "The model did not return every field exactly once in source order. "
            f"Expected {expected_names}; received {actual_names}."
        )
    if result["file_name"] != path.name:
        raise ValueError(
            f"The model returned file_name={result['file_name']!r}; expected {path.name!r}."
        )
    return result
