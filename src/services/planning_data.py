"""Bounded, revision-aware caches for planning inputs and selected-project reads."""

import streamlit as st

from app.main import create_planning_service
from src.repositories.project_repo import ProjectRepository
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.tag_repo import TagRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.schema_repo import SchemaRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.services.organization_service import OrganizationService
from src.services.portfolio_service import PortfolioService


def ensure_planning_indexes(db_path: str | None = None) -> None:
    """Prepare the planning read model through its application boundary."""
    create_planning_service(db_path).ensure_indexes()


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def load_planning_catalog(db_path, revision, property_ids=()):
    ensure_planning_indexes(db_path)
    projects = ProjectRepository(db_path).get_planning_catalog(property_ids)
    params = SchemaRepository(db_path).get_all_parameters()
    org = OrganizationRepository(db_path)
    # Organization labels are calculated once per revision, not once per rerun.
    frame = (
        PortfolioService.flatten_dynamic_attributes(
            projects, params[params.param_id.isin(property_ids)]
        )
        if property_ids
        else projects.copy()
    )
    frame = OrganizationService.enrich_projects_with_organization(
        frame, org.get_all_functions(), org.get_all_employees()
    )
    tags = TagRepository(db_path).get_all_project_tags().to_dict("records")
    return projects, frame, params, tags


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def load_planning_steps(db_path, revision, project_ids):
    repo = MilestoneRepository(db_path)
    steps = repo.get_milestones_for_projects(list(project_ids))
    dependencies = repo.get_dependencies_for_projects(list(project_ids))
    task_ids = steps.id.tolist() if not steps.empty else []
    return (
        steps,
        dependencies,
        TagRepository(db_path).get_task_tags_by_task_ids(task_ids),
        ResourcePoolRepository(db_path).get_task_assignments_map(task_ids),
    )


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def load_planning_project_metadata(db_path, revision, project_ids):
    return (
        TagRepository(db_path).get_project_tags_by_project_ids(list(project_ids)),
        ResourcePoolRepository(db_path).get_project_assignments_map(list(project_ids)),
    )


@st.cache_data(ttl=60, max_entries=4, show_spinner=False)
def load_planning_bounds(db_path, revision):
    return MilestoneRepository(db_path).get_all_project_date_bounds()


@st.cache_data(ttl=60, max_entries=16, show_spinner=False)
def load_dependency_choices(db_path, revision, project_id):
    steps = MilestoneRepository(db_path).get_milestones_for_projects([project_id])
    return (
        steps[["id", "task_name", "start_date", "end_date"]].to_dict("records")
        if not steps.empty
        else []
    )


@st.cache_data(ttl=60, max_entries=8, show_spinner=False, hash_funcs={tuple: repr})
def load_project_summaries(db_path, revision, project_ids):
    """Keep the revision cache while delegating summary transactions."""
    return create_planning_service(db_path).get_project_summaries(list(project_ids))


def affected_task_projects(db_path: str | None, task_id: int) -> tuple[set[int], set[int]]:
    """Find only the projects and pools affected by the edited task."""
    return create_planning_service(db_path).affected_task_projects(task_id)


def build_task_payload(db_path, project_ids, bounds, pool_details):
    """Hydrate only requested projects, with the same constraint/capacity semantics."""
    from src.repositories.portfolio_repo import portfolio_revision
    from src.services.milestone_service import MilestoneService

    steps, deps, tags, pools = load_planning_steps(
        db_path, portfolio_revision(db_path), tuple(sorted(project_ids))
    )
    if steps.empty:
        return []
    records = steps.to_dict("records")
    for dependency in deps:
        pid = dependency.get("predecessor_project_id")
        if pid and not dependency.get("predecessor_task_id") and str(pid) not in bounds:
            bounds[str(pid)] = MilestoneRepository(db_path).get_project_date_bounds(pid)
    evaluated, violations = MilestoneService.evaluate_constraints(records, deps, bounds)
    by_task = {}
    for dep in evaluated:
        by_task.setdefault(int(dep["task_id"]), []).append(dep)
    names = {
        p["id"]: p["name"]
        for p in load_project_summaries(
            db_path, portfolio_revision(db_path), tuple(sorted(project_ids))
        )
    }
    result = []
    for row in records:
        tid = int(row["id"])
        enriched = []
        for assignment in pools.get(tid, []):
            assignment = dict(assignment)
            detail = pool_details.get(assignment["pool_id"])
            if detail:
                start = assignment.get("start_date") or row["start_date"]
                end = assignment.get("end_date") or row["end_date"]
                assignment["pool_capacity"] = detail.total_capacity_fte
                assignment["is_overassigned"] = float(
                    assignment["fte"]
                ) > detail.total_capacity_fte + 1e-4 or any(
                    str(start) <= d.date <= str(end) for d in detail.daily_overassignments
                )
            enriched.append(assignment)
        result.append(
            {
                "id": str(tid),
                "name": row["task_name"],
                "start": row["start_date"],
                "end": row["end_date"],
                "project_id": str(row["project_id"]),
                "project_name": names.get(row["project_id"], str(row["project_id"])),
                "progress": int(row.get("progress_pct", 0)),
                "phase": row.get("phase", "General"),
                "description": row.get("description") or "",
                "dependenciesList": by_task.get(tid, []),
                "violations": violations.get(tid, []),
                "tags": tags.get(tid, []),
                "pools": enriched,
            }
        )
    return result
