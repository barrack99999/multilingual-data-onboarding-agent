"""Recommend unified customer and order schemas from field-analysis JSON.

The recommendation is deliberately deterministic: field analysis uses the LLM,
while schema policy is ordinary Python so the same inputs always produce the
same MVP design.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceCoverage(BaseModel):
    """Where a proposed unified field comes from."""

    sources: list[Literal["Customer A", "Customer B", "Customer C"]]
    source_fields: list[str]
    coverage_note: str


class SchemaField(BaseModel):
    """One proposed field in a unified table."""

    name: str
    type: str
    nullable: bool
    description: str
    source_coverage: SourceCoverage
    rationale: str


class UnifiedTable(BaseModel):
    """One unified table recommendation."""

    name: Literal["unified_customers", "unified_orders"]
    grain: str
    primary_key: str
    fields: list[SchemaField] = Field(min_length=1)


class Decision(BaseModel):
    """One explicit data-modeling decision."""

    decision: str
    rationale: str


class ModelingDecisions(BaseModel):
    """The four decisions required by Task 4."""

    table_separation: Decision
    name_strategy: Decision
    amount_strategy: Decision
    status_strategy: Decision


class UnifiedSchemaRecommendation(BaseModel):
    """Complete schema recommendation."""

    schema_version: str
    modeling_decisions: ModelingDecisions
    tables: list[UnifiedTable] = Field(min_length=2, max_length=2)


SOURCE_NAMES = {
    "customer_a_": "Customer A",
    "customer_b_": "Customer B",
    "customer_c_": "Customer C",
}


def _source_name(file_name: str) -> str | None:
    lowered = file_name.lower()
    return next(
        (label for prefix, label in SOURCE_NAMES.items() if lowered.startswith(prefix)),
        None,
    )


def _coverage(
    analyses: dict[str, Any], table_type: str, semantic_type: str
) -> SourceCoverage:
    """Find which customers supply a semantic field and preserve source names."""
    pairs: list[tuple[str, str]] = []
    for file_name, analysis in analyses.items():
        if analysis.get("table_type") != table_type:
            continue
        source = _source_name(file_name)
        if source is None:
            continue
        for field in analysis.get("fields", []):
            if field.get("semantic_type") == semantic_type:
                pairs.append((source, field["field_name"]))

    ordered_sources = [
        source
        for source in ("Customer A", "Customer B", "Customer C")
        if any(pair[0] == source for pair in pairs)
    ]
    source_fields = [f"{source}: {field}" for source, field in pairs]
    return SourceCoverage(
        sources=ordered_sources,
        source_fields=source_fields,
        coverage_note=(
            f"Directly supplied by {', '.join(ordered_sources)}."
            if ordered_sources
            else "No direct source field was reliably identified."
        ),
    )


def _derived_coverage(note: str) -> SourceCoverage:
    return SourceCoverage(
        sources=["Customer A", "Customer B", "Customer C"],
        source_fields=[],
        coverage_note=note,
    )


def _field(
    name: str,
    data_type: str,
    nullable: bool,
    description: str,
    coverage: SourceCoverage,
    rationale: str,
) -> SchemaField:
    return SchemaField(
        name=name,
        type=data_type,
        nullable=nullable,
        description=description,
        source_coverage=coverage,
        rationale=rationale,
    )


def _field_names(table: dict[str, Any]) -> set[str]:
    return {field["name"] for field in table["fields"]}


def _find_field(table: dict[str, Any], name: str) -> dict[str, Any]:
    """Return one field definition, or an empty dictionary when absent."""
    return next(
        (field for field in table["fields"] if field["name"] == name),
        {},
    )


def validate_recommendation(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic checks for required Task 4 design decisions."""
    tables = {table["name"]: table for table in result["tables"]}
    customers = tables.get("unified_customers")
    orders = tables.get("unified_orders")
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": passed, "detail": detail})

    add(
        "separate_customer_and_order_tables",
        customers is not None and orders is not None and len(tables) == 2,
        "Recommendation must contain exactly unified_customers and unified_orders.",
    )
    if not customers or not orders:
        return checks

    customer_fields = _field_names(customers)
    order_fields = _field_names(orders)
    required_customer_fields = {
        "unified_customer_id", "source_system", "source_customer_id", "full_name",
        "email", "phone", "signup_date", "customer_segment", "loyalty_tier",
    }
    required_order_fields = {
        "unified_order_id", "unified_customer_id", "source_system",
        "source_order_id", "source_customer_id", "order_date",
        "amount_original", "currency_code", "amount_usd", "status_raw",
        "order_status",
    }
    add(
        "required_customer_fields",
        required_customer_fields.issubset(customer_fields),
        f"Missing: {sorted(required_customer_fields - customer_fields)}",
    )
    add(
        "required_order_fields",
        required_order_fields.issubset(order_fields),
        f"Missing: {sorted(required_order_fields - order_fields)}",
    )
    add(
        "keep_full_name_unsplit",
        "full_name" in customer_fields
        and "first_name" not in customer_fields
        and "last_name" not in customer_fields,
        "MVP keeps culturally flexible full_name without unreliable splitting.",
    )
    customer_only_fields = {
        "full_name", "email", "phone", "signup_date", "customer_segment",
        "loyalty_tier",
    }
    add(
        "no_customer_attributes_in_orders",
        not customer_only_fields.intersection(order_fields),
        "Customer descriptive attributes must remain in unified_customers.",
    )

    all_fields = {
        field["name"]: field
        for table in result["tables"]
        for field in table["fields"]
    }
    add(
        "phone_nullable",
        all_fields.get("phone", {}).get("nullable") is True,
        "Phone must be nullable because sources contain missing numbers.",
    )
    add(
        "order_customer_link_settings",
        _find_field(orders, "unified_customer_id").get("nullable") is True
        and _find_field(orders, "source_customer_id").get("nullable") is False,
        "The source customer ID is required; the resolved unified link may be unavailable during matching.",
    )
    add(
        "source_system_required",
        all(
            _find_field(table, "source_system").get("nullable") is False
            for table in result["tables"]
        ),
        "source_system must be required in both tables.",
    )
    amount_usd = all_fields.get("amount_usd", {})
    add(
        "amount_usd_calculated_and_nullable",
        amount_usd.get("nullable") is True
        and "calculat" in amount_usd.get("rationale", "").lower(),
        "amount_usd must be a nullable calculated field.",
    )
    order_status = all_fields.get("order_status", {})
    add(
        "controlled_status_enum",
        "enum" in order_status.get("type", "").lower() and "status_raw" in order_fields,
        "Canonical enum and raw source status must both be retained.",
    )
    add(
        "field_metadata_complete",
        all(
            field.get("type")
            and field.get("description")
            and field.get("rationale")
            and field.get("source_coverage", {}).get("coverage_note")
            for table in result["tables"]
            for field in table["fields"]
        ),
        "Every field needs type, nullability, description, coverage, and rationale.",
    )
    full_coverage_fields = {
        "source_customer_id": customers,
        "full_name": customers,
        "email": customers,
        "phone": customers,
        "signup_date": customers,
        "source_order_id": orders,
        "order_date": orders,
        "amount_original": orders,
        "currency_code": orders,
        "status_raw": orders,
    }
    expected_sources = {"Customer A", "Customer B", "Customer C"}
    add(
        "core_source_coverage_complete",
        all(
            set(_find_field(table, field_name).get("source_coverage", {}).get("sources", []))
            == expected_sources
            for field_name, table in full_coverage_fields.items()
        ),
        "Core concepts must have direct coverage from Customers A, B, and C.",
    )
    return checks


