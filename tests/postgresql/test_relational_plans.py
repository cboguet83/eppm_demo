"""Plan-owned relational rows, operational scope and stable baseline snapshots."""

from copy import deepcopy

import psycopg
import pytest

from app.application.services.planning import PlanningService
from app.infrastructure.postgresql.planning import PostgresPlanningGateway
from app.domain.resources.models import PoolAssignment
from tests.postgresql.test_project_plans import service, draft_task
from tests.postgresql.test_resource_pools import service as pool_service


def test_activation_selects_existing_rows_and_preserves_inactive_schedule(authorized):
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    planning = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    identity = planning.create_milestone(1, 'Current', 'General', '2027-01-01', '2027-01-05', 0)
    baseline = plans.baseline_current(1)
    assert baseline.id != initial.id and baseline.is_baseline and not baseline.is_current
    assert planning.update_dates(identity, '2027-02-01', '2027-02-05')
    initial = next(plan for plan in plans.list_plans(1) if plan.is_current)
    alternative_content = deepcopy(initial.content)
    alternative_content.tasks[0]['start_date'] = '2027-03-01'
    alternative_content.tasks[0]['end_date'] = '2027-03-05'
    alternative = plans.save(1, initial.id, initial.revision, 'Alternative', alternative_content)
    plans.change(1, alternative.id, alternative.revision, 'status', 'approved')
    alternative = next(plan for plan in plans.list_plans(1) if plan.id == alternative.id)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        before = connection.execute('SELECT id,project_plan_id,stable_task_id,start_date FROM eppm.project_task ORDER BY id').fetchall()
        assert len(before) == 3
    plans.change(1, alternative.id, alternative.revision, 'current', 'true')
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT id,project_plan_id,stable_task_id,start_date FROM eppm.project_task ORDER BY id').fetchall() == before
        assert connection.execute("SELECT start_date::text FROM eppm.current_project_task").fetchall() == [('2027-03-01',)]
        assert connection.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='eppm' AND table_name='project_plan' AND column_name='content'").fetchone() == (0,)
    saved = {plan.id: plan for plan in plans.list_plans(1)}
    assert saved[initial.id].content.tasks[0]['start_date'] == '2027-02-01'
    assert saved[baseline.id].content.tasks[0]['start_date'] == '2027-01-01'
    assert saved[initial.id].content.tasks[0]['id'] == saved[alternative.id].content.tasks[0]['id']


def test_demand_excludes_inactive_baseline_and_deleted_plans(authorized):
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(name,capacity_fte) VALUES('Pool',5)")
    content = deepcopy(initial.content)
    content.tasks.append(draft_task())
    content.assignments.append(PoolAssignment(pool_id=1, project_id=1, fte_assigned=3, task_id=-1))
    alternative = plans.save(1, initial.id, initial.revision, 'Demand option', content)
    pools = pool_service(authorized)
    assert pools.get_assignments() == []
    plans.change(1, alternative.id, alternative.revision, 'status', 'approved')
    alternative = plans.list_plans(1)[0]
    plans.change(1, alternative.id, alternative.revision, 'current', 'true')
    assert len(pools.get_assignments()) == 1
    baseline = plans.baseline_current(1)
    assert len(pools.get_assignments()) == 1
    active = next(plan for plan in plans.list_plans(1) if plan.is_current)
    plans.change(1, active.id, active.revision, 'status', 'deleted')
    assert pools.get_assignments() == []
    assert plans.baseline_projects() == [1]
    assert len(plans.baseline_tasks([1])[1]) == 1
    assert not any(plan.is_current for plan in plans.list_plans(1))
    assert baseline.is_baseline


