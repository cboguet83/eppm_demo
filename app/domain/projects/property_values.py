"""Validation and typed representation of dynamic project-property values."""

import datetime
import math
from collections.abc import Collection

SUPPORTED_PROPERTY_TYPES = (
    "TEXT", "ENUM", "MULTI_ENUM", "TAGS", "URL", "DATE", "NUMBER", "HYPERLINK",
)
type EncodedValue = tuple[str, str | None, int | float | None, str | None, list[str]]


def encode_property_value(
    param_id: str, param_type: str, value: object, choices: Collection[str]
) -> EncodedValue:
    """Validate an external value and describe its typed representation.

    Args:
        param_id: Stable property identifier used in validation errors.
        param_type: Declared property type.
        value: Untrusted value received from a form, import, or existing data.
        choices: Allowed selections for enumerated properties.

    Returns:
        Kind, text, number, date, and ordered selections. Null, empty text,
        and empty selections remain distinct.

    Raises:
        ValueError: The value is incompatible with its property definition.
    """
    if param_type not in SUPPORTED_PROPERTY_TYPES:
        raise ValueError(f"{param_id}: unsupported property type {param_type}")
    if value is None:
        return ("null", None, None, None, [])
    if value == "":
        return ("empty", None, None, None, [])
    if param_type in ("MULTI_ENUM", "TAGS"):
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            raise ValueError(f"{param_id}: expected a list of text values")
        if len(set(value)) != len(value):
            raise ValueError(f"{param_id}: duplicate selections")
        if param_type == "MULTI_ENUM" and any(v not in choices for v in value):
            raise ValueError(f"{param_id}: invalid selection")
        return ("list", None, None, None, list(value))
    if param_type == "NUMBER":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{param_id}: expected a finite number")
        return ("number", None, value, None, [])
    if not isinstance(value, str):
        raise ValueError(f"{param_id}: expected text")
    if param_type == "DATE":
        if datetime.date.fromisoformat(value).isoformat() != value:
            raise ValueError(f"{param_id}: expected an ISO date")
        return ("date", None, None, value, [])
    if param_type == "ENUM" and value not in choices:
        raise ValueError(f"{param_id}: invalid selection {value!r}")
    return ("text", value, None, None, [])
