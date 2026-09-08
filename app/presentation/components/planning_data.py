"""Revision-keyed display caches using injected planning services.

Any describes the existing component JSON and DataFrame boundary. Cache keys
include the complete database revision; injected service instances are not hashed.
"""

from collections.abc import Collection
from dataclasses import asdict
from typing import Any

import pandas as pd
import streamlit as st

from app.application.ports.planning import ProjectSummary
from app.application.ports.tag_records import TagLink
from app.domain.planning.constraints import evaluate_constraints
from app.domain.planning.records import DependencySchedule, ProjectBounds
from app.domain.resources.models import AssignmentLink, PoolCapacityDetail
from app.domain.resources.overallocation import assignment_is_overallocated
from app.presentation.components.organization_frames import employees_frame, functions_frame
from app.presentation.components.planning_catalog import (
    enrich_projects_with_organization,
    flatten_dynamic_attributes,
)
from app.presentation.components.planning_frames import tasks_frame
from app.presentation.components.planning_workspace import PlanningWorkspace
from app.presentation.components.schema_frames import parameters_frame


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def load_planning_catalog(
    _workspace: PlanningWorkspace,
    revision: tuple,
    property_ids: tuple[str, ...] = (),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    """Cache minimal project identities and only currently selected filter values."""
    _workspace.planning.ensure_indexes()
    projects = pd.DataFrame(
        _workspace.projects.projects.get_planning_catalog(property_ids),
        columns=[
            "id",
            "name",
            "status",
            "function_id",
            "project_type_id",
            "project_template",
            "dynamic_attributes",
        ],
    )
    params = parameters_frame(_workspace.schema.get_all_parameters())
    frame = (
        flatten_dynamic_attributes(projects, params[params.param_id.isin(property_ids)])
        if property_ids
        else projects.copy()
    )
    frame = enrich_projects_with_organization(
        frame,
        functions_frame(_workspace.organization.get_all_functions()),
        employees_frame(_workspace.organization.get_all_employees()),
    )
    tags = [asdict(row) for row in _workspace.tags.get_all_project_tags()]
    return projects, frame, params, tags


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def load_planning_steps(
    _workspace: PlanningWorkspace,
    revision: tuple,
    project_ids: tuple[int, ...],
) -> tuple[
    pd.DataFrame,
    list[DependencySchedule],
    dict[int, list[TagLink]],
    dict[int, list[AssignmentLink]],
]:
    """Hydrate requested tasks and links from one application snapshot."""
    bundle = _workspace.planning.read_task_bundle(list(project_ids))
    return tasks_frame(bundle.tasks), bundle.dependencies, bundle.tags, bundle.pools


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def load_planning_project_metadata(
    _workspace: PlanningWorkspace,
    revision: tuple,
    project_ids: tuple[int, ...],
) -> tuple[dict[int, list[TagLink]], dict[int, list[AssignmentLink]]]:
    """Load project-level display tags and assignments only for requested projects."""
    return (
        _workspace.tags.get_project_tags_by_project_ids(list(project_ids)),
        _workspace.resources.get_project_assignments_map(list(project_ids)),
    )


@st.cache_data(ttl=60, max_entries=4, show_spinner=False)
def load_planning_bounds(_workspace: PlanningWorkspace, revision: tuple) -> ProjectBounds:
    """Cache aggregate dates for explicit callers needing all project bounds."""
    return _workspace.planning.get_all_project_date_bounds()


@st.cache_data(ttl=60, max_entries=16, show_spinner=False)
def load_dependency_choices(
    _workspace: PlanningWorkspace,
    revision: tuple,
    project_id: int,
) -> list[dict[str, Any]]:
    """Supply predecessor choices only for the project opened in the editor."""
    return [
        {key: row[key] for key in ("id", "task_name", "start_date", "end_date")}
        for row in _workspace.planning.get_milestones_for_projects([project_id])
    ]


@st.cache_data(ttl=60, max_entries=8, show_spinner=False, hash_funcs={tuple: repr})
def load_project_summaries(
    _workspace: PlanningWorkspace,
    revision: tuple,
    project_ids: tuple[int, ...],
) -> list[ProjectSummary]:
    """Cache compact headers using the application's atomic summary projection."""
    return _workspace.planning.get_project_summaries(list(project_ids))


def affected_task_projects(
    _workspace: PlanningWorkspace, task_id: int
) -> tuple[set[int], set[int]]:
    """Identify only dependent project rows and assigned pools after an edit."""
    return _workspace.planning.affected_task_projects(task_id)


def build_task_payload(
    _workspace: PlanningWorkspace,
    project_ids: Collection[int],
    bounds: ProjectBounds,
    pool_details: dict[int, PoolCapacityDetail],
) -> list[dict[str, Any]]:
    """Build the established Gantt payload from bounded, typed application reads."""
    ids = tuple(sorted(project_ids))
    steps, deps, tags, pools = load_planning_steps(_workspace, _workspace.revision(), ids)
    if steps.empty:
        return []
    records = steps.to_dict("records")
    for dependency in deps:
        pid = dependency.get("predecessor_project_id")
        if pid and not dependency.get("predecessor_task_id") and str(pid) not in bounds:
            bounds[str(pid)] = _workspace.planning.get_project_date_bounds(int(pid))
    evaluated, violations = evaluate_constraints(records, deps, bounds)
    by_task = {}
    for dependency in evaluated:
        by_task.setdefault(int(dependency["task_id"]), []).append(dependency)
    names = {
        row["id"]: row["name"]
        for row in load_project_summaries(_workspace, _workspace.revision(), ids)
    }
    result = []
    for row in records:
        task_id = int(row["id"])
        enriched = []
        for original in pools.get(task_id, []):
            assignment = dict(original)
            detail = pool_details.get(assignment["pool_id"])
            if detail:
                start = assignment.get("start_date") or row["start_date"]
                end = assignment.get("end_date") or row["end_date"]
                assignment["pool_capacity"] = detail.total_capacity_fte
                assignment["is_overassigned"] = assignment_is_overallocated(
                    float(assignment["fte"]),
                    str(start),
                    str(end),
                    detail,
                )
            enriched.append(assignment)
        result.append(
            {
                "id": str(task_id),
                "name": row["task_name"],
                "start": row["start_date"],
                "end": row["end_date"],
                "project_id": str(row["project_id"]),
                "project_name": names.get(row["project_id"], str(row["project_id"])),
                "progress": int(row.get("progress_pct", 0)),
                "phase": row.get("phase", "General"),
                "description": row.get("description") or "",
                "dependenciesList": by_task.get(task_id, []),
                "violations": violations.get(task_id, []),
                "tags": tags.get(task_id, []),
                "pools": enriched,
            }
        )
    return result
