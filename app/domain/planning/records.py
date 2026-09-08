"""Typed scheduling inputs shared by task use cases and constraint evaluation."""

from typing import NotRequired, TypedDict


class TaskValues(TypedDict):
    """Editable task values, with defaults supplied by the application."""

    task_name: str
    start_date: str
    end_date: str
    phase: NotRequired[str]
    progress_pct: NotRequired[int]
    description: NotRequired[str]
    predecessor_id: NotRequired[int | None]


class TaskInput(TaskValues):
    """Task values associated with a stable project identity."""

    project_id: int


class TaskSchedule(TypedDict, total=False):
    """Dates and labels needed to evaluate a task's incoming constraints."""

    id: int
    task_name: str
    start_date: str
    end_date: str


class DependencyInput(TypedDict, total=False):
    """Optional predecessor selection and link settings."""

    predecessor_task_id: int | None
    predecessor_project_id: int | None
    link_type: str
    lag_days: int


class DependencySchedule(TypedDict, total=False):
    """Enriched predecessor dates for local, cross-project, and whole-project links."""

    id: int
    task_id: int
    predecessor_task_id: int | None
    predecessor_project_id: int | str | None
    link_type: str
    lag_days: int
    predecessor_task_name: str | None
    predecessor_project_name: str | None
    pred_start_date: str | None
    pred_end_date: str | None
    pred_task_project_id: int | None
    task_name: str


class EvaluatedDependency(DependencySchedule, total=False):
    """A dependency with its existing display warning fields."""

    is_violated: bool
    violation_text: str | None
    pred_start: str | None
    pred_end: str | None
    pred_label: str


type ProjectBounds = dict[int | str, tuple[str | None, str | None]]
