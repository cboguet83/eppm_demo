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
