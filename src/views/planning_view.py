"""Historical planning entry point; the screen lives in layered presentation."""

from typing import Protocol

from app.main import create_planning_workspace
from app.presentation.pages.planning import render_planning_milestones as render_planning


class DatabaseSource(Protocol):
    """The database identity retained by historical repository callers."""

    db_path: str | None


def render_planning_milestones(
    project_repo: DatabaseSource,
    milestone_repo: DatabaseSource,
    tag_repo: DatabaseSource | None = None,
    pool_repo: DatabaseSource | None = None,
    org_repo: DatabaseSource | None = None,
    schema_repo: DatabaseSource | None = None,
) -> None:
    """Adapt the old call shape to services composed for its project database."""
    render_planning(create_planning_workspace(project_repo.db_path))
