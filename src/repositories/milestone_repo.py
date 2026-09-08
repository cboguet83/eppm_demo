"""Historical task API adapting IDs/DataFrames to layered planning use cases.

Any is confined to legacy dictionary payloads from pandas and old components.
The new application uses typed task contracts.
"""

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from typing import Any
import pandas as pd
from app.application.exceptions import PlanningConflictError, PlanningStorageError
from app.main import create_planning_service
from app.presentation.components.planning_frames import tasks_frame
from src.repositories.project_repo import parse_project_id


@contextmanager
def legacy_planning_errors() -> Iterator[None]:
    """Keep historical SQLite errors for callers outside migrated presentation."""
    try:
        yield
    except (PlanningConflictError, PlanningStorageError) as exc:
        if isinstance(exc.__cause__, sqlite3.DatabaseError):
            raise exc.__cause__ from exc
        raise


def _dependencies(values: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if values is None:
        return None
    result = []
    for value in values:
        project = value.get("predecessor_project_id")
        result.append(
            {
                **value,
                "predecessor_project_id": (
                    parse_project_id(project)
                    if project is not None and str(project).strip()
                    else None
                ),
            }
        )
    return result


class MilestoneRepository:
    """Preserve the old API while the remaining planning callers are migrated."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain the database path and compose the layered service."""
        self.db_path = db_path
        self.service = create_planning_service(db_path)

    def get_milestones_by_project(self, project_id: int | str) -> pd.DataFrame:
        """Loads all steps/tasks for a specific project sorted by start date."""
        with legacy_planning_errors():
            return tasks_frame(
                self.service.get_milestones_by_project(project_id=parse_project_id(project_id)),
                project_labels=False,
            )

    def search_task_choices(self, search: str = "", *, limit: int = 50) -> list[dict[str, Any]]:
        """Small on-demand task lookup for tag editors; never fetch all tasks."""
        with legacy_planning_errors():
            return self.service.search_task_choices(search=search, limit=limit)

    def get_all_milestones(self) -> pd.DataFrame:
        """Loads all steps/tasks across all projects enriched with project names."""
        with legacy_planning_errors():
            return tasks_frame(self.service.get_all_milestones(), project_labels=True)

    def get_dependencies_for_project(self, project_id: int | str) -> list[dict[str, Any]]:
        """Retrieves all dependency records for steps in a project."""
        with legacy_planning_errors():
            return self.service.get_dependencies_for_project(
                project_id=parse_project_id(project_id)
            )

    def get_task_dependencies(self, task_id: int) -> list[dict[str, Any]]:
        """Retrieves all predecessor dependencies for a specific task."""
        with legacy_planning_errors():
            return self.service.get_task_dependencies(task_id=task_id)

    def save_task_dependencies(self, task_id: int, dependencies: list[dict[str, Any]]) -> None:
        """Replaces all dependencies for a task with a new set of dependencies."""
        with legacy_planning_errors():
            return self.service.save_task_dependencies(
                task_id=task_id, dependencies=_dependencies(dependencies)
            )

    def add_dependency(
        self,
        task_id: int,
        predecessor_task_id: int | None = None,
        predecessor_project_id: int | str | None = None,
        link_type: str = "FS",
        lag_days: int = 0,
    ) -> None:
        """Adds a single dependency for a milestone/task."""
        with legacy_planning_errors():
            return self.service.add_dependency(
                task_id=task_id,
                predecessor_task_id=predecessor_task_id,
                predecessor_project_id=(
                    parse_project_id(predecessor_project_id)
                    if predecessor_project_id is not None and str(predecessor_project_id).strip()
                    else None
                ),
                link_type=link_type,
                lag_days=lag_days,
            )

    def get_project_date_bounds(self, project_id: int | str) -> tuple[str | None, str | None]:
        """Calculates the overall earliest start date and latest end date of a project."""
        with legacy_planning_errors():
            return self.service.get_project_date_bounds(project_id=parse_project_id(project_id))

    def get_all_project_date_bounds(self) -> dict[Any, tuple[str | None, str | None]]:
        """Calculates earliest start and latest end dates for all projects in one query."""
        with legacy_planning_errors():
            return self.service.get_all_project_date_bounds()

    def get_all_external_tasks_map(
        self, exclude_project_ids: list[int | str] | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Retrieves all tasks grouped by project ID for external link mapping in one query."""
        with legacy_planning_errors():
            return self.service.get_all_external_tasks_map(
                exclude_project_ids=[parse_project_id(pid) for pid in exclude_project_ids or []]
            )

    def get_milestones_for_projects(self, project_ids: list[int | str]) -> pd.DataFrame:
        """Loads all steps/tasks for multiple projects sorted by project and start date."""
        with legacy_planning_errors():
            return tasks_frame(
                self.service.get_milestones_for_projects(
                    project_ids=[parse_project_id(pid) for pid in project_ids]
                ),
                project_labels=False,
            )

    def get_dependencies_for_projects(self, project_ids: list[int | str]) -> list[dict[str, Any]]:
        """Retrieves all dependency records for steps in a list of projects in a single query."""
        with legacy_planning_errors():
            return self.service.get_dependencies_for_projects(
                project_ids=[parse_project_id(pid) for pid in project_ids]
            )

    def create_milestone(
        self,
        project_id: int | str,
        task_name: str,
        phase: str,
        start_date: str,
        end_date: str,
        progress_pct: int,
        predecessor_id: int | None = None,
        dependencies: list[dict[str, Any]] | None = None,
        description: str | None = None,
    ) -> int:
        """Creates a single project step or task."""
        with legacy_planning_errors():
            return self.service.create_milestone(
                project_id=parse_project_id(project_id),
                task_name=task_name,
                phase=phase,
                start_date=start_date,
                end_date=end_date,
                progress_pct=progress_pct,
                predecessor_id=predecessor_id,
                dependencies=_dependencies(dependencies),
                description=description,
            )

    def update_milestone(
        self,
        milestone_id: int,
        task_name: str,
        phase: str,
        start_date: str,
        end_date: str,
        progress_pct: int,
        predecessor_id: int | None = None,
        dependencies: list[dict[str, Any]] | None = None,
        description: str | None = None,
    ) -> bool:
        """Updates an existing project step or task."""
        with legacy_planning_errors():
            return self.service.update_milestone(
                milestone_id=milestone_id,
                task_name=task_name,
                phase=phase,
                start_date=start_date,
                end_date=end_date,
                progress_pct=progress_pct,
                predecessor_id=predecessor_id,
                dependencies=_dependencies(dependencies),
                description=description,
            )

    def update_dates(self, milestone_id: int, start_date: str, end_date: str) -> bool:
        """Updates only the start and end dates of a step."""
        with legacy_planning_errors():
            return self.service.update_dates(
                milestone_id=milestone_id, start_date=start_date, end_date=end_date
            )

    def update_progress(self, milestone_id: int, progress_pct: int) -> bool:
        """Updates only the progress percentage of a step."""
        with legacy_planning_errors():
            return self.service.update_progress(
                milestone_id=milestone_id, progress_pct=progress_pct
            )

    def bulk_create_milestones(self, rows: list[dict[str, Any]]) -> int:
        """Bulk inserts step/task records in a single database transaction."""
        with legacy_planning_errors():
            return self.service.bulk_create_milestones(
                rows=[{**row, "project_id": parse_project_id(row["project_id"])} for row in rows]
            )

    def delete_milestone(self, milestone_id: int) -> bool:
        """Deletes a step/task by ID, cleaning up any task dependencies first."""
        with legacy_planning_errors():
            return self.service.delete_milestone(milestone_id=milestone_id)

    def get_milestone_by_id(self, milestone_id: int) -> dict[str, Any] | None:
        """Retrieves a single project task by primary key ID."""
        with legacy_planning_errors():
            return self.service.get_milestone_by_id(milestone_id=milestone_id)
