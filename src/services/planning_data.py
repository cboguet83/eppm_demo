"""Compatibility calls for the former planning caches.

The real caches and chart projection now live in presentation and receive an
injected workspace. These wrappers preserve historical path-based callers.
Any describes the historical mixed-value component JSON results.
"""

from collections.abc import Collection
from typing import Any
import pandas as pd
from app.main import create_planning_service, create_planning_workspace
from app.application.ports.planning import ProjectSummary
from app.application.ports.tag_records import TagLink
from app.domain.planning.records import DependencySchedule, ProjectBounds
from app.domain.resources.models import AssignmentLink, PoolCapacityDetail
from app.presentation.components import planning_data as _display


def ensure_planning_indexes(db_path: str | None = None) -> None:
    """Prepare planning's existing read model through the application service."""
    create_planning_service(db_path).ensure_indexes()


def load_planning_catalog(
    db_path: str | None, revision: tuple, property_ids: tuple[str, ...] = ()
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    """Delegate the historical load planning catalog call."""
    return _display.load_planning_catalog(
        create_planning_workspace(db_path), revision, property_ids
    )


load_planning_catalog.clear = _display.load_planning_catalog.clear


def load_planning_steps(
    db_path: str | None, revision: tuple, project_ids: tuple[int, ...]
) -> tuple[
    pd.DataFrame,
    list[DependencySchedule],
    dict[int, list[TagLink]],
    dict[int, list[AssignmentLink]],
]:
    """Delegate the historical load planning steps call."""
    return _display.load_planning_steps(create_planning_workspace(db_path), revision, project_ids)


load_planning_steps.clear = _display.load_planning_steps.clear


def load_planning_project_metadata(
    db_path: str | None, revision: tuple, project_ids: tuple[int, ...]
) -> tuple[dict[int, list[TagLink]], dict[int, list[AssignmentLink]]]:
    """Delegate the historical load planning project metadata call."""
    return _display.load_planning_project_metadata(
        create_planning_workspace(db_path), revision, project_ids
    )


load_planning_project_metadata.clear = _display.load_planning_project_metadata.clear


def load_planning_bounds(db_path: str | None, revision: tuple) -> ProjectBounds:
    """Delegate the historical load planning bounds call."""
    return _display.load_planning_bounds(create_planning_workspace(db_path), revision)


load_planning_bounds.clear = _display.load_planning_bounds.clear


def load_dependency_choices(
    db_path: str | None, revision: tuple, project_id: int
) -> list[dict[str, Any]]:
    """Delegate the historical load dependency choices call."""
    return _display.load_dependency_choices(
        create_planning_workspace(db_path), revision, project_id
    )


load_dependency_choices.clear = _display.load_dependency_choices.clear


def load_project_summaries(
    db_path: str | None, revision: tuple, project_ids: tuple[int, ...]
) -> list[ProjectSummary]:
    """Delegate the historical load project summaries call."""
    return _display.load_project_summaries(
        create_planning_workspace(db_path), revision, project_ids
    )


load_project_summaries.clear = _display.load_project_summaries.clear


def affected_task_projects(db_path: str | None, task_id: int) -> tuple[set[int], set[int]]:
    """Find only schedule dependents and assigned pools for the changed task."""
    return create_planning_service(db_path).affected_task_projects(task_id)


def build_task_payload(
    db_path: str | None,
    project_ids: Collection[int],
    bounds: ProjectBounds,
    pool_details: dict[int, PoolCapacityDetail],
) -> list[dict[str, Any]]:
    """Delegate the historical component payload boundary."""
    return _display.build_task_payload(
        create_planning_workspace(db_path), project_ids, bounds, pool_details
    )
