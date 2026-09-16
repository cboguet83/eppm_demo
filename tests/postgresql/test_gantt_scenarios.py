"""Alternative rescheduling never changes the active schedule or pool demand."""

from copy import deepcopy

import psycopg
import pytest

from app.application.exceptions import PlanningConflictError
from app.domain.access.models import AccessDenied
from app.domain.resources.models import PoolAssignment
from tests.postgresql.test_project_plans import service, draft_task
from tests.postgresql.test_resource_pools import service as pools


def test_comparison_reschedule_keeps_current_baseline_and_allocations(authorized):
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date) VALUES(1,%s,'Active task','2027-01-01','2027-01-05')", (initial.id,))
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Pool',2)")
    pools(authorized).create_assignment(PoolAssignment(pool_id=1, project_id=1, task_id=1, fte_assigned=1))
    baseline = plans.baseline_current(1)
    initial = next(row for row in plans.list_plans(1) if row.is_current)
    content = deepcopy(initial.content)
    content.tasks.append(draft_task(-1, 'Extra step'))
    alternative = plans.save(1, initial.id, initial.revision, 'Option A', content)
    before_assignments = pools(authorized).get_assignments()
    _, rows = plans.comparison(1, alternative.id)
    assert rows[0]['id'] == 1 and rows[0]['stable_id'] == 1
    assert rows[1]['id'] < 0 and rows[1]['stable_id'] > 0
    plans.reschedule_alternative(1, alternative.id, alternative.revision, 1, '2027-02-01', '2027-02-05')
    saved = {row.id: row for row in plans.list_plans(1)}
    assert saved[alternative.id].content.tasks[0]['start_date'] == '2027-02-01'
    assert saved[alternative.id].revision == alternative.revision + 1
    assert saved[initial.id].content == initial.content
    assert saved[baseline.id].content == baseline.content
    assert pools(authorized).get_assignments() == before_assignments
    assert saved[alternative.id].content.assignments == alternative.content.assignments
    with pytest.raises(PlanningConflictError):
        plans.reschedule_alternative(1, alternative.id, alternative.revision, 1, '2027-03-01', '2027-03-05')
    with pytest.raises(AccessDenied):
        service(authorized, 2).reschedule_alternative(1, alternative.id, alternative.revision + 1, 1, '2027-03-01', '2027-03-05')
    for forbidden in (saved[initial.id], saved[baseline.id]):
        with pytest.raises(ValueError):
            plans.comparison(1, forbidden.id)
        with pytest.raises(ValueError):
            plans.reschedule_alternative(1, forbidden.id, forbidden.revision, 1, '2027-03-01', '2027-03-05')


def test_delete_baseline_retains_frozen_history_and_active_plan(authorized):
    plans = service(authorized, 4)
    baseline = plans.baseline_current(1)
    with pytest.raises(AccessDenied):
        service(authorized, 1).delete_baseline(1)
    plans.delete_baseline(1)
    saved = {row.id: row for row in plans.list_plans(1)}
    assert saved[baseline.id].status == 'deleted'
    assert saved[baseline.id].is_frozen and not saved[baseline.id].is_baseline
    assert plans.baseline_tasks([1]) == {}
    assert sum(row.is_current for row in saved.values()) == 1
    with pytest.raises(ValueError):
        plans.comparison(1, baseline.id)
