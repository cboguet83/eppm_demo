"""Reusable native Streamlit project-editor rendering helper."""


def project_screen(path, actor, operation):
    """Put production project actions/dialogs beside an independently retained shell."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_workspace
    from app.presentation.components.project_dialogs import open_create_project_dialog, open_edit_project_dialog
    from app.presentation.pages.portfolio import _render_project_create_action, _render_project_edit_action
    from app.presentation.components.portfolio_project_dialog import render_project_modal

    st.session_state["shell_runs"] = st.session_state.get("shell_runs", 0) + 1
    st.sidebar.caption("Navigation and account")
    st.write("Project summary remains mounted")
    workspace = create_project_workspace(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))
    if operation == "create":
        open_create_project_dialog(workspace)
    elif operation == "edit":
        open_edit_project_dialog(1, workspace)
    elif operation == "create_action":
        _render_project_create_action(workspace)
    else:
        _render_project_edit_action(1, workspace)
    if operation.endswith("action"):
        render_project_modal(workspace)
