"""Scoped portfolio component requests and collaboration workflows on real PostgreSQL."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import Actor
from app.runtime import RuntimeResources
from app.main import create_collaboration_service
from tests.postgresql.business import business


def portfolio_app(path: RuntimeResources, actor: Actor) -> None:
    """Inject only the authenticated transport into the production portfolio page."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_workspace
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.portfolio import render_portfolio_overview

    set_current_locale("en")
    if st.session_state.get("nav_redirect"):
        st.caption(st.session_state["nav_redirect"])
        return
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_portfolio_overview(create_project_workspace(path, access=access))


def project_details_fragment_app(path: RuntimeResources, actor: Actor) -> None:
    """Rerun the production details fragment with its previously displayed row."""
    import pandas as pd
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_workspace
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.portfolio import _render_project_details_panel

    set_current_locale("en")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    selected = pd.Series({"id": 1, "name": "Visible", "planned_budget": "0", "actual_budget": "0"})
    _render_project_details_panel(selected, pd.DataFrame(), create_project_workspace(path, access=access))


@pytest.mark.parametrize("change", ["disabled", "revoked"])
def test_project_details_fragment_handles_lost_access_without_exposing_a_script_error(business, change):
    path, service, admin, editor, _ = business
    app = AppTest.from_function(project_details_fragment_app, args=(path, editor.actor)).run()
    assert not app.exception and not app.error
    if change == "disabled":
        service.set_status(admin, editor.actor.user_id, "disabled")
    else:
        for assignment in service.assignments(admin, editor.actor.user_id):
            service.revoke(admin, assignment["id"])
    app.run()
    assert not app.exception and "not permitted" in app.error[0].value
    assert not app.button and not app.tabs


def test_project_details_fragment_stops_displaying_a_deleted_project(business):
    from app.main import create_project_service

    path, _, _, _, manager = business
    app = AppTest.from_function(project_details_fragment_app, args=(path, manager.actor)).run()
    assert not app.exception and not app.error
    create_project_service(path, access=manager).delete_project(1)
    app.run()
    assert not app.exception and not app.error
    assert app.info[0].value == "The selected project no longer exists."
    assert not app.button and not app.tabs


def test_business_administrator_can_open_project_creation_from_the_scoped_portfolio(pg_database, business):
    from tests.test_fragment_reruns import FragmentRun
    path, _, _, _, manager = business
    with patch("app.presentation.pages.portfolio.portfolio_project_table"):
        app = AppTest.from_function(portfolio_app, args=(path, manager.actor), default_timeout=30)
        FragmentRun("btn_create_project_from_portfolio", widget_trigger=True).run(app)
    assert not app.exception and not app.error
    assert app.session_state["portfolio_project_modal_state"].form["submit"] == "Create project"
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT id FROM eppm.project ORDER BY id").fetchall() == [(1,), (2,)]


@pytest.mark.parametrize("field", ["row_click", "gantt_click"])
@pytest.mark.parametrize("value", [[], {}, True, 1.5, "1", 0, -1, float("inf")])
def test_malformed_portfolio_identifiers_are_ignored_before_navigation_or_details(business, field, value):
    path, _, _, editor, _ = business
    with patch("app.presentation.pages.portfolio.portfolio_project_table") as table:
        app = AppTest.from_function(portfolio_app, args=(path, editor.actor))
        app.session_state["portfolio_master_table"] = {field: value}
        app.run()
    assert not app.exception and not app.error
    assert [row["project_id"] for row in table.call_args.args[0]] == [1]
    assert "nav_redirect" not in app.session_state
    assert "selected_portfolio_project_id" not in app.session_state
    assert not app.subheader[1:]


@pytest.mark.parametrize("field", ["row_click", "gantt_click"])
@pytest.mark.parametrize("project_id", [1, 2, 999])
def test_portfolio_navigation_resolves_current_read_scope(business, field, project_id):
    path, _, _, editor, _ = business
    with patch("app.presentation.pages.portfolio.portfolio_project_table"):
        app = AppTest.from_function(portfolio_app, args=(path, editor.actor))
        app.session_state["portfolio_master_table"] = {field: project_id}
        app.session_state["active_resource_pool_filter"] = {"pool_id": 1}
        app.session_state["pending_resource_pool_filter"] = {"pool_id": 1}
        app.run()
        assert not app.exception and not app.error
        if field == "gantt_click" and project_id == 1:
            assert app.session_state["target_planning_project_id"] == 1
            assert app.session_state["nav_redirect"] == "2. Planning & Step Loader"
            assert "active_resource_pool_filter" not in app.session_state
            assert "pending_resource_pool_filter" not in app.session_state
        else:
            assert "nav_redirect" not in app.session_state
            buttons = [button.key for button in app.button]
            assert ("btn_edit_details_1" in buttons) == (field == "row_click" and project_id == 1)


