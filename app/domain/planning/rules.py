"""Task validation and established dependency normalization rules."""

from datetime import date

from app.domain.planning.records import DependencyInput, TaskValues


def normalize_dates(start_date: str, end_date: str) -> tuple[str, str]:
    """Require valid ISO dates and allow zero-duration milestones."""
    try:
        start = date.fromisoformat(start_date.strip()).isoformat()
        end = date.fromisoformat(end_date.strip()).isoformat()
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid task date. Use YYYY-MM-DD.") from exc
    if start > end:
        raise ValueError(f"Start date ({start}) cannot be after End date ({end}).")
    return start, end


def normalize_progress(progress: int) -> int:
    """Retain the established 0–100 clamp and reject nonnumeric submissions."""
    try:
        return max(0, min(100, int(progress)))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Task progress must be a number.") from exc


def normalize_task(values: TaskValues, *, task_id: int | None = None) -> TaskValues:
    """Validate task content without mutating the submitted command."""
    name = values.get("task_name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Task name cannot be empty.")
    start, end = normalize_dates(values.get("start_date", ""), values.get("end_date", ""))
    phase = values.get("phase") or "General"
    description = values.get("description") or ""
    if not isinstance(phase, str) or not isinstance(description, str):
        raise ValueError("Task phase and description must be text.")
    predecessor = values.get("predecessor_id")
    if task_id is not None and predecessor == task_id:
        predecessor = None
    return TaskValues(
        task_name=name.strip(),
        phase=phase.strip() or "General",
        start_date=start,
        end_date=end,
        progress_pct=normalize_progress(values.get("progress_pct", 0)),
        description=description.strip(),
        predecessor_id=predecessor,
    )


def normalize_dependency(task_id: int, value: DependencyInput) -> DependencyInput | None:
    """Keep existing defaults and ignore empty/self links.

    Dependency cycles remain warning data: evaluation visits each link once and
    does not recursively reschedule tasks. No new cycle prohibition is introduced.
    """
    if not isinstance(value, dict):
        raise ValueError("Invalid dependency selection.")
    predecessor = value.get("predecessor_task_id")
    if predecessor is not None:
        try:
            predecessor = int(predecessor)
        except (TypeError, ValueError, OverflowError):
            predecessor = None
        if predecessor == task_id:
            return None
    project = value.get("predecessor_project_id")
    if project is not None:
        try:
            project = int(project)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid predecessor project identity.") from exc
    if predecessor is None and project is None:
        return None
    link_type = str(value.get("link_type", "FS")).strip().upper()
    if link_type not in ("FS", "FF", "SS", "SF"):
        link_type = "FS"
    try:
        lag = int(value.get("lag_days", 0))
    except (TypeError, ValueError, OverflowError):
        lag = 0
    return DependencyInput(
        predecessor_task_id=predecessor,
        predecessor_project_id=project,
        link_type=link_type,
        lag_days=lag,
    )