def test_cross_project_links_follow_active_task_identity_and_actual_progress(authorized):
    plans = service(authorized, 4)
    plans.initialize(1)
    plans.initialize(2)
    planning = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    predecessor = planning.create_milestone(1, 'Predecessor', 'General', '2027-01-01', '2027-01-05', 65)
    successor = planning.create_milestone(2, 'Consumer', 'General', '2027-01-06', '2027-01-08', 0,
        predecessor_id=predecessor,
        dependencies=[dict(predecessor_task_id=predecessor, predecessor_project_id=None, link_type='FS', lag_days=0)])
    current = plans.list_plans(1)[0]
    content = deepcopy(current.content)
    content.tasks[0]['end_date'] = '2027-01-12'
    alternative = plans.save(1, current.id, current.revision, 'Late', content)
    plans.change(1, alternative.id, alternative.revision, 'status', 'approved')
    alternative = plans.list_plans(1)[0]
    plans.change(1, alternative.id, alternative.revision, 'current', 'true')
    dependencies = planning.get_task_dependencies(successor)
    assert dependencies[0]['pred_end_date'] == '2027-01-12'
    active = planning.get_milestones_by_project(1)
    assert planning.get_milestone_by_id(successor)['predecessor_id'] == active[0]['id']
    assert next(row for row in plans.task_choices() if row['project_id'] == 1)['id'] == predecessor
    assert len(active) == 1 and active[0]['progress_pct'] == 65
    baseline = plans.baseline_current(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        baseline_task = connection.execute('SELECT id FROM eppm.project_task WHERE project_plan_id=%s', (baseline.id,)).fetchone()[0]
    assert not planning.update_dates(baseline_task, '2028-01-01', '2028-01-02')
    assert plans.list_plans(1)[0].content.tasks[0]['end_date'] == '2027-01-12'
    assert service(authorized, 2).list_plans(1) == []


def test_plan_constraints_reject_second_active_and_cross_plan_assignment(authorized):
    plans = service(authorized, 4)
    current = plans.initialize(1)
    content = deepcopy(current.content)
    content.tasks.append(draft_task())
    alternative = plans.save(1, current.id, current.revision, 'Alternative', content)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(name,capacity_fte) VALUES('Pool',5)")
        task = connection.execute('SELECT id FROM eppm.project_task WHERE project_plan_id=%s', (alternative.id,)).fetchone()[0]
        with pytest.raises(psycopg.errors.UniqueViolation), connection.transaction():
            connection.execute('UPDATE eppm.project_plan SET is_current=true WHERE id=%s', (alternative.id,))
        with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
            connection.execute('''INSERT INTO eppm.resource_pool_assignment
                (project_plan_id,project_id,pool_id,task_id,fte_assigned) VALUES(%s,1,1,%s,1)''', (current.id, task))
    assert next(plan for plan in plans.list_plans(1) if plan.is_current).id == current.id


def test_baseline_replacement_retains_frozen_history_and_read_view_rejects_writes(authorized):
    plans = service(authorized, 4)
    planning = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    task = planning.create_milestone(1, 'Task', 'General', '2027-01-01', '2027-01-05', 0)
    old = plans.baseline_current(1)
    planning.update_dates(task, '2027-02-01', '2027-02-05')
    new = plans.baseline_current(1)
    saved = {plan.id: plan for plan in plans.list_plans(1)}
    assert saved[old.id].is_frozen and not saved[old.id].is_baseline
    assert saved[new.id].is_baseline and saved[new.id].is_frozen
    assert authorized.query('UPDATE eppm.project_task SET task_name=%s WHERE project_plan_id=%s RETURNING id',
        ('Changed', old.id), user_id=4, write=True) == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query('UPDATE eppm.current_project_task SET task_name=%s', ('Changed',), user_id=4, write=True)


def test_deleting_project_cascades_its_plans_and_frozen_children_atomically(authorized):
    from app.infrastructure.postgresql.projects import PostgresProjectGateway
    plans = service(authorized, 4)
    planning = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    first = planning.create_milestone(1, 'First', 'General', '2027-01-01', '2027-01-05', 0)
    planning.create_milestone(1, 'Second', 'General', '2027-01-06', '2027-01-07', 0, predecessor_id=first)
    plans.baseline_current(1)
    gateway = PostgresProjectGateway(authorized.database, authorized.key, access=authorized.binding(4).access)
    assert gateway.run(lambda store: store.delete(1), write=True)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.project_plan WHERE project_id=1').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.project_task WHERE project_id=1').fetchone() == (0,)


def test_revision_inherits_allocations_and_removed_tasks_release_only_revision_demand(authorized):
    plans = service(authorized, 4)
    planning = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    keep = planning.create_milestone(1, 'Keep', 'General', '2027-01-01', '2027-01-05', 0)
    remove = planning.create_milestone(1, 'Remove', 'General', '2027-01-01', '2027-01-05', 0)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(name,capacity_fte) VALUES('Pool',5)")
    pools = pool_service(authorized)
    for task, fte in ((keep, 1), (remove, 2), (None, 0.5)):
        pools.create_assignment(PoolAssignment(pool_id=1, project_id=1, task_id=task, fte_assigned=fte))
    source = next(plan for plan in plans.list_plans(1) if plan.is_current)
    inherited = plans.save(1, source.id, source.revision, 'Copied allocations')
    assert inherited.content.assignments == source.content.assignments
    assert len(pools.get_assignments()) == 3
    edited = deepcopy(inherited.content)
    edited.tasks = [task for task in edited.tasks if task['id'] != remove] + [draft_task(-1, 'New task')]
    revised = plans.save(1, inherited.id, inherited.revision, 'Removed task', edited)
    assert {row.task_id for row in revised.content.assignments} == {keep, None}
    added = next(task for task in revised.content.tasks if task['task_name'] == 'New task')
    assert not any(row.task_id == added['id'] for row in revised.content.assignments)
    assert len(next(plan for plan in plans.list_plans(1) if plan.id == source.id).content.assignments) == 3
    plans.change(1, revised.id, revised.revision, 'status', 'approved')
    revised = plans.list_plans(1)[0]
    plans.change(1, revised.id, revised.revision, 'current', 'true')
    assert sum(row['fte_assigned'] for row in pools.get_assignments()) == 1.5