@pytest.mark.parametrize("read_only", [False, True])
def test_planning_shortcut_allows_project_readers_and_replaces_stale_focus(business, read_only):
    path, service, admin, editor, _ = business
    if read_only:
        for assignment in service.assignments(admin, editor.actor.user_id):
            service.revoke(admin, assignment["id"])
        service.grant(admin, editor.actor.user_id, "project_viewer",
                      {"kind": "projects", "project_ids": [1]})
    with patch("app.presentation.pages.portfolio.portfolio_project_table"):
        app = AppTest.from_function(portfolio_app, args=(path, editor.actor))
        app.session_state["portfolio_master_table"] = {"row_click": 1}
        app.run()
        assert not app.exception and not app.error
        assert ("btn_edit_details_1" in [button.key for button in app.button]) == (not read_only)
        stale_keys = ("active_resource_pool_filter", "pending_resource_pool_filter",
                      "pending_clear_resource_pool_filter", "pending_project_context_filter",
                      "target_planning_task_id")
        for key in stale_keys:
            app.session_state[key] = {"project_id": 2}
        app.button(key="btn_planning_details_1").click().run()
    assert not app.exception and not app.error
    assert app.session_state["nav_redirect"] == "2. Planning & Step Loader"
    assert app.session_state["target_planning_project_id"] == 1
    assert all(key not in app.session_state for key in stale_keys)


@pytest.mark.parametrize("offset", ["invalid", [], float("inf")])
def test_portfolio_facet_requests_and_invalid_offsets_keep_scoped_rows_and_statistics(business, offset):
    path, _, _, editor, _ = business
    with patch("app.presentation.pages.portfolio.portfolio_project_table") as table:
        app = AppTest.from_function(portfolio_app, args=(path, editor.actor)).run()
        context = table.call_args.kwargs["page_info"]["context"]
        app.session_state["portfolio_master_table"] = {"request": {
            "context": context, "kind": "facet", "column": "name", "search": "",
            "offset": offset, "nonce": "facet-request",
            "query": {"filters": {"status": {"values": "invalid"}}},
        }}
        app.run()
        assert not app.exception and not app.error
        info = table.call_args.kwargs["page_info"]
        assert info["offset"] == 0 and info["total"] == 1
        assert info["facet"]["values"] == [{"value": "Visible", "count": 1}]
        assert dict(info["facet"]["stats"])["Rows"] == 1
        assert info["request_id"] == "facet-request"


def test_portfolio_cached_facet_is_not_served_after_access_revocation(business):
    path, service, admin, editor, _ = business
    with patch("app.presentation.pages.portfolio.portfolio_project_table") as table:
        app = AppTest.from_function(portfolio_app, args=(path, editor.actor)).run()
        context = table.call_args.kwargs["page_info"]["context"]
        app.session_state["portfolio_master_table"] = {"request": {
            "context": context, "kind": "facet", "column": "name", "nonce": "cached-facet",
        }}
        app.run()
        assert table.call_args.kwargs["page_info"]["facet"]["values"][0]["value"] == "Visible"
        service.set_status(admin, editor.actor.user_id, "disabled")
        table.reset_mock()
        app.run()
        assert not app.exception and app.error
        table.assert_not_called()


def test_numeric_portfolio_statistics_and_cached_facets_follow_each_actor_scope(pg_database, business):
    from app.main import create_portfolio_service
    from app.presentation.pages.portfolio import _load_portfolio_facet

    path, service, admin, editor, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type,applies_to_all) VALUES('SCORE','complexity','NUMBER',true)")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,number_value) VALUES(1,'SCORE','number',3),(2,'SCORE','number',99)")
    columns = [{"key": "property:SCORE", "param_id": "SCORE", "format": "number"}]
    for access, count, maximum in [(manager, 2, 99), (editor, 1, 3)]:
        reader = create_portfolio_service(path, access=access)
        facet = _load_portfolio_facet(reader.revision(), columns, {}, "property:SCORE", "", reader)
        stats = dict(facet["stats"])
        assert stats["Rows"] == count and stats["Maximum"] == maximum
        assert stats["Minimum"] == 3
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [2]})
    reader = create_portfolio_service(path, access=editor)
    facet = _load_portfolio_facet(reader.revision(), columns, {}, "property:SCORE", "", reader)
    assert dict(facet["stats"])["Average"] == 51


