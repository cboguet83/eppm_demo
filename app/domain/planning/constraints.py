"""Single-pass evaluation of existing FS, FF, SS, and SF scheduling constraints."""

from collections.abc import Sequence
from datetime import date, timedelta

from app.domain.planning.records import (
    DependencySchedule,
    EvaluatedDependency,
    ProjectBounds,
    TaskSchedule,
)


def _dates(start: str | None, end: str | None) -> tuple[date, date] | None:
    try:
        return (date.fromisoformat(str(start).split()[0]), date.fromisoformat(str(end).split()[0]))
    except (ValueError, IndexError):
        # Incomplete historical schedules cannot establish a constraint date.
        return None


def _predecessor(
    dependency: DependencySchedule,
    tasks: dict[int, TaskSchedule],
    bounds: ProjectBounds,
) -> tuple[str | None, str | None, str]:
    task_id = dependency.get("predecessor_task_id")
    project_id = dependency.get("predecessor_project_id")
    if task_id is not None and int(task_id) in tasks:
        task = tasks[int(task_id)]
        return (
            str(task.get("start_date", "")),
            str(task.get("end_date", "")),
            str(task.get("task_name", f"Step #{task_id}")),
        )
    if task_id is not None:
        project = dependency.get("predecessor_project_name") or project_id or "Ext"
        task_name = dependency.get("predecessor_task_name") or f"Step #{task_id}"
        return (
            dependency.get("pred_start_date"),
            dependency.get("pred_end_date"),
            f"{project} > {task_name}",
        )
    if project_id is not None:
        start, end = bounds.get(str(project_id), bounds.get(project_id, (None, None)))
        return start, end, f"Project [{dependency.get('predecessor_project_name') or project_id}]"
    return None, None, "Predecessor"


def evaluate_constraints(
    tasks: Sequence[TaskSchedule],
    dependencies: Sequence[DependencySchedule],
    project_bounds: ProjectBounds | None = None,
) -> tuple[list[EvaluatedDependency], dict[int, list[str]]]:
    """Annotate incoming links without mutating tasks or recursively scheduling.

    FS/SS constrain successor start; FF/SF constrain successor end. Lag is in
    calendar days. Unknown dates leave the link unviolated, as in the original
    planner. This evaluates cycles in bounded time because each link is visited once.
    """
    by_id = {int(task["id"]): task for task in tasks if "id" in task}
    dates = {
        key: _dates(task.get("start_date"), task.get("end_date")) for key, task in by_id.items()
    }
    violations: dict[int, list[str]] = {key: [] for key in by_id}
    evaluated: list[EvaluatedDependency] = []
    for dependency in dependencies:
        task_id = dependency.get("task_id")
        if task_id is None or int(task_id) not in by_id:
            continue
        task_id = int(task_id)
        successor_dates = dates[task_id]
        if successor_dates is None:
            continue
        start, end, label = _predecessor(dependency, by_id, project_bounds or {})
        predecessor_dates = _dates(start, end)
        result: EvaluatedDependency = {**dependency, "is_violated": False, "violation_text": None}
        if predecessor_dates is None:
            evaluated.append(result)
            continue
        link_type = str(dependency.get("link_type", "FS")).upper()
        lag = int(dependency.get("lag_days", 0))
        result.update(pred_start=start, pred_end=end, pred_label=label)
        if link_type in ("FS", "FF", "SS", "SF"):
            target = predecessor_dates[0 if link_type in ("SS", "SF") else 1] + timedelta(days=lag)
            finish = link_type in ("FF", "SF")
            actual = successor_dates[1 if finish else 0]
            if actual < target:
                actual_text = str(by_id[task_id]["end_date" if finish else "start_date"])
                message = (
                    f"{link_type} with '{label}' ({lag:+d}d offset): "
                    f"{'End' if finish else 'Start'} must be ≥ {target.isoformat()} "
                    f"(actual: {actual_text})"
                )
                result.update(is_violated=True, violation_text=message)
                violations[task_id].append(message)
        evaluated.append(result)
    return evaluated, violations
