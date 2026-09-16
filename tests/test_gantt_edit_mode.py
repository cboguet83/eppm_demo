"""The server rejects component mutations outside the selected edit mode."""

import pytest

from app.presentation.pages import planning_scenarios
from app.presentation.components.planning_events import validate_event


def test_server_edit_guard_defaults_to_read_only_and_protects_active_comparison(monkeypatch):
    state = {}
    monkeypatch.setattr(planning_scenarios.st, 'session_state', state)
    with pytest.raises(ValueError, match='Enable edit mode'):
        planning_scenarios.require_edit()
    state['planning_edit_enabled'] = True
    planning_scenarios.require_edit()
    state['planning_alternatives'] = {1: 5}
    with pytest.raises(ValueError, match='Only the displayed alternative'):
        planning_scenarios.require_edit()
    planning_scenarios.require_edit(alternative=True)


@pytest.mark.parametrize('action', ['toggle_edit', 'toggle_baseline'])
@pytest.mark.parametrize('enabled', [None, 1, 'true', []])
def test_gantt_mode_flags_require_real_booleans(action, enabled):
    with pytest.raises(ValueError):
        validate_event(dict(action=action, enabled=enabled))


def test_creating_alternative_requires_edit_mode(monkeypatch):
    state = {}
    monkeypatch.setattr(planning_scenarios.st, 'session_state', state)
    event = validate_event(dict(action='create_alternative', project_id='1'))
    with pytest.raises(ValueError, match='Enable edit mode'):
        planning_scenarios.handle_scenario_event(event, None)
    assert 'planning_create_scenario_project' not in state
    state['planning_edit_enabled'] = True
    planning_scenarios.handle_scenario_event(event, None)
    assert state['planning_create_scenario_project'] == 1


def test_alternative_actions_validate_plan_identity_and_operation():
    event = dict(action='alternative_action', operation='delete_step', project_id='1', plan_id='5', revision='2', id='3')
    assert validate_event(event)['plan_id'] == 5
    for field, value in [('project_id', None), ('plan_id', 0), ('revision', -1), ('id', False), ('operation', [])]:
        with pytest.raises(ValueError):
            validate_event(event | {field: value})


def test_logs_are_available_without_editing_and_hide_does_not_mutate_plans(monkeypatch):
    state = {'planning_alternatives': {1: 5}, 'planning_statuses': ['In Progress'],
             'planning_new_scenario_views': {1: 5},
             'ms_multi_projects': [1], 'planning_edit_enabled': True,
             'planning_alternative_editor': {'plan_id': 5}}
    monkeypatch.setattr(planning_scenarios.st, 'session_state', state)
    assert 'log_project_event' not in planning_scenarios.MUTATIONS
    planning_scenarios.handle_scenario_event({'action': 'hide_alternatives'}, None)
    assert state['planning_alternatives'] == {}
    assert state['planning_new_scenario_views'] == {}
    assert state['ms_multi_projects'] == [1]
    assert state['planning_statuses'] == ['In Progress']
    assert state['planning_edit_enabled'] is True
    assert 'planning_alternative_editor' not in state
