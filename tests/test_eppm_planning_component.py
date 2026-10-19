"""Verify EPPM's Python adapter retains widget callbacks and wire acknowledgments."""

from unittest.mock import Mock

import pytest

from app.presentation.components import planning_component
from app.presentation.pages import planning


@pytest.mark.parametrize("event", [None, {}, {"nonce": 7}, {"nonce": "request"}])
def test_component_acknowledges_string_nonce_and_preserves_callback(
    monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    """A rerun acknowledges delivery without rewriting Streamlit widget state."""
    state = {"instance": event}
    component = Mock(return_value=event)
    declare = Mock(return_value=component)
    callback = Mock()
    monkeypatch.setattr(planning_component.st, "session_state", state)
    monkeypatch.setattr(planning_component.components, "declare_component", declare)

    result = planning_component.render_planning_component(
        key="instance", on_change=callback, tasks=[]
    )

    assert result is event
    assert state["instance"] is event
    arguments = component.call_args.kwargs
    assert arguments["on_change"] is callback
    assert arguments["tasks"] == []
    assert arguments.get("ack_nonce") == (
        "request" if event == {"nonce": "request"} else None
    )
    assert declare.call_args.args == ("interactive_gantt",)
    assert declare.call_args.kwargs["path"].endswith("components/gantt")


@pytest.mark.parametrize("action", ["update_dates", "update_alternative_dates"])
def test_failed_edit_callback_provides_a_correlated_browser_rejection(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """Application failures survive the rerun as safe draft-preserving responses."""
    event = {
        "action": action, "id": 7, "project_id": 1, "plan_id": 2,
        "revision": 4, "start_date": "2027-01-01",
        "end_date": "2027-01-05", "nonce": "edit-request",
    }
    state = {"instance": event, "planning_edit_enabled": True}
    workspace = Mock()
    workspace.planning.update_dates.side_effect = ValueError("Source changed.")
    scenario = Mock(side_effect=ValueError("Source changed."))
    monkeypatch.setattr(planning.st, "session_state", state)
    monkeypatch.setattr(planning, "handle_scenario_event", scenario)

    planning._handle_gantt_component_change("instance", workspace)
    planning._handle_gantt_component_change("instance", workspace)

    assert state["planning_step_form_error"] == "Source changed."
    assert state["last_gantt_nonce"] == "edit-request"
    assert "planning_pending_change" not in state
    if action == "update_dates":
        workspace.planning.update_dates.assert_called_once()
    else:
        scenario.assert_called_once()


@pytest.mark.parametrize('rejected', [False, True])
def test_direct_link_callback_appends_once_and_refreshes_authoritative_data(
    monkeypatch: pytest.MonkeyPatch, rejected: bool,
) -> None:
    """A repeated rerun cannot duplicate the append; safe errors reach the adapter."""
    event = dict(action='create_dependency', project_id=1, task_id=7,
                 predecessor_task_id=None, predecessor_project_id=2,
                 link_type='FS', lag_days=0, source_tokens={'1': 'a', '2': 'b'}, nonce='create-link')
    state = {'instance': event, 'planning_edit_enabled': True, 'planning_chart_snapshot': {'old': True}}
    workspace = Mock()
    if rejected:
        workspace.planning.create_dependency.side_effect = ValueError('Source changed.')
    monkeypatch.setattr(planning.st, 'session_state', state)
    planning._handle_gantt_component_change('instance', workspace)
    planning._handle_gantt_component_change('instance', workspace)
    workspace.planning.create_dependency.assert_called_once_with(
        1, 7, dict(predecessor_task_id=None, predecessor_project_id=2, link_type='FS', lag_days=0), {1: 'a', 2: 'b'})
    assert 'planning_chart_snapshot' not in state
    assert state.get('planning_step_form_error') == ('Source changed.' if rejected else None)