def test_portfolio_detail_button_opens_the_persisted_project_for_editing(business):
    from tests.test_fragment_reruns import FragmentRun
    path, _, _, editor, _ = business
    with patch("app.presentation.pages.portfolio.portfolio_project_table"):
        app = AppTest.from_function(portfolio_app, args=(path, editor.actor))
        app.session_state["portfolio_master_table"] = {"row_click": 1}
        FragmentRun("btn_edit_details_1", widget_trigger=True).run(app)
    assert not app.exception and not app.error
    form = app.session_state["portfolio_project_modal_state"].form
    assert form["can_save"] and form["values"]["name"] == "Visible"
    assert not next(field for field in form["fields"] if field["key"] == "name")["disabled"]
    assert "Update Project" in form["submit"]


def task_query_app(path: RuntimeResources, actor: Actor) -> None:
    """Apply the production component callback before rendering its real scoped query."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_tag_service
    from app.presentation.components.tag_dialogs import _handle_task_tag_query_change
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.tags import render_task_tags

    set_current_locale("en")
    if "before_event" in st.session_state:
        st.session_state["task_tag_interactive_table"] = st.session_state.pop("before_event")
        _handle_task_tag_query_change()
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_task_tags(create_tag_service(path, access=access))


@pytest.mark.parametrize("query,expected", [
    ({"search": "Hidden"}, []),
    ({"search": "Visible", "page": 99, "sort": "free_tag", "ascending": True}, [10]),
    ({"filters": {"project_name": "Hidden"}, "project_ids": [2], "permission": "all"}, []),
    ([], [10]),
])
def test_task_tag_component_query_callback_preserves_scoped_counts_and_allowlisted_arguments(pg_database, business, query, expected):
    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.task_tag(id,task_id,free_tag) VALUES(10,10,'Visible tag'),(20,20,'Hidden tag')")
    with patch("streamlit.components.v1.declare_component") as factory:
        factory.return_value.return_value = None
        app = AppTest.from_function(task_query_app, args=(path, editor.actor))
        app.session_state["before_event"] = {"action": "query_task_tags", "query": query, "nonce": "query-request"}
        app.run()
        assert not app.exception and not app.error
        payload = factory.return_value.call_args.kwargs
        assert payload["page_info"]["total"] == 1
        assert payload["page_info"]["filtered_total"] == len(expected)
        assert [row["id"] for row in payload["task_tags"]] == expected
        assert not ({"project_ids", "permission"} & payload["query"].keys())
        assert payload["query_nonce"] == ("query-request" if isinstance(query, dict) else None)


@pytest.fixture
def contacts(pg_database, business):
    """Create visible/hidden assignments and an unrelated employee for payload checks."""
    path, _, _, editor, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level) VALUES(10,'Visible function',1),(20,'Hidden function',1),(30,'Unrelated function',1)")
        connection.execute("INSERT INTO eppm.employee(firstname,lastname,email,employee_code,function_id) VALUES('Rae','Visible','visible@example.test','V',10),('Robin','Hidden','hidden@example.test','H',20),('Unrelated','Person','unrelated@example.test','U',30)")
    shared = create_collaboration_service(path, access=manager)
    role_id = shared.save_catalog("role", "Sponsor")
    visible_id = shared.save_contact(1, role_id, 10)
    hidden_id = shared.save_contact(2, role_id, 20)
    return path, editor, visible_id, hidden_id


def collaboration_app(path: RuntimeResources, actor: Actor, surface: str, contact_id: int | None = None) -> None:
    """Render production contact and log entry points with an explicit actor."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_collaboration_service
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages import collaboration

    set_current_locale("en")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    service = create_collaboration_service(path, access=access)
    {
        "contacts": lambda: collaboration.render_project_contacts(1, service),
        "reassign": lambda: collaboration._contact_dialog(1, service, contact_id),
        "log": lambda: collaboration._event_dialog(1, service),
    }[surface]()
    if surface == "reassign":
        collaboration.render_project_contacts(1, service)
    elif surface == "log":
        collaboration.render_project_log(1, service)


