"""Editable project CSV templates with numbered dependency references."""

import csv
from dataclasses import dataclass
from datetime import datetime
import io

from app.domain.planning.records import DependencySchedule, TaskValues
from app.domain.planning.rules import normalize_task


@dataclass(frozen=True)
class TemplateDependency:
    """Reference a template step, external task, or whole project."""

    kind: str
    identity: int
    link_type: str = "FS"
    lag_days: int = 0


@dataclass(frozen=True)
class TemplateStep:
    """Validated task values and references independent of database task IDs."""

    number: int
    values: TaskValues
    dependencies: tuple[TemplateDependency, ...]


def _positive_integer(value: str, label: str) -> int:
    try:
        number = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label} must be a positive integer.") from exc
    if not 1 <= number <= 9223372036854775807:
        raise ValueError(f"{label} must be a positive 64-bit integer.")
    return number


def _dependencies(row: dict[str, str]) -> tuple[TemplateDependency, ...]:
    """Match semicolon-separated predecessors, types and lags by their position."""
    references = (row.get("preceding_step") or "").strip()
    types = (row.get("dependency_type") or "").strip()
    lags = (row.get("dependency_lag") or "").strip()
    if not references and not types and not lags:
        return ()
    columns = [[value.strip() for value in column.split(";")] for column in (references, types, lags)]
    if len({len(column) for column in columns}) != 1 or any(not value for column in columns for value in column):
        raise ValueError("Preceding step, dependency type and dependency lag must contain the same number of nonempty semicolon-separated values.")
    result = []
    for reference, link_type, lag_text in zip(*columns):
        parts = reference.split(":") if ":" in reference else ["step", reference]
        if len(parts) != 2 or parts[0] not in {"step", "task", "project"}:
            raise ValueError("Preceding step must be a step number, task:123, or project:4.")
        if link_type not in {"FS", "SS", "FF", "SF"}:
            raise ValueError("Dependency type must be FS, SS, FF, or SF.")
        identity = _positive_integer(parts[1], "Dependency reference")
        try:
            lag = int(lag_text)
        except ValueError as exc:
            raise ValueError("Dependency lag must be an integer number of days.") from exc
        if not -9223372036854775808 <= lag <= 9223372036854775807:
            raise ValueError("Dependency lag is outside the supported integer range.")
        dependency = TemplateDependency(parts[0], identity, link_type, lag)
        if dependency in result:
            raise ValueError("Duplicate dependency.")
        result.append(dependency)
    return tuple(result)


def _template_date(value: str, column: str, date_format: str) -> str:
    """Normalize an explicitly selected CSV date format to stored ISO dates."""
    formats = {"YYYY-MM-DD": "%Y-%m-%d", "DD/MM/YYYY": "%d/%m/%Y", "MM/DD/YYYY": "%m/%d/%Y"}
    value = value.strip()
    parts = value.split('/')
    if date_format != 'YYYY-MM-DD' and len(parts) == 3 and len(parts[2]) == 2 and parts[2].isdigit():
        value = '/'.join([*parts[:2], '20' + parts[2]])
    # Exported ISO dates remain valid even when only some cells were reformatted.
    for pattern in dict.fromkeys(("%Y-%m-%d", formats[date_format])):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError(
        f"Invalid {column}: {value!r}. Expected YYYY-MM-DD"
        + (f" or {date_format}." if date_format != "YYYY-MM-DD" else ".")
        + " Select the date format used in the CSV import panel."
    )


def _parse_step(row: dict[str, str], line: int, date_format: str) -> TemplateStep:
    try:
        number = _positive_integer(row.get("step_number", ""), "Step number")
        progress = int(row.get("progress_pct") or "0")
        if not 0 <= progress <= 100:
            raise ValueError("Progress must be between 0 and 100.")
        values = normalize_task(TaskValues(
            task_name=row.get("task_name") or "",
            start_date=_template_date(row.get("start_date") or "", "start_date", date_format),
            end_date=_template_date(row.get("end_date") or "", "end_date", date_format),
            phase=row.get("phase") or "General",
            description=row.get("description") or "",
            progress_pct=progress,
        ))
        dependencies = _dependencies(row)
        return TemplateStep(number, values, dependencies)
    except ValueError as exc:
        raise ValueError(f"Row {line}: {exc}") from exc


def parse_template(content: str, *, date_format: str = "YYYY-MM-DD") -> list[TemplateStep]:
    """Validate every cell and local reference before any database writes."""
    if date_format not in {"YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"}:
        raise ValueError("Unsupported CSV date format.")
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
    try:
        fields = reader.fieldnames or []
        required = {"step_number", "task_name", "start_date", "end_date"}
        if missing := required - set(fields):
            raise ValueError("Missing required columns: " + ", ".join(sorted(missing)))
        allowed = required | {"phase", "description", "progress_pct", "preceding_step", "dependency_type", "dependency_lag"}
        if len(fields) != len(set(fields)) or set(fields) - allowed:
            raise ValueError("Duplicate or unsupported columns in the project template.")
        steps = []
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Row {line}: Column count does not match the header.")
            steps.append(_parse_step(row, line, date_format))
    except csv.Error as exc:
        raise ValueError("Invalid CSV quoting or structure.") from exc
    if not steps:
        raise ValueError("The template contains no tasks.")
    numbers = {step.number for step in steps}
    if len(numbers) != len(steps):
        raise ValueError("Step numbers must be unique.")
    for step in steps:
        predecessors = {dep.identity for dep in step.dependencies if dep.kind == "step"}
        if predecessors - numbers:
            raise ValueError(f"Step {step.number}: Unknown predecessor step(s): {sorted(predecessors - numbers)}.")
        if step.number in predecessors:
            raise ValueError(f"Step {step.number}: A task cannot contain a self-link.")
    # Multi-task cycles remain diagnostic warnings under the existing scheduling rules.
    return steps


def export_template(tasks: list[TaskValues], dependencies: list[DependencySchedule]) -> str:
    """Export actual project tasks and all incoming links with portable step numbers."""
    numbers = {task.get("id"): number for number, task in enumerate(tasks, 1)}
    grouped: dict[int, list[str]] = {}
    for dep in dependencies:
        predecessor = dep.get("predecessor_task_id")
        kind = "step" if predecessor in numbers else "task" if predecessor else "project"
        identity = numbers[predecessor] if kind == "step" else predecessor or dep.get("predecessor_project_id")
        grouped.setdefault(dep["task_id"], []).append(
            f"{kind}:{identity}:{dep.get('link_type', 'FS')}:{dep.get('lag_days', 0)}"
        )
    output = io.StringIO(newline="")
    fields = ["task_name", "phase", "start_date", "end_date", "progress_pct", "description"]
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["step_number", *fields, "preceding_step", "dependency_type", "dependency_lag"])
    for number, task in enumerate(tasks, 1):
        links = grouped.get(task.get("id"), []).copy()
        if not links and task.get("predecessor_id"):
            predecessor = task["predecessor_id"]
            links.append(f"step:{numbers[predecessor]}:FS:0" if predecessor in numbers else f"task:{predecessor}:FS:0")
        split = [link.split(":") for link in links]
        preceding = ";".join(parts[1] if parts[0] == "step" else ":".join(parts[:2]) for parts in split)
        types = ";".join(parts[2] for parts in split)
        lags = ";".join(parts[3] for parts in split)
        writer.writerow([number, *(task.get(field, "") for field in fields), preceding, types, lags])
    return output.getvalue()
