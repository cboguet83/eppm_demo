"""Explicit snapshot encoding and current-schedule capture for project plans."""

from dataclasses import asdict
from typing import cast

import psycopg
from psycopg.rows import dict_row

from app.domain.planning.plans import PlanContent, PlanDependency, PlanTask
from app.domain.resources.models import PoolAssignment


def encode_content(content: PlanContent) -> dict:
    """Encode the typed plan at the JSON persistence boundary."""
    return asdict(content)


def decode_content(value: dict) -> PlanContent:
    """Decode stored complete snapshots without exposing database rows to UI."""
    return PlanContent(value['tasks'], value['dependencies'],
        [PoolAssignment(**row) for row in value['assignments']],
        {int(identity): tags for identity, tags in value['task_tags'].items()})


def capture_content(connection: psycopg.Connection, project_id: int) -> PlanContent:
    """Capture all versioned schedule fields from one consistent transaction."""
    with connection.cursor(row_factory=dict_row) as cursor:
        tasks = list(cursor.execute('''SELECT id,task_name,phase,start_date::text,end_date::text,description
            FROM eppm.project_task WHERE project_id=%s ORDER BY id''', (project_id,)))
        dependencies = list(cursor.execute('''SELECT d.task_id,d.predecessor_task_id,d.predecessor_project_id,
            d.link_type,d.lag_days FROM eppm.task_dependencies d JOIN eppm.project_task t ON t.id=d.task_id
            WHERE t.project_id=%s UNION ALL SELECT NULL,predecessor_task_id,predecessor_project_id,link_type,lag_days
            FROM eppm.project_dependency WHERE project_id=%s''', (project_id, project_id)))
        assignments = [PoolAssignment(**row) for row in cursor.execute('''SELECT id,pool_id,project_id,task_id,
            fte_assigned::float,start_date::text,end_date::text,notes,schedule_anchor,offset_days,duration_days
            FROM eppm.resource_pool_assignment WHERE project_id=%s ORDER BY id''', (project_id,))]
    tags: dict[int, list[int]] = {}
    for task_id, tag_id in connection.execute('''SELECT tt.task_id,tt.tag_id FROM eppm.task_tag tt
        JOIN eppm.project_task t ON t.id=tt.task_id WHERE t.project_id=%s''', (project_id,)):
        tags.setdefault(task_id, []).append(tag_id)
    return PlanContent(cast(list[PlanTask], tasks), cast(list[PlanDependency], dependencies), assignments, tags)