@pytest.mark.parametrize("action", ["reassign", "remove"])
@pytest.mark.parametrize("target", ["visible", "hidden", "malformed"])
def test_contact_table_actions_are_limited_to_current_visible_assignments(pg_database, contacts, action, target):
    path, editor, visible_id, hidden_id = contacts
    identifier = {"visible": visible_id, "hidden": hidden_id, "malformed": True}[target]
    component = Mock(return_value=SimpleNamespace(action={"id": identifier, "action": action}))
    with patch("streamlit.components.v2.component", return_value=component):
        app = AppTest.from_function(collaboration_app, args=(path, editor.actor, "contacts")).run()
    assert not app.exception and not app.error
    payload = next(call.kwargs["data"] for call in component.call_args_list
                   if call.kwargs["key"] == "project_contacts_table_1")
    assert [row["id"] for row in payload["rows"]] == [visible_id]
    assert payload["rows"][0]["person"] == "Rae Visible"
    assert "Robin Hidden" not in str(payload) and "Unrelated Person" not in str(payload)
    assert set(payload["actions"]) == {"reassign", "remove"}
    assert ("project_contacts_1_modal_state" in app.session_state) == (target == "visible")
    if target == "visible" and action == "reassign":
        assert app.session_state["project_contacts_1_modal_state"]["form"]["fields"][0]["disabled"]
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT COUNT(*) FROM eppm.project_contact").fetchone()[0] == 2


def test_viewer_contacts_include_visible_people_without_exposing_edit_actions(business, contacts):
    path, service, admin, editor, _ = business
    _, _, visible_id, _ = contacts
    assignment = service.assignments(admin, editor.actor.user_id)[0]
    service.revoke(admin, assignment["id"])
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})
    component = Mock(return_value=SimpleNamespace(action={"id": visible_id, "action": "remove"}))
    with patch("streamlit.components.v2.component", return_value=component):
        app = AppTest.from_function(collaboration_app, args=(path, editor.actor, "contacts")).run()
    assert not app.exception and not app.error and not app.button and not app.get("dialog")
    payload = next(call.kwargs["data"] for call in component.call_args_list
                   if call.kwargs["key"] == "project_contacts_table_1")
    assert payload["actions"] == {}
    assert [row["id"] for row in payload["rows"]] == [visible_id]


@pytest.mark.parametrize("stale", ["removed", "moved"])
def test_contact_reassignment_detects_a_changed_owner_before_submitting(pg_database, contacts, stale):
    path, editor, visible_id, _ = contacts
    app = AppTest.from_function(collaboration_app, args=(path, editor.actor, "reassign", visible_id)).run()
    with psycopg.connect(pg_database.operator_url) as connection:
        if stale == "removed":
            connection.execute("DELETE FROM eppm.project_contact WHERE id=%s", (visible_id,))
        else:
            connection.execute("UPDATE eppm.project_contact SET project_id=2 WHERE id=%s", (visible_id,))
    app.run()
    assert not app.exception and "no longer exists" in app.error[0].value
    assert not app.selectbox
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT project_id,function_id FROM eppm.project_contact WHERE id=%s", (visible_id,)).fetchall() == ([] if stale == "removed" else [(2, 10)])


def test_log_creation_requires_configured_event_types_and_preserves_multiline_values(business):
    from tests.modal_interactions import submit_modal

    path, _, _, editor, manager = business
    shared = create_collaboration_service(path, access=manager)
    for record in shared.list_catalog("event_type"):
        shared.delete_catalog("event_type", record["id"])
    app = AppTest.from_function(collaboration_app, args=(path, editor.actor, "log")).run()
    assert not app.exception and "project_log_1_modal_state" not in app.session_state
    assert "Create event types in Settings" in app.info[0].value
    shared.save_catalog("event_type", "Update")
    app.run()
    submit_modal(app, "log", {"title": "Scope review", "description": "First line\nSecond line",
                              "comment": "Review\nApproved wording"})
    assert not app.exception and not app.error
    events = shared.list_events(1)
    assert len(events) == 1 and events[0]["description"] == "First line\nSecond line"
    assert events[0]["comment"] == "Review\nApproved wording"
    assert shared.list_events(2) == []
