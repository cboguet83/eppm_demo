"""Native storage authorization during real Streamlit fragment reruns."""

from unittest.mock import patch
import json
import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.operator_services import create_deployment_access_service
from tests.postgresql.test_access_presentation import access_screen, access_ui
from tests.postgresql.test_portfolio_project_modal import business, dashboard_business, runtime
from tests.test_fragment_reruns import (
    FragmentRun, navigation_app, settings_fragment_app, portfolio_app,
    project_details_fragment_app,
)



def _admin_screen(access_ui, pg_database) -> AppTest:
    path, settings, service, cookie = access_ui
    actor = service.actor(cookie)
    create_deployment_access_service(pg_database.operator_url).bootstrap(actor.user_id)
    app = AppTest.from_function(access_screen, args=(path, settings, cookie))
    app.session_state["access_selected_user"] = actor.user_id
    app.session_state["access_new_role"] = "access_admin"
    return app



def test_role_scope_rerun_preserves_account_controls_and_does_not_read_audit(access_ui, pg_database):
    from app.application.services.access import AccessService

    app = _admin_screen(access_ui, pg_database)
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



def test_retained_static_administrator_role_editor_rechecks_revoked_access(access_ui, pg_database):
    app = _admin_screen(access_ui, pg_database)
    _, _, service, cookie = access_ui

    def disable():
        # Deployment-side status change deliberately bypasses the last-admin UI guard.
        with psycopg.connect(pg_database.operator_url) as connection:
            connection.execute("UPDATE eppm.app_user SET status='disabled' WHERE id=%s", (service.actor(cookie).user_id,))

    rerun = FragmentRun("access_new_role", disable)
    rerun.run(app)
    rerun.assert_isolated()
    assert "not permitted" in app.error[0].value
    assert not any(button.key == "access_grant" for button in app.button)



def test_account_selection_rerun_does_not_reload_audit_or_sidebar(access_ui, pg_database):
    from app.application.services.access import AccessService

    app = _admin_screen(access_ui, pg_database)
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



@pytest.mark.parametrize("change", ["disabled", "revoked"])
def test_sidebar_navigation_rechecks_current_access_before_loading_the_next_page(business, change):
    path, service, admin, editor, _ = business
    app = AppTest.from_function(navigation_app, args=(path, editor.actor))

    def remove_access():
        if change == "disabled":
            service.set_status(admin, editor.actor.user_id, "disabled")
        else:
            for assignment in service.assignments(admin, editor.actor.user_id):
                service.revoke(admin, assignment["id"])

    rerun = FragmentRun("app_sidebar_nav", remove_access, widget_index=2, full_app_request=True)
    rerun.run(app)
    assert app.session_state["shell_runs"] == 2
    if change == "disabled":
        assert "not permitted" in app.error[0].value
    else:
        from app.domain.access.models import AccessDenied
        from app.main import create_planning_service

        assert app.radio(key="app_sidebar_nav").options == ["Dashboard", "Finance"]
        with pytest.raises(AccessDenied):
            create_planning_service(path, access=editor).get_totals()
    deltas = [message for message in rerun.messages if message.WhichOneof("type") == "delta"]
    assert deltas
    assert not any(message.delta.new_element.component_instance.id for message in deltas)
    for message in deltas:
        component = message.delta.new_element.bidi_component
        if not component.id:
            continue
        if component.id.endswith("-dashboard_project_table"):
            payload = json.loads(component.json)
            assert payload["rows"] == [] and payload["total"] == 0
        else:
            assert (
                component.id.endswith("-eppm_page_transition")
                or "-dashboard_filter_" in component.id
            )
    if change == "revoked":
        assert any(
            message.delta.new_element.bidi_component.id.endswith(
                "-dashboard_project_table"
            ) for message in deltas
        )
    assert not any(message.delta.new_element.HasField("dataframe") for message in deltas)



def test_settings_catalog_tab_rerun_does_not_rerun_application_shell(business):
    path, _, _, _, manager = business
    app = AppTest.from_function(settings_fragment_app, args=(path, manager.actor))
    rerun = FragmentRun("settings_tab_selection")
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
    assert not any(component.key == "portfolio_master_table" for component in app.get("bidi_component"))
    assert not any(message.delta.new_element.HasField("bidi_component") for message in rerun.messages)



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