def recommend_schema(field_analyses: dict[str, Any]) -> dict[str, Any]:
    """Build and validate the Week 2 MVP unified schema locally."""
    if not field_analyses:
        raise ValueError("At least one field-analysis result is required.")

    customers = UnifiedTable(
        name="unified_customers",
        grain="One row per customer within a source system.",
        primary_key="unified_customer_id",
        fields=[
            _field(
                "unified_customer_id", "string", False,
                "Generated identifier for a customer in the unified model.",
                _derived_coverage("Generated during onboarding for every customer source."),
                "A generated key avoids collisions when different systems reuse the same customer ID.",
            ),
            _field(
                "source_system", "string", False,
                "System or customer dataset from which the record originated.",
                _derived_coverage("Assigned during ingestion for Customers A, B, and C."),
                "Required for provenance and to make source identifiers unambiguous.",
            ),
            _field(
                "source_customer_id", "string", False,
                "Customer identifier exactly as represented by the source.",
                _coverage(field_analyses, "customer", "customer_id"),
                "Preserves the source key for traceability and joins back to source data.",
            ),
            _field(
                "full_name", "string", True,
                "Customer's complete name in the source-provided form.",
                _coverage(field_analyses, "customer", "full_name"),
                "Kept as one field because reliably splitting names is difficult across cultures and languages.",
            ),
            _field(
                "email", "string", True,
                "Customer email address.",
                _coverage(field_analyses, "customer", "email"),
                "Nullable because source records may omit an email or contain an unusable value.",
            ),
            _field(
                "phone", "string", True,
                "Customer phone number, retaining the cleaned international representation when available.",
                _coverage(field_analyses, "customer", "phone"),
                "Nullable because phone values are missing in some source records and formats vary.",
            ),
            _field(
                "signup_date", "date", True,
                "Date on which the customer registered with the source system.",
                _coverage(field_analyses, "customer", "signup_date"),
                "Nullable because the original examples contain an invalid signup date that cannot be converted safely.",
            ),
            _field(
                "customer_segment", "string", True,
                "Source-defined customer segment or group.",
                _coverage(field_analyses, "customer", "customer_segment"),
                "Nullable because this concept is not supplied by every customer source.",
            ),
            _field(
                "loyalty_tier", "string", True,
                "Customer loyalty-program tier.",
                _coverage(field_analyses, "customer", "loyalty_tier"),
                "Nullable because only sources with a loyalty program provide it.",
            ),
        ],
    )
    orders = UnifiedTable(
        name="unified_orders",
        grain="One row per order within a source system.",
        primary_key="unified_order_id",
        fields=[
            _field(
                "unified_order_id", "string", False,
                "Generated identifier for an order in the unified model.",
                _derived_coverage("Generated during onboarding for every order source."),
                "A generated key prevents collisions between source order identifiers.",
            ),
            _field(
                "source_system", "string", False,
                "System or customer dataset from which the order originated.",
                _derived_coverage("Assigned during ingestion for Customers A, B, and C."),
                "Required for provenance and to make source identifiers unambiguous.",
            ),
            _field(
                "source_order_id", "string", False,
                "Order identifier exactly as represented by the source.",
                _coverage(field_analyses, "order", "order_id"),
                "Preserves the source key for reconciliation and traceability.",
            ),
            _field(
                "unified_customer_id", "string", True,
                "Resolved link to the matching row in unified_customers.",
                _derived_coverage("Derived by matching source_system and source_customer_id to unified_customers."),
                "Nullable until source_system and source_customer_id successfully resolve to a unified customer.",
            ),
            _field(
                "source_customer_id", "string", False,
                "Source customer identifier associated with the order.",
                _coverage(field_analyses, "order", "customer_id"),
                "Required because every order in the original examples supplies this relationship key.",
            ),
            _field(
                "order_date", "date", True,
                "Date on which the order was placed.",
                _coverage(field_analyses, "order", "order_date"),
                "Nullable because invalid or missing source dates cannot always be converted safely.",
            ),
            _field(
                "amount_original", "decimal(18,2)", True,
                "Order amount in its original transaction currency.",
                _coverage(field_analyses, "order", "amount"),
                "Preserves the authoritative source amount; nullable when a value is missing or invalid.",
            ),
            _field(
                "currency_code", "string(3)", True,
                "ISO-style currency code for amount_original.",
                _coverage(field_analyses, "order", "currency"),
                "Conditionally required whenever amount_original is present; nullable only when the amount is absent or unusable.",
            ),
            _field(
                "amount_usd", "decimal(18,2)", True,
                "Order amount converted to US dollars.",
                _derived_coverage("Calculated from amount_original, currency_code, order_date, and an exchange-rate source."),
                "A calculated field supports comparison, but remains nullable until a dated exchange rate is available.",
            ),
            _field(
                "status_raw", "string", True,
                "Unchanged order status supplied by the source.",
                _coverage(field_analyses, "order", "order_status"),
                "Preserves the original value for auditing and future mapping corrections.",
            ),
            _field(
                "order_status", "enum(pending, paid, shipped, cancelled, unknown)", False,
                "Normalized order status used consistently across all sources.",
                _derived_coverage("Derived from each source's raw order-status field."),
                "A controlled enum supports reliable reporting; unknown safely captures unmapped values.",
            ),
        ],
    )
    recommendation = UnifiedSchemaRecommendation(
        schema_version="1.1",
        modeling_decisions=ModelingDecisions(
            table_separation=Decision(
                decision="Use separate unified_customers and unified_orders tables.",
                rationale="A customer can have many orders, so separate tables avoid repeating customer attributes on every order.",
            ),
            name_strategy=Decision(
                decision="Keep full_name; do not split first_name and last_name in the MVP.",
                rationale="Name structures differ across languages and cultures, and the sources do not provide reliable components.",
            ),
            amount_strategy=Decision(
                decision="Keep amount_original and currency_code, and calculate nullable amount_usd.",
                rationale="The original value remains auditable while a common USD amount enables comparison when a dated exchange rate exists.",
            ),
            status_strategy=Decision(
                decision="Keep status_raw and map it to a controlled order_status enum.",
                rationale="Canonical values support analytics, while the raw value preserves evidence for review and remapping.",
            ),
        ),
        tables=[customers, orders],
    )
    result = recommendation.model_dump()
    checks = validate_recommendation(result)
    failed = [check for check in checks if not check["passed"]]
    if failed:
        raise ValueError(f"Schema recommendation failed validation: {failed}")
    return result
