"""Live rescheduling leaves immutable plan and baseline snapshots untouched."""

from datetime import date

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.application.services.planning import PlanningService
from app.domain.access.models import AccessDenied
from app.infrastructure.postgresql.planning import PostgresPlanningGateway
from tests.postgresql.test_project_plans import service


def test_drag_changes_live_dates_without_creating_plan_or_moving_baseline(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date,project_plan_id) VALUES (1,'Task','2027-01-01','2027-01-05',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
    plans = service(authorized, 4)
    assert plans.baseline_projects() == []
    baseline = plans.baseline_current(1)
    assert plans.baseline_projects() == [1]
    editor = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(1).access))
    assert editor.update_dates(1, '2027-02-01', '2027-02-05')
    saved = plans.list_plans(1)
    assert len(saved) == 2 and saved[0].id == baseline.id and saved[0].is_baseline
    assert saved[0].content.tasks[0]['start_date'] == '2027-01-01'
    assert saved[0].revision == baseline.revision
    assert plans.current_content(1).tasks[0]['start_date'] == '2027-02-01'
    assert plans.baseline_tasks([1])[1][0]['start_date'] == '2027-01-01'
    assert authorized.query('SELECT start_date FROM eppm.project_task WHERE id=1') == [(date(2027, 2, 1),)]
    with pytest.raises(AccessDenied):
        service(authorized, 1).baseline_current(1)
    refreshed = plans.baseline_current(1)
    assert refreshed.id != baseline.id and not refreshed.is_current and refreshed.is_baseline
    assert refreshed.content.tasks[0]['start_date'] == '2027-02-01'
    assert len(plans.list_plans(1)) == 3
    assert plans.baseline_current(1).id == refreshed.id
    assert len(plans.list_plans(1)) == 3


def test_scoped_approver_can_capture_latest_dates_but_cannot_reschedule(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('''INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES(3,'project_approver',%s,900,'test')''', (Jsonb({'kind': 'projects', 'project_ids': [1]}),))
        connection.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date,project_plan_id) VALUES (1,'Task','2027-01-01','2027-01-05',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
    approver = service(authorized, 3)
    approver.baseline_current(1)
    planning = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(3).access))
    with pytest.raises(AccessDenied):
        planning.update_dates(1, '2027-02-01', '2027-02-05')
    with pytest.raises(AccessDenied):
        approver.baseline_current(2)
    assert approver.baseline_tasks([1, 2]).keys() == {1}
    assert service(authorized, 2).baseline_tasks([1]) == {}
    assert service(authorized, 2).baseline_projects() == []
