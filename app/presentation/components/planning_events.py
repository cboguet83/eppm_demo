"""Decode the existing Gantt JSON boundary into task-service argument types."""

from typing import Any

from app.domain.planning.project_dependencies import positive_identity


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    """Normalize component scalar fields and reject malformed collection payloads.

    Any is limited to the dynamic component JSON. Task names, dates, progress
    ranges, and dependency rules remain authoritative in application/domain code.
    """
    result = dict(event)
    if result.get('action') in {'load_project_dependencies', 'save_project_dependencies', 'log_project_event'}:
        result['project_id'] = positive_identity(result.get('project_id'))
    for field in ("id", "task_id", "project_id", "pool_id", "group_id", "progress", "progress_pct"):
        value = result.get(field)
        if field not in result or value is None and field.endswith("id") or value == "":
            continue
        try:
            result[field] = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid planning request: {field} must be a number.") from exc
    for field in ("task_name", "phase", "start_date", "end_date", "description"):
        if field not in result:
            continue
        value = result[field]
        if value is None:
            result[field] = ""
        elif not isinstance(value, str):
            raise ValueError(f"Invalid planning request: {field} must be text.")
    if "project_ids" in result and not isinstance(result["project_ids"], list):
        raise ValueError("Invalid planning request: project_ids must be a list.")
    dependencies = result.get("dependencies")
    if dependencies is not None and (
        not isinstance(dependencies, list)
        or not all(isinstance(item, dict) for item in dependencies)
    ):
        raise ValueError("Invalid dependency selection.")
    return result
