"""Project-type invariants and effective templates without persistence or UI."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypedDict

type PropertyValue = str | int | float | list[str] | None


@dataclass(frozen=True)
class ProjectType:
    """A named project template; General is the protected built-in type."""

    id: int
    name: str
    description: str
    is_general: bool


@dataclass(frozen=True)
class PropertyApplicability:
    """Whether a property applies to all types or specific type IDs."""

    applies_to_all: bool
    type_ids: tuple[int, ...]


class PropertyDefinition(TypedDict):
    """The business fields required to resolve a custom-property template."""

    param_id: str
    group_id: int | None
    param_name: str
    param_type: str
    mandatory: bool | int
    alias: str | None
    applies_to_all: bool | int


class TemplateProperty(PropertyDefinition):
    """A property with effective required/default settings for one type."""

    mandatory_override: bool | int | None
    has_default: bool
    default_value: PropertyValue


def normalize_details(name: str, description: str) -> tuple[str, str]:
    """Validate the required name and trim user-entered details."""
    if not name.strip():
        raise ValueError("Project type name is required")
    return name.strip(), description.strip()


def validate_rename(project_type: ProjectType, requested_name: str) -> None:
    """Preserve the exact historical name of the built-in General type."""
    if project_type.is_general and requested_name != "General":
        raise ValueError("The General type cannot be renamed")


def validate_deletion(
    project_type: ProjectType | None,
    *,
    has_projects: bool,
    has_exclusive_properties: bool,
) -> None:
    """Protect General, assigned projects, and selected-only properties."""
    if project_type is not None and project_type.is_general:
        raise ValueError("The General type cannot be deleted")
    if has_projects:
        raise ValueError("Reassign this type's projects before deleting it")
    if has_exclusive_properties:
        raise ValueError("Assign this type's exclusive properties to another type first")


def make_applicability(
    applies_to_all: bool, type_ids: Sequence[int]
) -> PropertyApplicability:
    """Validate selected scope and normalize its membership before saving."""
    if not applies_to_all and not type_ids:
        raise ValueError("Select at least one project type")
    return PropertyApplicability(
        applies_to_all,
        () if applies_to_all else tuple(sorted(set(type_ids))),
    )


def resolve_template(
    definitions: Sequence[PropertyDefinition],
    selected_properties: set[str],
    overrides: Mapping[str, bool | int | None],
    defaults: Mapping[str, PropertyValue],
) -> list[TemplateProperty]:
    """Resolve applicability, required overrides, and explicit empty defaults.

    Args:
        definitions: Ordered property definitions shared by project types.
        selected_properties: Properties explicitly assigned to the type.
        overrides: Optional required overrides keyed by property ID.
        defaults: Present defaults, including explicit null/empty values.

    Returns:
        New records; input definitions and default lists are not mutated.
    """
    result: list[TemplateProperty] = []
    for definition in definitions:
        pid = definition["param_id"]
        if not definition["applies_to_all"] and pid not in selected_properties:
            continue
        override = overrides.get(pid)
        default = defaults.get(pid)
        result.append({
            **definition,
            "mandatory_override": override,
            "mandatory": bool(definition["mandatory"] if override is None else override),
            "has_default": pid in defaults,
            "default_value": list(default) if isinstance(default, list) else default,
        })
    return result
