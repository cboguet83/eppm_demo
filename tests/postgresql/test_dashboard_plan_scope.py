"""Dashboard plan scope and pool filtering at the real privacy boundary."""

from copy import deepcopy
from dataclasses import replace

import psycopg
import pytest

from app.domain.access.models import AccessDenied
from tests.postgresql.test_dashboard import service
from tests.postgresql.test_pool_capacity import staffing
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
