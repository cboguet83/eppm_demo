"""Dispatch real Streamlit fragment requests against isolated authorized storage."""

from collections.abc import Callable
from dataclasses import dataclass, field
from unittest.mock import patch

import pytest
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.runtime.scriptrunner import RerunData, ScriptRunnerEvent
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.local_script_runner import LocalScriptRunner

from app.application.services.access import DeploymentAccessService
from tests.test_access_presentation import access_screen, access_ui as access_ui
from tests.test_business_transaction_security import business as business
from tests.test_scoped_portfolio_collaboration_ui import portfolio_app, project_details_fragment_app


@dataclass
class FragmentRun:
    """Collect only the rerun output, retaining Streamlit's real widget dispatch."""

    widget_key: str
    before_rerun: Callable[[], None] = lambda: None
    fragment_id: str = ""
    dispatched: bool = False
    messages: list[ForwardMsg] = field(default_factory=list)

    def runner(self, *args, **kwargs) -> LocalScriptRunner:
        runner = LocalScriptRunner(*args, **kwargs)

        def event_received(sender, event, **event_data):
            if event == ScriptRunnerEvent.ENQUEUE_FORWARD_MSG:
                message = event_data["forward_msg"]
                if self.dispatched:
                    self.messages.append(message)
                elif message.WhichOneof("type") == "delta":
                    delta = message.delta
                    identifiers = (
                        delta.new_element.selectbox.id,
                        delta.new_element.radio.id,
                        delta.new_element.bidi_component.id,
                        delta.add_block.tab_container.id,
                    )
                    if any(identifier.endswith("-" + self.widget_key) for identifier in identifiers):
                        self.fragment_id = delta.fragment_id
            if event == ScriptRunnerEvent.SCRIPT_STOPPED_WITH_SUCCESS and not self.dispatched:
                assert self.fragment_id, "The interactive control must belong to a fragment"
                self.before_rerun()
                self.dispatched = True
                runner.request_rerun(RerunData(
                    widget_states=WidgetStates(widgets=runner._session_state.get_widget_states()),
                    fragment_id_queue=[self.fragment_id],
                ))

        runner.on_event.connect(event_received, weak=False)
        return runner

    def run(self, app: AppTest) -> AppTest:
        """Queue the browser-equivalent fragment request after initial rendering."""
        with patch("streamlit.testing.v1.app_test.LocalScriptRunner", self.runner):
            app.run(timeout=30)
        assert self.dispatched and self.messages
        assert not app.exception
        return app

    def assert_isolated(self) -> None:
        """No navigation or sibling-fragment deltas may be sent on a local update."""
        deltas = [message for message in self.messages if message.WhichOneof("type") == "delta"]
        assert deltas
        assert all(message.delta.fragment_id == self.fragment_id for message in deltas)
        assert all(message.metadata.delta_path[0] != 1 for message in deltas)


def _admin_screen(access_ui) -> AppTest:
    import secrets
    import time

    path, settings, service, cookie = access_ui
    actor = service.actor(cookie)
    DeploymentAccessService(service.gateway, lambda: int(time.time()), "fragment-test",
                            lambda: secrets.token_urlsafe(16)).bootstrap(actor.user_id)
    app = AppTest.from_function(access_screen, args=(path, settings, cookie))
    app.session_state["access_selected_user"] = actor.user_id
    app.session_state["access_new_role"] = "access_admin"
    return app


def test_role_scope_rerun_preserves_account_controls_and_does_not_read_audit(access_ui):
    from app.application.services.access import AccessService

    app = _admin_screen(access_ui)
    audit_reads = []
    real_audit = AccessService.audit

    def audit(service, actor):
        audit_reads.append(actor.user_id)
        return real_audit(service, actor)

    rerun = FragmentRun("access_new_role")
    with patch.object(AccessService, "audit", audit):
        rerun.run(app)
    rerun.assert_isolated()
    assert len(audit_reads) == 1
    assert app.selectbox(key="access_selected_user")
    assert not app.error


def test_retained_static_administrator_role_editor_rechecks_revoked_access(access_ui):
    app = _admin_screen(access_ui)
    _, _, service, cookie = access_ui

    def disable():
        # Deployment-side status change deliberately bypasses the last-admin UI guard.
        with service.gateway.transaction(write=True) as store:
            store.set_status(service.actor(cookie).user_id, "disabled", 1)

    rerun = FragmentRun("access_new_role", disable)
    rerun.run(app)
    rerun.assert_isolated()
    assert "not permitted" in app.error[0].value
    assert not any(button.key == "access_grant" for button in app.button)


