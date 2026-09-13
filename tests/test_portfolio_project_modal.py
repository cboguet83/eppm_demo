"""Storage-independent project modal interaction helpers."""

from copy import deepcopy
from streamlit.testing.v1 import AppTest
from tests.test_fragment_reruns import FragmentRun

def workflow_app(path, actor):
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_workspace
    from app.presentation.pages.portfolio import render_portfolio_overview
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    st.session_state["shell_runs"] = st.session_state.get("shell_runs", 0) + 1
    st.sidebar.caption("Retained navigation")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_portfolio_overview(create_project_workspace(path, access=access))



def open_form(path, actor, operation="edit"):
    app = AppTest.from_function(workflow_app, args=(path, actor), default_timeout=30)
    if operation == "edit":
        app.session_state["selected_portfolio_project_id"] = 1
    key = "btn_create_project_from_portfolio" if operation == "create" else "btn_edit_details_1"
    FragmentRun(key, widget_trigger=True).run(app)
    assert app.session_state["shell_runs"] == 1
    return app



def submit(app, kind="save", changes=None, links=None, before=None, mutate=None):
    def prepare():
        draft = app.session_state["portfolio_project_modal_state"]
        values = deepcopy(draft.form["values"])
        for field in draft.form["fields"]:
            if field["kind"] not in {"number", "multi", "tags"}:
                values[field["key"]] = "" if values[field["key"]] is None else str(values[field["key"]])
        values.update(changes or {})
        event = dict(kind=kind, token=draft.token, values=values,
                     links=links if links is not None else draft.form["links"], dirty=list(changes or {}))
        if mutate:
            mutate(event)
        if before:
            before()
        run.widget_json = {"action": event}

    before_shell = app.session_state["shell_runs"]
    run = FragmentRun("portfolio_project_form", prepare)
    run.run(app)
    assert app.session_state["shell_runs"] == before_shell + 1
    assert all(message.metadata.delta_path[0] != 1 for message in run.messages if message.WhichOneof("type") == "delta")
    return run
