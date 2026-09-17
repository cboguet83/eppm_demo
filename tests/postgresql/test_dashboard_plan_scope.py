"""Dashboard plan scope and pool filtering at the real privacy boundary."""

from copy import deepcopy
from dataclasses import replace

import psycopg
import pytest

from app.domain.access.models import AccessDenied
from app.domain.resources.capacity import calculate_capacity
from tests.postgresql.test_dashboard import service
from tests.postgresql.test_pool_capacity import staffing, reference_inputs, DAY
from tests.postgresql.test_project_plans import service as plan_service


def test_dashboard_ignores_baselines_drafts_deleted_plans_and_tracks_activation(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("SELECT setval('eppm.project_task_id_seq', (SELECT max(id) FROM eppm.project_task))")
    dashboard = service(staffing)
    before = dashboard.resource_breakdown([1])
    plans = plan_service(staffing, 4)
    for project in (1, 3):
        active = plans.initialize(project)
        plans.baseline_current(project)
        content = deepcopy(active.content)
        for task in content.tasks:
            task['end_date'] = '2029-12-31'
        content.assignments = [replace(row, fte_assigned=100) for row in content.assignments]
        draft = plans.save(project, active.id, active.revision, 'High demand draft', content)
        deleted = plans.save(project, active.id, active.revision, 'Deleted draft', content)
        plans.change(project, deleted.id, deleted.revision, 'status', 'deleted')
        assert dashboard.resource_breakdown([1]) == before
    # Activating a hidden competitor changes aggregate demand without exposing it.
    plans.change(3, draft.id, draft.revision, 'status', 'approved')
    approved = next(plan for plan in plans.list_plans(3) if plan.id == draft.id)
    revision = dashboard.revision()
    plans.change(3, approved.id, approved.revision, 'current', 'true')
    assert dashboard.revision() != revision
    after = dashboard.resource_breakdown([1])
    assert after['allocation']['2026-Q1'] > before['allocation']['2026-Q1']
    assert after['overallocation']['2026-Q1'] > before['overallocation']['2026-Q1']
    assert dashboard.consuming_projects([1], '2026-Q1') == [1, 2]


def test_single_pool_filter_recalculates_own_peaks_capacity_and_rejects_unrelated_pool(staffing):
    dashboard = service(staffing)
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.resource_pool_assignment
            (pool_id,project_id,fte_assigned,start_date,end_date,project_plan_id)
            VALUES(2,1,3,'2026-02-01','2026-02-02',
                (SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))""")
    all_pools = dashboard.resource_breakdown([1])
    selected = dashboard.resource_breakdown([1], 2)
    assert [pool['pool_id'] for pool in selected['pools']] == [2]
    assert selected['allocation']['2026-Q1'] == 3
    assert selected['overallocation']['2026-Q1'] == 1
    assert selected['capacity']['2026-Q1'] == 2
    assert selected['peak_days']['allocation']['2026-Q1'] == '2026-02-01'
    assert all_pools['peak_days']['allocation']['2026-Q1'] != '2026-02-01'
    with pytest.raises(AccessDenied):
        dashboard.resource_breakdown([1], 6)
    for identity in (True, -1, '2'):
        with pytest.raises(ValueError):
            dashboard.resource_breakdown([1], identity)


def test_status_filter_excludes_competing_demand_and_drill_through_consumers(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status=CASE id WHEN 1 THEN 'In Progress' WHEN 2 THEN 'Completed' ELSE 'Draft' END")
        connection.execute('DELETE FROM eppm.resource_pool_mapping WHERE pool_id=1')
        connection.execute('UPDATE eppm.resource_pool SET capacity_fte=1 WHERE id=1')
    dashboard = service(staffing, 4)
    active = dashboard.resource_breakdown([1], statuses=['In Progress'], pool_ids=[1])
    completed = dashboard.resource_breakdown([1, 2], statuses=['In Progress', 'Completed'], pool_ids=[1])
    all_statuses = dashboard.resource_breakdown([1], statuses=[], pool_ids=[1])
    assert active['allocation']['2026-Q1'] == 1
    assert completed['allocation']['2026-Q1'] == 1.5
    assert all_statuses['allocation']['2026-Q1'] == 21.5
    assert active['overallocation']['2026-Q1'] < completed['overallocation']['2026-Q1'] < all_statuses['overallocation']['2026-Q1']
    inputs = reference_inputs(staffing, [1])[1]
    for project_ids, chart in [({1}, active), ({1, 2}, completed), ({1, 2, 3}, all_statuses)]:
        detail = calculate_capacity(replace(inputs, assignments=[row for row in inputs.assignments
                                                                if row['project_id'] in project_ids]), DAY)
        assert chart['allocation']['2026-Q1'] == max(detail.daily_usage.values())
        assert chart['overallocation']['2026-Q1'] == max((row.excess_fte for row in detail.daily_overassignments), default=0)
    assert dashboard.consuming_projects([1], '2026-Q1', 1, 'allocation', statuses=['In Progress']) == [1]
    assert dashboard.consuming_projects([1], '2026-Q1', 1, 'allocation', statuses=['In Progress', 'Completed']) == [1, 2]
    assert dashboard.resource_breakdown([2], statuses=['In Progress'])['pools'] == []
    assert dashboard.resource_breakdown([1], statuses=['In Progress'], pool_ids=[])['pools'] == []
    assert {pool['pool_id'] for pool in dashboard.resource_breakdown([1], statuses=['In Progress'], pool_ids=[1, 2])['pools']} == {1, 2}
    with pytest.raises(ValueError, match='statuses'):
        dashboard.resource_breakdown([1], statuses=['invalid'])


def test_individual_pool_peaks_keep_distinct_dates_without_summing_them(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.resource_pool_assignment')
        connection.execute('DELETE FROM eppm.resource_pool_mapping')
        connection.execute('UPDATE eppm.resource_pool SET capacity_fte=2')
        connection.execute("""INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date,project_plan_id)
            SELECT pool_id,1,fte,day,day,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)
            FROM (VALUES(1,10,'2026-01-01'::date),(2,8,'2026-02-01'::date)) rows(pool_id,fte,day)""")
    result = service(staffing, 4).resource_breakdown([1])
    assert result['allocation']['2026-Q1'] == 10
    assert result['overallocation']['2026-Q1'] == 8
    first, second = result['individual_pools']
    assert first['allocation']['2026-Q1'] == 10
    assert second['allocation']['2026-Q1'] == 8
    assert second['overallocation']['2026-Q1'] == 6
    assert second['available']['2026-Q1'] == -6
    assert second['capacity']['2026-Q1'] == 2
