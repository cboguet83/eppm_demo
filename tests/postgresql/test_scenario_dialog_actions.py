"""Shared resource forms must retain scenario ownership and stale-edit checks."""

from types import SimpleNamespace

import psycopg
import pytest

from app.domain.planning.plans import PlanContent
from app.domain.resources.models import PoolAssignment
from app.presentation.pages import planning_scenarios
from app.presentation.pages.planning_scenario_assignments import assignment_rows, save_assignment
from tests.postgresql.test_project_plans import draft_task, service


def test_shared_assignment_form_rejects_wrong_task_and_stale_scenario(authorized, monkeypatch):
    plans = service(authorized, 4)
    active = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Pool',2)")
    content = PlanContent(tasks=[draft_task(-1, 'Gate', '2027-01-01', '2027-01-01'),
                                 draft_task(-2, 'Build', '2027-01-03', '2027-01-07')])
    alternative = plans.save(1, active.id, active.revision, 'Option', content)
    first, second = [task['id'] for task in alternative.content.tasks]
    state = dict(planning_edit_enabled=True, planning_alternatives={1: alternative.id})
    monkeypatch.setattr(planning_scenarios.st, 'session_state', state)
    workspace = SimpleNamespace(plans=plans)
    event = dict(operation='manage_task_pools', project_id=1, plan_id=alternative.id,
                 revision=alternative.revision, id=first)
    with pytest.raises(ValueError, match='selected scenario step'):
        save_assignment(event, workspace, PoolAssignment(1, 1, 0.5, task_id=second))
    save_assignment(event, workspace, PoolAssignment(1, 1, 0.5, task_id=first,
                    schedule_anchor='start', offset_days=-1, duration_days=3))
    with pytest.raises(ValueError, match='plan changed'):
        save_assignment(event, workspace, PoolAssignment(1, 1, 0.5, task_id=first))
    saved, _ = plans.comparison(1, alternative.id)
    bounds, rows = assignment_rows(saved, first, {1: 'Pool'})
    assert bounds == ('2027-01-01', '2027-01-01')
    assert (rows[0]['effective_start_date'], rows[0]['effective_end_date']) == ('2026-12-31', '2027-01-02')
    with pytest.raises(ValueError, match='not part of this scenario step'):
        save_assignment(event | dict(revision=saved.revision, id=second), workspace, delete_id=rows[0]['id'])
    state['planning_edit_enabled'] = False
    with pytest.raises(ValueError, match='Enable edit mode'):
        save_assignment(event | dict(revision=saved.revision), workspace, delete_id=rows[0]['id'])
    assert plans.current_content(1) == active.content
