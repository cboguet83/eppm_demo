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


def test_alternative_edit_preserves_active_rows_and_releases_removed_task_allocations(authorized):
    plans = service(authorized, 4)
    current = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Pool',2)")
    content = deepcopy(current.content)
    content.tasks = [draft_task(-1, 'First'), draft_task(-2, 'Second')]
    content.assignments = [PoolAssignment(pool_id=1, project_id=1, task_id=-1, fte_assigned=1)]
    alternative = plans.save(1, current.id, current.revision, 'Editable option', content)
    first, second = [row['id'] for row in alternative.content.tasks]
    changed = deepcopy(alternative.content)
    changed.tasks[0]['task_name'] = 'Renamed'
    changed.dependencies = [dict(task_id=second, predecessor_task_id=first, predecessor_project_id=None, link_type='SS', lag_days=2)]
    changed.task_tags = {second: [dict(tag_id=None, free_tag='Alternative tag')]}
    plans.update_alternative(1, alternative.id, alternative.revision, changed)
    saved = next(row for row in plans.list_plans(1) if row.id == alternative.id)
    assert saved.content == changed
    with pytest.raises(PlanningConflictError):
        plans.update_alternative(1, alternative.id, alternative.revision, changed)
    changed.tasks = changed.tasks[1:] + [draft_task(-1, 'New unmapped task')]
    plans.update_alternative(1, alternative.id, saved.revision, changed)
    saved = next(row for row in plans.list_plans(1) if row.id == alternative.id)
    assert saved.content.assignments == []
    assert saved.content.dependencies == []
    assert saved.content.tasks[-1]['id'] > 0
    assert next(row for row in plans.list_plans(1) if row.is_current).content == current.content
    assert plans.current_content(1) == current.content
    with pytest.raises(ValueError):
        plans.update_alternative(1, current.id, current.revision, current.content)
    with pytest.raises(AccessDenied):
        service(authorized, 2).update_alternative(1, saved.id, saved.revision, saved.content)


def test_activate_alternative_requires_approved_plan_and_retains_previous_plan(authorized):
    plans = service(authorized, 4)
    current = plans.initialize(1)
    alternative = plans.save(1, current.id, current.revision, 'Option')
    with pytest.raises(ValueError, match='Approved'):
        plans.activate_alternative(1, alternative.id, alternative.revision)
    plans.change(1, alternative.id, alternative.revision, 'status', 'approved')
    alternative = next(row for row in plans.list_plans(1) if row.id == alternative.id)
    with pytest.raises(AccessDenied):
        service(authorized, 1).activate_alternative(1, alternative.id, alternative.revision)
    plans.activate_alternative(1, alternative.id, alternative.revision)
    saved = {row.id: row for row in plans.list_plans(1)}
    assert saved[alternative.id].is_current
    assert not saved[current.id].is_current
    assert saved[current.id].content == current.content
    with pytest.raises(ValueError):
        plans.activate_alternative(1, alternative.id, saved[alternative.id].revision)


def test_progress_is_copied_then_edited_and_activated_independently(authorized):
    from app.application.services.planning import PlanningService
    from app.infrastructure.postgresql.planning import PostgresPlanningGateway

    plans = service(authorized, 4)
    planning = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    identity = planning.create_milestone(1, 'Task', 'General', '2027-01-01', '2027-01-02', 25)
    current = next(row for row in plans.list_plans(1) if row.is_current)
    baseline = plans.baseline_current(1)
    alternative = plans.save(1, current.id, current.revision, 'Independent progress')
    assert alternative.content.tasks[0]['progress_pct'] == 25
    content = deepcopy(alternative.content)
    content.tasks[0]['progress_pct'] = 100
    plans.update_alternative(1, alternative.id, alternative.revision, content)
    planning.update_progress(identity, 50)
    saved = {row.id: row for row in plans.list_plans(1)}
    assert saved[current.id].content.tasks[0]['progress_pct'] == 50
    assert saved[baseline.id].content.tasks[0]['progress_pct'] == 25
    assert saved[alternative.id].content.tasks[0]['progress_pct'] == 100
    plans.change(1, alternative.id, saved[alternative.id].revision, 'status', 'approved')
    alternative = next(row for row in plans.list_plans(1) if row.id == alternative.id)
    plans.activate_alternative(1, alternative.id, alternative.revision)
    assert plans.current_content(1).tasks[0]['progress_pct'] == 100
    assert next(row for row in plans.list_plans(1) if row.id == current.id).content.tasks[0]['progress_pct'] == 50
