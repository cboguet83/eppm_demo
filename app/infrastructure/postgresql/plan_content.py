"""Batch capture of active relational plans for application DTOs."""

import psycopg
from app.domain.planning.plans import PlanContent


def capture_content(connection: psycopg.Connection, project_id: int) -> PlanContent:
    """Read one active plan or an empty initial schedule."""
    return capture_contents(connection, [project_id]).get(project_id, PlanContent())


def capture_contents(connection: psycopg.Connection, project_ids: list[int]) -> dict[int, PlanContent]:
    """Batch-read only the designated active plans."""
    from app.infrastructure.postgresql.plan_rows import read_plans
    owners = dict(connection.execute('SELECT project_id,id FROM eppm.project_plan WHERE is_current AND project_id=ANY(%s::bigint[])', (project_ids,)))
    contents = read_plans(connection, list(owners.values()))
    return {project: contents[plan] for project, plan in owners.items()}
