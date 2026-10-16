"""Small deterministic transformations for Week 3 sample validation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Sequence


class TransformationError(ValueError):
    """The value or transformation configuration is invalid."""


class ManualReviewRequired(TransformationError):
    """The helper cannot make a safe decision from the supplied information."""


# Fictional fixtures for demonstrations only. They are not current market rates.
# Each value means USD per one unit of the named currency.
TEST_FIXED_RATES = {"USD": Decimal("1"), "EUR": Decimal("1.10"), "IDR": Decimal("0.000065")}
MISSING = object()


def is_missing(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().casefold() in {"", "n/a", "null", "none"}
    )


def normalize_missing(value: Any, nullable: bool, field_name: str) -> Any:
    """Normalize known null markers; never fabricate a required field's value."""
    if not is_missing(value):
        return value
    if not nullable:
        raise TransformationError(f"Required target {field_name} is missing; repair the source or reject the row.")
    return None


def parse_date(
    value: Any, input_formats: Sequence[str], output_format: str = "%Y-%m-%d"
) -> str | None:
    """Try only the declared formats; flag competing interpretations."""
    if not input_formats or isinstance(input_formats, str):
        raise TransformationError("input_formats must be a non-empty list of date formats.")
    if is_missing(value):
        return None
    if not isinstance(value, str):
        raise TransformationError("Date input must be a string; quote dates in YAML.")
    matches = set()
    for date_format in input_formats:
        try:
            matches.add(datetime.strptime(value.strip(), date_format).date())
        except ValueError:
            continue
    if not matches:
        raise TransformationError(f"Date {value!r} does not match {list(input_formats)!r}.")
    if len(matches) > 1:
        raise ManualReviewRequired(f"Date {value!r} has multiple possible interpretations.")
    return matches.pop().strftime(output_format)


def split_name(
    value: Any, delimiter: str = " ", part_index: int = 0, trim: bool = True
) -> str | None:
    """Extract one of exactly two components; complex names need human review."""
    if not isinstance(delimiter, str) or not delimiter:
        raise TransformationError("Name delimiter must be a non-empty string.")
    if type(part_index) is not int or part_index not in {0, 1}:
        raise TransformationError("The simple name helper supports part_index 0 or 1.")
    if is_missing(value):
        return None
    if not isinstance(value, str):
        raise TransformationError("Name input must be a string.")
    name = value.strip() if trim else value
    parts = name.split() if delimiter == " " and trim else name.split(delimiter)
    if trim:
        parts = [part.strip() for part in parts]
    if len(parts) != 2 or any(not part for part in parts):
        raise ManualReviewRequired(
            f"Name {value!r} is not an unambiguous two-component split; keep full_name or review."
        )
    return parts[part_index]


def map_status(
    value: Any,
    value_map: Mapping[str, Any],
    case_sensitive: bool = False,
    trim_before_match: bool = True,
) -> Any:
    """Apply the explicit value map; never invent a translation."""
    if not value_map or not all(isinstance(key, str) for key in value_map):
        raise TransformationError("value_map must have non-empty, string-keyed entries.")

    def normalize(item: Any) -> str:
        result = str(item)
        if trim_before_match:
            result = result.strip()
        return result if case_sensitive else result.casefold()

    normalized = {}
    for key, mapped_value in value_map.items():
        normalized_key = normalize(key)
        if normalized_key in normalized and normalized[normalized_key] != mapped_value:
            raise TransformationError(f"Conflicting status map entries after normalization: {key!r}.")
        normalized[normalized_key] = mapped_value
    if is_missing(value):
        # Missing statuses can be mapped explicitly; otherwise policy is applied by the caller.
        key = "" if value is None else normalize(value)
    else:
        key = normalize(value)
    if key not in normalized:
        raise TransformationError(f"Status {value!r} is absent from value_map.")
    return normalized[key]


def decimal_value(value: Any) -> Decimal:
    """Read an ordinary dot-decimal amount without guessing locale conventions."""
    if isinstance(value, bool) or is_missing(value):
        raise TransformationError(f"Amount {value!r} is missing or is not numeric.")
    if "," in str(value):
        raise ManualReviewRequired("Decimal-comma amounts require an approved parsing rule.")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as error:
        raise TransformationError(f"Amount {value!r} is not a decimal number.") from error
    if not number.is_finite():
        raise TransformationError("Amount must be finite; NaN and Infinity are invalid.")
    return number


def convert_currency(
    amount: Any,
    source_currency: str,
    target_currency: str = "USD",
    rates: Mapping[str, Any] | None = None,
    rounding_decimals: int = 2,
) -> Decimal | None:
    """Convert with supplied USD-per-unit fixed rates using decimal arithmetic."""
    if type(rounding_decimals) is not int or not 0 <= rounding_decimals <= 6:
        raise TransformationError("rounding_decimals must be an integer from 0 to 6.")
    if is_missing(amount):
        # The caller must enforce the target nullable setting. Missing is never zero.
        return None
    if not isinstance(source_currency, str) or not isinstance(target_currency, str):
        raise TransformationError("Currency codes must be strings.")
    source = source_currency.strip().upper()
    target = target_currency.strip().upper()
    if len(source) != 3 or len(target) != 3 or not source.isalpha() or not target.isalpha():
        raise TransformationError("Currency codes must have three letters.")
    number = decimal_value(amount)
    if source != target:
        if rates is None or source not in rates or target not in rates:
            raise ManualReviewRequired(f"No supplied fixed rate for {source} to {target}.")
        source_rate = decimal_value(rates[source])
        target_rate = decimal_value(rates[target])
        if source_rate <= 0 or target_rate <= 0:
            raise TransformationError("Exchange rates must be positive.")
        number = number * source_rate / target_rate
    try:
        return number.quantize(Decimal(1).scaleb(-rounding_decimals), rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise TransformationError("Amount exceeds the helper's supported decimal precision.") from error


def default_value(value: Any, apply_when: str, source_value: Any = MISSING) -> Any:
    """Apply a scalar default only when its explicit condition is satisfied."""
    if value is not None and type(value) not in {str, int, float, bool}:
        raise TransformationError("default_value must be a scalar or null, not an object or list.")
    if apply_when not in {"always", "source_missing", "source_null"}:
        raise TransformationError(f"Unsupported default condition: {apply_when!r}.")
    if apply_when == "always" or (apply_when == "source_missing" and source_value is MISSING):
        return value
    if source_value is MISSING:
        raise ManualReviewRequired("source_null has no source value to inspect in this source-free rule.")
    return value if apply_when == "source_null" and is_missing(source_value) else source_value
