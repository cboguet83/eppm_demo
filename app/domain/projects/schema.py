"""Schema domain models for parameter groups, parameters, and options."""

from dataclasses import dataclass
from collections.abc import Iterable, Mapping, Sequence

from app.domain.projects.property_values import SUPPORTED_PROPERTY_TYPES


@dataclass
class SchemaGroup:
    """Represents a logical grouping of dynamic schema parameters.

    Attributes:
        id: Unique numeric group ID (primary key).
        group_name: Unique display name of the schema group.
        display_order: Display sequence index.
    """

    group_name: str
    display_order: int
    id: int | None = None


@dataclass
class SchemaParameter:
    """Represents a dynamic attribute definition.

    Attributes:
        param_id: Unique parameter key (e.g. 'PRM_001').
        param_name: User-facing parameter label.
        param_type: Data type ('TEXT', 'ENUM', 'MULTI_ENUM', 'TAGS', 'URL', 'DATE', 'NUMBER', 'HYPERLINK').
        group_id: Optional reference to parent SchemaGroup ID.
        mandatory: Whether this dynamic parameter is required to save a project (default False).
        alias: Optional alternative name or display alias.
        applies_to_all: Whether this property applies to current and future types.
    """

    param_id: str
    param_name: str
    param_type: str
    group_id: int | None = None
    mandatory: bool = False
    alias: str | None = None
    applies_to_all: bool = True


@dataclass
class SchemaParamOption:
    """Represents a discrete choice value for ENUM, MULTI_ENUM, or TAGS parameters.

    Attributes:
        param_id: Reference to parent parameter ID.
        option_value: The text value of the option.
        display_order: Display sequence index.
        id: Optional unique numeric option ID.
    """

    param_id: str
    option_value: str
    display_order: int = 0
    id: int | None = None


def next_group_order(orders: Iterable[int | None]) -> int:
    """Return the first unused positive display order, filling gaps first."""
    occupied = set(orders)
    candidate = 1
    while candidate in occupied:
        candidate += 1
    return candidate


def next_parameter_id(identifiers: Iterable[object]) -> str:
    """Continue the historical PRM sequence, including numeric legacy IDs.

    Unrelated or malformed identifiers do not contribute to the sequence.
    PRM identifiers retain the former parser's first numeric segment behavior.
    """
    maximum = 0
    for value in identifiers:
        if isinstance(value, int):
            maximum = max(maximum, value)
        elif isinstance(value, str) and value.startswith("PRM_"):
            try:
                maximum = max(maximum, int(value.split("_")[1]))
            except ValueError:
                continue
        elif isinstance(value, str) and value.isdigit():
            maximum = max(maximum, int(value))
    return f"PRM_{maximum + 1:03d}"


def normalize_group(group_name: str, display_order: int) -> tuple[str, int]:
    """Apply the editor's required name and positive-order rules to all callers."""
    if not group_name.strip():
        raise ValueError("Group name cannot be empty.")
    if isinstance(display_order, bool) or not isinstance(display_order, int) or display_order < 1:
        raise ValueError("Group display order must be a positive integer")
    return group_name.strip(), display_order


def normalize_parameter(parameter: SchemaParameter) -> SchemaParameter:
    """Normalize stable IDs before lookup and validate a property definition."""
    if not parameter.param_id.strip() or not parameter.param_name.strip() or parameter.param_type not in SUPPORTED_PROPERTY_TYPES:
        raise ValueError("A property needs an ID, a name, and a supported type")
    return SchemaParameter(
        parameter.param_id.strip(), parameter.param_name.strip(), parameter.param_type,
        parameter.group_id, bool(parameter.mandatory),
        parameter.alias.strip() if parameter.alias else "", parameter.applies_to_all,
    )


def normalize_option(value: str, display_order: int) -> tuple[str, int]:
    """Require nonblank choices and the editor's nonnegative display order."""
    if not value.strip():
        raise ValueError("Value cannot be empty.")
    if isinstance(display_order, bool) or not isinstance(display_order, int) or display_order < 0:
        raise ValueError("Option display order must be a nonnegative integer")
    return value.strip(), display_order


def validate_property_type_change(previous_type: str, requested_type: str, *, has_values: bool) -> None:
    """Protect all stored project values and defaults, including cleared values."""
    if previous_type != requested_type and has_values:
        raise ValueError("Clear stored values and defaults before changing the property type")


def validate_property_deletion(*, has_values: bool) -> None:
    """Require values and defaults to be cleared from storage before deletion."""
    if has_values:
        raise ValueError("This property has stored values or defaults and cannot be deleted")


def validate_option_deletion(*, is_referenced: bool) -> None:
    """Protect scalar and list selections in projects and template defaults."""
    if is_referenced:
        raise ValueError("This option is referenced by a project value or template default")


def missing_required_properties(
    values: Mapping[str, object], definitions: Sequence[Mapping[str, object]],
) -> list[str]:
    """Support legacy form validation using IDs, labels, then aliases.

    Legacy callers supply flexible row dictionaries and may supply collections
    other than lists. Persisted project values use the stricter project rules.
    """
    missing = []
    for prop in definitions:
        if not prop.get("mandatory", False):
            continue
        pid = str(prop["param_id"])
        name = str(prop.get("param_name", pid))
        alias = str(prop.get("alias") or "").strip()
        value = values.get(pid)
        if value is None:
            value = values.get(name)
        if value is None and alias:
            value = values.get(alias)
        if value is None or isinstance(value, str) and not value.strip() or isinstance(value, (list, tuple, set)) and not value:
            missing.append(name)
    return missing
