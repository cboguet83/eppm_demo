"""Validate project identities sent by the Gantt log-event action."""

import pytest

from app.presentation.components.planning_events import validate_event


@pytest.mark.parametrize("project_id", [None, True, False, 0, -1, 1.5, "bad", "", 2**63])
def test_log_event_rejects_invalid_or_missing_project_identity(project_id):
    with pytest.raises(ValueError):
        validate_event({"action": "log_project_event", "project_id": project_id})


def test_log_event_normalizes_project_identity():
    assert validate_event({"action": "log_project_event", "project_id": "42"}) == {
        "action": "log_project_event", "project_id": 42,
    }
