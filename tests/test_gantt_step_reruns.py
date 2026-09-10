"""Native Gantt step forms commit before a single targeted chart rerun."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.main import create_planning_service
from tests.test_business_transaction_security import business as business
from tests.test_fragment_reruns import FragmentRun


def planning_app(path, actor):
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_planning_workspace
    from app.presentation.pages.planning import render_planning_milestones

    st.session_state["shell_runs"] = st.session_state.get("shell_runs", 0) + 1
    st.sidebar.caption("Retained navigation")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_planning_milestones(create_planning_workspace(path, access=access))


@pytest.mark.parametrize("action", ["create_step_full", "update_task_full"])
def test_step_form_commits_before_one_chart_patch_and_preserves_the_shell(business, action):
    from app.presentation.pages.planning import _interactive_gantt

    path, _, _, _, manager = business
    app = AppTest.from_function(planning_app, args=(path, manager.actor), default_timeout=30)
    app.session_state["ms_multi_projects"] = [1]
    event = dict(action=action, id=10, project_id=1, task_name="Single update", phase="General",
                 start_date="2026-01-06", end_date="2026-01-08", progress_pct=25,
                 dependencies=[], description="Saved once", nonce="step-form")
    calls = []

    def render(**payload):
        calls.append(deepcopy({key: value for key, value in payload.items() if key != "on_change"}))
        return _interactive_gantt(**payload)

    run = FragmentRun("planning_lazy_gantt", widget_json=event)
    with patch("app.presentation.pages.planning._interactive_gantt", render):
        run.run(app)
    assert app.session_state["shell_runs"] == 1
    assert len(calls) == 2  # initial render and one response containing the committed step
    assert "patch" in calls[1] and "tasks" not in calls[1]
    assert calls[1]["patch"]["replace_projects"] == [1]
    assert any(task["name"] == "Single update" for task in calls[1]["patch"]["tasks"])
    assert not any(message.metadata.delta_path[0] == 1 for message in run.messages if message.WhichOneof("type") == "delta")
    service = create_planning_service(path, access=manager)
    assert sum(task["task_name"] == "Single update" for task in service.get_milestones_by_project(1)) == 1


def test_retained_gantt_create_rechecks_current_project_edit_scope(business):
    path, service, admin, editor, _ = business
    app = AppTest.from_function(planning_app, args=(path, editor.actor), default_timeout=30)
    app.session_state["ms_multi_projects"] = [1]

    def revoke():
        service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})
        for assignment in service.assignments(admin, editor.actor.user_id):
            if assignment["role"] == "project_editor":
                service.revoke(admin, assignment["id"])

    event = dict(action="create_step_full", project_id=1, task_name="Forbidden", phase="General",
                 start_date="2026-01-06", end_date="2026-01-08", progress_pct=0, dependencies=[], nonce="revoked")
    run = FragmentRun("planning_lazy_gantt", revoke, widget_json=event)
    run.run(app)
    assert any("not permitted" in error.value for error in app.error)
    assert all(task["task_name"] != "Forbidden" for task in create_planning_service(path, access=editor).get_milestones_by_project(1))
