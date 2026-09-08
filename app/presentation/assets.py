"""Resolve presentation-owned custom-component resources."""

from pathlib import Path

COMPONENT_NAMES = frozenset(
    {
        "gantt",
        "employee_table",
        "function_table",
        "function_type_table",
        "team_table",
        "tag_group_table",
        "tag_dictionary_table",
        "project_tag_table",
        "task_tag_table",
    }
)


def component_path(name: str) -> Path:
    """Resolve a known component directory without accepting arbitrary paths."""
    if name not in COMPONENT_NAMES:
        raise ValueError("Unknown presentation component.")
    return Path(__file__).parent / "assets" / "components" / name
