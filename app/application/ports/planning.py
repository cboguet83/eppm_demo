"""Transactional task storage and bounded planning query contracts."""

from contextlib import AbstractContextManager
from typing import NotRequired, Protocol, TypedDict

from app.domain.planning.records import (
    DependencyInput,
    DependencySchedule,
    ProjectBounds,
    TaskInput,
    TaskValues,
)


class TaskRow(TaskInput):
    """Task projection with optional joined display labels."""

    id: int
    predecessor_name: NotRequired[str | None]
    project_name: NotRequired[str | None]


class ExternalTask(TypedDict):
    """Minimal external predecessor choice."""

    id: int
    task_name: str
    start_date: str
    end_date: str


class TaskChoice(TypedDict):
    """Bounded task selector projection."""

    id: int
    task_name: str
    project_id: int
    project_name: str


class PlanningStore(Protocol):
    """Task operations sharing the gateway's connection and snapshot."""

    def get_milestones_by_project(self, project_id: int) -> list[TaskRow]: ...
    def search_task_choices(self, search: str = "", *, limit: int = 50) -> list[TaskChoice]: ...
    def get_all_milestones(self) -> list[TaskRow]: ...
    def get_dependencies_for_project(self, project_id: int) -> list[DependencySchedule]: ...
    def get_task_dependencies(self, task_id: int) -> list[DependencySchedule]: ...
    def get_project_date_bounds(self, project_id: int) -> tuple[str | None, str | None]: ...
    def get_all_project_date_bounds(self) -> ProjectBounds: ...
    def get_all_external_tasks_map(
        self,
        exclude_project_ids: list[int] | None = None,
    ) -> dict[str, list[ExternalTask]]: ...
    def get_milestones_for_projects(self, project_ids: list[int]) -> list[TaskRow]: ...
    def get_dependencies_for_projects(
        self, project_ids: list[int]
    ) -> list[DependencySchedule]: ...
    def get_milestone_by_id(self, milestone_id: int) -> TaskRow | None: ...
    def create_task(self, project_id: int, values: TaskValues) -> int: ...
    def update_task(self, task_id: int, values: TaskValues) -> bool: ...
    def replace_dependencies(self, task_id: int, dependencies: list[DependencyInput]) -> None: ...
    def insert_dependency(self, task_id: int, dependency: DependencyInput) -> None: ...
    def update_dates(self, milestone_id: int, start_date: str, end_date: str) -> bool: ...
    def update_progress(self, milestone_id: int, progress_pct: int) -> bool: ...
    def bulk_create_milestones(self, rows: list[TaskInput]) -> int: ...
    def delete_milestone(self, milestone_id: int) -> bool: ...


class PlanningGateway(Protocol):
    """Provide a consistent reader or reserve the writer before related changes."""

    def transaction(self, *, write: bool = False) -> AbstractContextManager[PlanningStore]: ...
