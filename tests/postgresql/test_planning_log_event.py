"""Standalone planning event modal uses real project authorization and writes."""

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from tests.postgresql.business import business
from tests.postgresql.test_collaboration_modals import interaction


def planning_event_app(path, actor, project_id):
    """Open the composition root's shared dialog without rendering a log list."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_workspace

    st.session_state["chart_runs"] = st.session_state.get("chart_runs", 0) + 1
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    workspace = create_project_workspace(path, access=access)
    workspace.open_event_dialog(project_id)


@pytest.mark.parametrize("role", ["editor", "admin"])
def test_planning_event_saves_to_owning_project_without_rerendering_chart(pg_database, business, role):
    path, _, admin, editor, _ = business
    actor = editor.actor if role == "editor" else admin
    app = AppTest.from_function(planning_event_app, args=(path, actor, 1))
    interaction(app, "log", {"title": "Planning event", "description": "From the chart"})
    assert app.session_state["chart_runs"] == 1
    assert "project_log_1_modal_state" not in app.session_state
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT project_id,title FROM eppm.project_log_event").fetchall() == [(1, "Planning event")]


def test_planning_event_rejects_project_outside_editor_scope(business):
    path, _, _, editor, _ = business
    app = AppTest.from_function(planning_event_app, args=(path, editor.actor, 2)).run()
    assert not app.exception
    assert "read-only" in app.info[0].value
    assert "project_log_2_modal_state" not in app.session_state


@pytest.mark.parametrize("change", ["viewer", "disabled"])
def test_planning_event_reauthorizes_retained_form_before_saving(pg_database, business, change):
    path, service, admin, editor, _ = business
    app = AppTest.from_function(planning_event_app, args=(path, editor.actor, 1))

    def revoke_edit():
        if change == "disabled":
            service.set_status(admin, editor.actor.user_id, "disabled")
        else:
            for assignment in service.assignments(admin, editor.actor.user_id):
                service.revoke(admin, assignment["id"])
            service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})

    interaction(app, "log", {"title": "Forbidden"}, revoke_edit)
    assert app.session_state["project_log_1_modal_state"]["form"]["error"]
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.project_log_event").fetchone() == (0,)