def test_account_selection_rerun_does_not_reload_audit_or_sidebar(access_ui):
    from app.application.services.access import AccessService

    app = _admin_screen(access_ui)
    real_audit = AccessService.audit
    reads = []

    def audit(service, actor):
        reads.append(actor.user_id)
        return real_audit(service, actor)

    rerun = FragmentRun("access_selected_user")
    with patch.object(AccessService, "audit", audit):
        rerun.run(app)
    assert len(reads) == 1
    assert not app.error
    deltas = [message for message in rerun.messages if message.WhichOneof("type") == "delta"]
    assert deltas and all(message.delta.fragment_id for message in deltas)
    assert all(message.metadata.delta_path[0] != 1 for message in deltas)


def settings_fragment_app(path, actor):
    """Render real protected Settings with a shell counter outside its fragment."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_settings_workspace
    from app.presentation.pages.settings import render_settings_view

    st.session_state["shell_runs"] = st.session_state.get("shell_runs", 0) + 1
    st.sidebar.caption("Navigation remains mounted")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_settings_view(create_settings_workspace(path, access=access))


def test_settings_section_rerun_does_not_rerun_application_shell(business):
    path, _, _, _, manager = business
    app = AppTest.from_function(settings_fragment_app, args=(path, manager.actor))
    rerun = FragmentRun("rb_settings_section")
    rerun.run(app)
    rerun.assert_isolated()
    assert not app.error
    assert app.session_state["shell_runs"] == 1


def test_master_grid_paging_does_not_rebuild_catalog_controls_or_selected_project(business):
    from app.presentation.pages import portfolio
    from app.application.services.portfolio import PortfolioService

    path, _, _, editor, _ = business
    app = AppTest.from_function(portfolio_app, args=(path, editor.actor))
    app.session_state["selected_portfolio_project_id"] = 1
    catalog_reads = []
    initial_reads = []
    real_catalog = PortfolioService.get_catalog

    def catalog(service, **kwargs):
        catalog_reads.append(1)
        return real_catalog(service, **kwargs)

    rerun = FragmentRun("portfolio_master_table", lambda: initial_reads.append(len(catalog_reads)))
    with patch.object(PortfolioService, "get_catalog", catalog), patch.object(
        portfolio, "_render_project_details_body", wraps=portfolio._render_project_details_body,
    ) as summary:
        rerun.run(app)
    rerun.assert_isolated()
    assert not app.error
    assert summary.call_count == 1
    assert len(catalog_reads) == initial_reads[0]


def test_retained_master_grid_rechecks_access_before_serving_its_cached_page(business):
    path, service, admin, editor, _ = business
    app = AppTest.from_function(portfolio_app, args=(path, editor.actor))
    rerun = FragmentRun("portfolio_master_table", lambda: service.set_status(admin, editor.actor.user_id, "disabled"))
    rerun.run(app)
    rerun.assert_isolated()
    assert "not permitted" in app.error[0].value
    assert not app.get("bidi_component")


def test_project_section_rerun_preserves_summary_and_loads_only_active_section(business):
    from app.presentation.pages import portfolio

    path, _, _, editor, _ = business
    app = AppTest.from_function(project_details_fragment_app, args=(path, editor.actor))
    rerun = FragmentRun("project_details_tabs_1")
    with patch.object(portfolio, "_render_project_details_body", wraps=portfolio._render_project_details_body) as summary:
        rerun.run(app)
    rerun.assert_isolated()
    assert summary.call_count == 1
    assert not app.error
    assert app.button(key="btn_edit_details_1")


@pytest.mark.parametrize("change", ["disabled", "revoked", "deleted"])
def test_project_section_rerun_handles_current_access_or_deleted_project(business, change):
    from app.main import create_project_service

    path, service, admin, editor, manager = business
    actor = manager.actor if change == "deleted" else editor.actor
    app = AppTest.from_function(project_details_fragment_app, args=(path, actor))

    def remove_access():
        if change == "disabled":
            service.set_status(admin, editor.actor.user_id, "disabled")
        elif change == "revoked":
            for assignment in service.assignments(admin, editor.actor.user_id):
                service.revoke(admin, assignment["id"])
        else:
            create_project_service(path, access=manager).delete_project(1)

    rerun = FragmentRun("project_details_tabs_1", remove_access)
    rerun.run(app)
    rerun.assert_isolated()
    if change == "deleted":
        assert app.info[0].value == "The selected project no longer exists."
    else:
        assert "not permitted" in app.error[0].value
    assert not app.tabs
