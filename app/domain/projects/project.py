"""Project records and effective-template rules, independent of storage and UI."""

from dataclasses import dataclass, field

from app.domain.projects.project_types import PropertyValue, TemplateProperty
from app.domain.projects.property_values import encode_property_value

PROJECT_STATUSES = ("Draft", "In Progress", "On Hold", "Completed", "Cancelled")


@dataclass
class Project:
    """Project master data, including inactive values retained for restoration.

    Financial amounts are derived from transactions and approved WBS budgets.
    """

    id: int | None = None
    name: str = ""
    status: str = "Draft"
    dynamic_attributes: dict[str, PropertyValue] = field(default_factory=dict)
    function_id: int | None = None
    project_type_id: int = 1
    strategic_priority_id: int | None = None



def normalize_project_name(name: str) -> str:
    """Require a nonblank name and retain the established trimming behavior."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Project name is required")
    return name.strip()


def prepare_project_values(
    template: list[TemplateProperty], choices: dict[str, set[str]],
    submitted: dict[str, PropertyValue], *, creating: bool,
    existing: dict[str, PropertyValue] | None = None,
) -> dict[str, PropertyValue]:
    """Validate applicable values and apply defaults only during creation.

    Args:
        template: Effective applicability, required rules, and default values.
        choices: Allowed enum values indexed by property ID.
        submitted: Explicit input; null, empty string, and empty list clear values.
        creating: Whether creation defaults should be applied.
        existing: Previously stored values, including inactive properties.

    Returns:
        Validated active values to upsert. Inactive stored values are untouched.
    """
    allowed = {prop["param_id"] for prop in template}
    unknown = submitted.keys() - allowed
    if unknown:
        raise ValueError("Properties do not apply to this project type: " + ", ".join(sorted(unknown)))
    values = {pid: value for pid, value in (existing or {}).items() if pid in allowed}
    if creating:
        values.update({p["param_id"]: p["default_value"] for p in template if p["has_default"]})
    values.update(submitted)
    for prop in template:
        pid = prop["param_id"]
        value = values.get(pid)
        if prop["mandatory"] and (
            value is None or value == [] or isinstance(value, str) and not value.strip()
        ):
            raise ValueError(f"Required property: {prop['param_name']}")
        if pid in values:
            encode_property_value(pid, prop["param_type"], value, choices.get(pid, set()))
    return {pid: list(value) if isinstance(value, list) else value for pid, value in values.items()}
