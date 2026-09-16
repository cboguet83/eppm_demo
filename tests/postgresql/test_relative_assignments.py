"""Real storage, constraints and current owner schedule resolution."""

from dataclasses import replace
from datetime import date, timedelta

import psycopg
import pytest

from app.domain.access.models import AccessDenied
from app.domain.resources.capacity import calculate_capacity
from app.domain.resources.models import PoolAssignment, ResourcePool
from app.infrastructure.postgresql.operator_capacity import read_operator_capacity_inputs
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore
from tests.postgresql.test_resource_pools import pools, service


@pytest.mark.parametrize('task_id,anchor', [(11, 'start'), (11, 'end'), (None, 'start'), (None, 'end')])
def test_relative_storage_and_links_move_with_current_owner_dates(authorized, pools, task_id, anchor):
    pool_id = pools.create_pool(ResourcePool('Relative pool', capacity_fte=1))
    identity = pools.create_assignment(PoolAssignment(pool_id, 1, 2, task_id=task_id,
        schedule_anchor=anchor, offset_days=10, duration_days=5))
    original = pools.get_assignment_by_id(identity)
    assert original.start_date is original.end_date is None
    assert (original.schedule_anchor, original.offset_days, original.duration_days) == (anchor, 10, 5)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project_task SET start_date='2026-05-31',end_date='2026-06-30' WHERE id=11")
        def resolved():
            inputs = read_operator_capacity_inputs(connection, [pool_id])[pool_id]
            return calculate_capacity(inputs, date(2026, 1, 1)).assignments[0]
        first = resolved()
        expected = '2026-06-10' if anchor == 'start' else '2026-07-10'
        assert first['start_date'] == expected
        store = PostgresResourcePoolStore(connection)
        links = store.get_task_assignments_map([11]) if task_id else store.get_project_assignments_map([1])
        assert links[task_id or 1][0]['start_date'] == expected
        connection.execute("UPDATE eppm.project_task SET start_date=start_date+30,end_date=end_date+30 WHERE id=11")
        assert date.fromisoformat(resolved()['start_date']) == date.fromisoformat(expected) + timedelta(days=30)
    assert pools.update_assignment(replace(original, offset_days=-5, duration_days=1))
    assert pools.get_assignment_by_id(identity).duration_days == 1
    with pytest.raises(AccessDenied):
        service(authorized, 1).create_assignment(replace(original, id=None, project_id=2, task_id=12 if task_id else None))


@pytest.mark.parametrize('columns,values', [
    ('schedule_anchor', "'start'"),
    ('offset_days', '1'),
    ('schedule_anchor,offset_days,duration_days', "'start',10,0"),
    ('schedule_anchor,offset_days,duration_days,start_date', "'end',10,5,'2026-01-01'"),
])
def test_database_rejects_partial_and_mixed_relative_modes(authorized, pools, columns, values):
    identity = pools.create_pool(ResourcePool('Constraint pool'))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(f'INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,{columns},project_plan_id) VALUES (%s,1,1,{values},(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))', (identity,))

