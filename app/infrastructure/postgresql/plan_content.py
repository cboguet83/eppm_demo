"""Explicit snapshot encoding and current-schedule capture for project plans."""

from dataclasses import asdict
from typing import cast

import psycopg
from psycopg.rows import dict_row

from app.domain.planning.plans import PlanContent, PlanDependency, PlanTask, PlanTag
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
    return capture_contents(connection, [project_id])[project_id]


def capture_contents(connection: psycopg.Connection, project_ids: list[int]) -> dict[int, PlanContent]:
    """Batch-capture live schedules without a query per project."""
    result = {identity: PlanContent([], [], [], {}) for identity in project_ids}
    with connection.cursor(row_factory=dict_row) as cursor:
        for row in cursor.execute('''SELECT project_id,id,task_name,phase,start_date::text,end_date::text,description
            FROM eppm.project_task WHERE project_id=ANY(%s::bigint[]) ORDER BY id''', (project_ids,)):
            result[row.pop('project_id')].tasks.append(cast(PlanTask, row))
        for row in cursor.execute('''SELECT t.project_id,d.task_id,d.predecessor_task_id,d.predecessor_project_id,
            d.link_type,d.lag_days FROM eppm.task_dependencies d JOIN eppm.project_task t ON t.id=d.task_id
            WHERE t.project_id=ANY(%s::bigint[]) UNION ALL SELECT project_id,NULL,predecessor_task_id,predecessor_project_id,link_type,lag_days
            FROM eppm.project_dependency WHERE project_id=ANY(%s::bigint[])''', (project_ids, project_ids)):
            result[row.pop('project_id')].dependencies.append(cast(PlanDependency, row))
        direct = connection.execute("SELECT has_column_privilege(current_user,'eppm.project_task','predecessor_id','SELECT')").fetchone()[0]
        source = 'eppm.project_task' if direct else 'eppm.visible_project_task'
        primary = list(cursor.execute(f'''SELECT project_id,id AS task_id,predecessor_id AS predecessor_task_id,
            NULL::bigint AS predecessor_project_id,'FS' AS link_type,0 AS lag_days
            FROM {source} WHERE project_id=ANY(%s::bigint[]) AND predecessor_id IS NOT NULL''', (project_ids,)))
        for row in primary:
            dependencies = result[row.pop('project_id')].dependencies
            if not any(dep['task_id'] == row['task_id'] and dep['predecessor_task_id'] == row['predecessor_task_id']
                       for dep in dependencies):
                dependencies.append(cast(PlanDependency, row))
        for row in cursor.execute('''SELECT id,pool_id,project_id,task_id,
            fte_assigned::float,start_date::text,end_date::text,notes,schedule_anchor,offset_days,duration_days
            FROM eppm.resource_pool_assignment WHERE project_id=ANY(%s::bigint[]) ORDER BY id''', (project_ids,)):
            result[row['project_id']].assignments.append(PoolAssignment(**row))
    for project_id, task_id, tag_id, free_tag in connection.execute('''SELECT t.project_id,tt.task_id,tt.tag_id,tt.free_tag FROM eppm.task_tag tt
        JOIN eppm.project_task t ON t.id=tt.task_id WHERE t.project_id=ANY(%s::bigint[])''', (project_ids,)):
        result[project_id].task_tags.setdefault(task_id, []).append(PlanTag(tag_id=tag_id, free_tag=free_tag))
    return result
