"""Gantt callbacks preserve scoped task and resource data while updating the chart."""

import json
from datetime import date
from unittest.mock import patch

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from tests.postgresql.business import business
from app.runtime import RuntimeResources
from app.domain.access.models import Actor


def scoped_planning_app(path: RuntimeResources, actor: Actor) -> None:
    """Run mutation-focused cases after explicit edit-mode consent."""
    import streamlit as st
    from tests.business_ui import scoped_planning_app as render_scoped_planning

    st.session_state.setdefault('planning_edit_enabled', True)
    render_scoped_planning(path, actor)


def filtered_planning_app(path, actor):
    """Include shell markers to detect full-app reruns from chart callbacks."""
    import streamlit as st
    from tests.business_ui import scoped_planning_app

    st.sidebar.text("Retained navigation")
    st.text("Retained page shell")
    scoped_planning_app(path, actor)


@pytest.mark.parametrize("action", ["update_dates", "update_progress"])
def test_inline_gantt_updates_refresh_only_authorized_tasks_and_pool_demand(pg_database, business, action):
    path, _, _, editor, _ = business
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        initial = component.call_args.kwargs
        assert [int(task["id"]) for task in initial["tasks"]] == [10]
        app.session_state["before_event"] = {
            "action": action, "id": 10, "start_date": "2026-02-02", "end_date": "2026-02-06",
            "progress": 40, "nonce": "inline-update",
        }
        app.run()
        assert not app.exception and not app.error
        delta = component.call_args.kwargs["patch"]
        assert delta["replace_projects"] == [1]
        assert [int(task["id"]) for task in delta["tasks"]] == [10]
        assert "Hidden" not in json.dumps(delta, default=str)
        assert ("resource_pools" in delta) == (action == "update_dates")
        if action == "update_dates":
            assert delta["resource_pools"]
        app.run()
        assert not app.exception and not app.error
    with psycopg.connect(pg_database.operator_url) as connection:
        visible = connection.execute("SELECT start_date,end_date,progress_pct FROM eppm.project_task WHERE id=10").fetchone()
        hidden = connection.execute("SELECT start_date,end_date,progress_pct FROM eppm.project_task WHERE id=20").fetchone()
        assert visible == ((date(2026, 2, 2), date(2026, 2, 6), 0) if action == "update_dates" else (date(2026, 1, 1), date(2026, 1, 5), 40))
        assert hidden == (date(2026, 1, 1), date(2026, 1, 5), 0)
        assert connection.execute("SELECT id,fte_assigned FROM eppm.resource_pool_assignment ORDER BY id").fetchall() == [(1, 1), (2, 2)]


def test_lazy_gantt_hydration_discards_invalid_hidden_and_duplicate_project_ids(business):
    path, _, _, editor, _ = business
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        app.session_state["before_event"] = {
            "action": "load_project_tasks", "project_ids": [[], "bad", 2, 999, 1, 1],
            "scope_token": component.call_args.kwargs["scope_token"], "nonce": "hydrate",
        }
        app.run()
        assert not app.exception and not app.error
        delta = component.call_args.kwargs["patch"]
        assert delta["replace_projects"] == [1]
        assert [int(task["id"]) for task in delta["tasks"]] == [10]
        assert "Hidden" not in json.dumps(delta, default=str)


@pytest.mark.parametrize("filter_scope", ["this", "all", "predecessors"])
def test_project_context_filter_refreshes_the_planning_fragment_once_with_current_scope(business, filter_scope):
    from tests.test_fragment_reruns import FragmentRun

    path, _, _, editor, _ = business
    app = AppTest.from_function(filtered_planning_app, args=(path, editor.actor), default_timeout=30)
    rerun = FragmentRun("planning_lazy_gantt", widget_json={
        "action": "filter_project", "project_id": 1, "filter_scope": filter_scope, "nonce": "project-filter",
    })
    rerun.run(app)
    assert not app.error
    assert app.session_state["ms_multi_projects"] == [1]
    assert "planning_needs_full_rerun" not in app.session_state
    deltas = [message.delta for message in rerun.messages if message.WhichOneof("type") == "delta"]
    assert all(delta.fragment_id for delta in deltas), "Filtering must not rerun the application shell"
    chart_updates = [delta.new_element.component_instance for delta in deltas if delta.new_element.component_instance.id]
    assert len(chart_updates) == 1
    assert "Hidden" not in chart_updates[0].json_args
    assert not any(message.metadata.delta_path[0] == 1 for message in rerun.messages if message.WhichOneof("type") == "delta")


def test_changing_the_chart_selection_reads_current_capacity_once_per_rebuild(pg_database, business):
    from app.presentation.components.planning_workspace import PlanningWorkspace
    from tests.test_fragment_reruns import FragmentRun

    path, access, administrator, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name,status) VALUES(3,'Other visible project','In Progress')")
    access.grant(administrator, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [3]})
    reads = []
    original = PlanningWorkspace.pool_details

    def details(workspace, pool_ids=None, *, project_ids=None):
        reads.append(pool_ids)
        return original(workspace, pool_ids, project_ids=project_ids)

    rerun = FragmentRun("planning_lazy_gantt", widget_json={
        "action": "filter_project", "project_id": 1, "filter_scope": "all", "nonce": "capacity-filter",
    })
    app = AppTest.from_function(filtered_planning_app, args=(path, editor.actor), default_timeout=30)
    with patch.object(PlanningWorkspace, "pool_details", details):
        rerun.run(app)
    assert not app.error
    assert app.session_state["ms_multi_projects"] == [1]
    assert len(reads) == 2  # One initial build and one changed selection.


def test_project_filter_rechecks_a_disabled_account_without_a_full_application_rerun(business):
    from tests.test_fragment_reruns import FragmentRun

    path, access, administrator, editor, _ = business
    rerun = FragmentRun(
        "planning_lazy_gantt",
        before_rerun=lambda: access.set_status(administrator, editor.actor.user_id, "disabled"),
        widget_json={"action": "filter_project", "project_id": 1, "filter_scope": "all", "nonce": "disabled-filter"},
    )
    app = AppTest.from_function(filtered_planning_app, args=(path, editor.actor), default_timeout=30)
    rerun.run(app)
    assert app.error and "not permitted" in app.error[0].value
    assert not any(
        message.delta.new_element.component_instance.id
        for message in rerun.messages if message.WhichOneof("type") == "delta"
    )


@pytest.mark.parametrize("event", [
    {"action": "update_dates", "id": 10, "start_date": "invalid", "end_date": "2026-02-06"},
    {"action": "update_dates", "id": 10, "start_date": "2026-02-06", "end_date": "2026-02-02"},
    {"action": "update_progress", "id": 10, "progress": None},
    {"action": "update_dates", "id": [], "start_date": "2026-02-02", "end_date": "2026-02-06"},
    {"action": "update_dates", "id": 20, "start_date": "2026-02-02", "end_date": "2026-02-06"},
])
def test_invalid_or_unauthorized_inline_updates_leave_tasks_and_allocations_unchanged(pg_database, business, event):
    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        tasks = connection.execute("SELECT * FROM eppm.project_task ORDER BY id").fetchall()
        allocations = connection.execute("SELECT * FROM eppm.resource_pool_assignment ORDER BY id").fetchall()
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None):
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        app.session_state["before_event"] = event
        app.run()
        assert not app.exception
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT * FROM eppm.project_task ORDER BY id").fetchall() == tasks
        assert connection.execute("SELECT * FROM eppm.resource_pool_assignment ORDER BY id").fetchall() == allocations


@pytest.mark.parametrize("action", ["update_dates", "update_progress"])
@pytest.mark.parametrize("task_id", [10, 20, 999])
def test_gantt_returned_events_enforce_the_same_task_scope_as_callbacks(pg_database, business, action, task_id):
    path, _, _, editor, _ = business
    event = {"action": action, "id": task_id, "start_date": "2026-02-02", "end_date": "2026-02-06",
             "progress": 40, "nonce": "returned-event"}
    with patch("app.presentation.pages.planning._interactive_gantt", side_effect=[event, None]):
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
    assert not app.exception
    assert bool(app.error) == (task_id != 10)
    if task_id != 10:
        assert not app.toast
        assert "Hidden" not in app.error[0].value
    with psycopg.connect(pg_database.operator_url) as connection:
        tasks = connection.execute("SELECT id,start_date,end_date,progress_pct FROM eppm.project_task ORDER BY id").fetchall()
        expected = (10, date(2026, 2, 2), date(2026, 2, 6), 0) if action == "update_dates" else (10, date(2026, 1, 1), date(2026, 1, 5), 40)
        assert tasks == [expected if task_id == 10 else (10, date(2026, 1, 1), date(2026, 1, 5), 0), (20, date(2026, 1, 1), date(2026, 1, 5), 0)]
        assert connection.execute("SELECT id,fte_assigned FROM eppm.resource_pool_assignment ORDER BY id").fetchall() == [(1, 1), (2, 2)]


@pytest.mark.parametrize("action", ["filter_project", "clear_resource_pool_filter"])
def test_gantt_menu_filter_reruns_retain_only_current_authorized_projects(business, action):
    path, _, _, editor, _ = business
    event = {"action": action, "project_id": 1, "filter_scope": "all", "nonce": "menu-filter"}
    with patch("app.presentation.pages.planning._interactive_gantt", side_effect=[event, None]) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30)
        if action == "clear_resource_pool_filter":
            app.session_state["active_resource_pool_filter"] = {
                "pool_id": 1, "pool_name": "Reference pool", "pool_ids": [1], "project_ids": [1], "count": 1,
                "start_date": "2026-01-01", "end_date": "2026-01-05", "clear_other_filters": True,
            }
        app.run()
        assert not app.exception and not app.error
        assert app.session_state["ms_multi_projects"] == [1]
        assert "Hidden" not in json.dumps(component.call_args.kwargs, default=str)
        assert "active_resource_pool_filter" not in app.session_state


def test_forged_resource_settings_navigation_does_not_grant_shared_administration(business):
    from tests.postgresql.test_scoped_resource_settings_ui import resource_settings_app

    path, _, _, editor, _ = business
    event = {"action": "go_to_pool_details", "pool_id": 1, "nonce": "resource-navigation"}
    with patch("app.presentation.pages.planning._interactive_gantt", side_effect=[event, None]):
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
    assert not app.exception and not app.error
    assert app.session_state["target_resource_pool_id"] == 1
    assert app.session_state["settings_active_tab"] == "resource_pools"
    settings = AppTest.from_function(resource_settings_app, args=(path, editor.actor), default_timeout=30).run()
    assert not settings.exception and "not permitted" in settings.error[0].value
    assert not settings.button and not settings.selectbox and not settings.metric


@pytest.mark.parametrize("group", [False, True])
def test_gantt_pool_and_group_allocation_menus_open_only_scoped_rows(pg_database, business, group):
    import streamlit as st
    from types import SimpleNamespace
    from unittest.mock import Mock

    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES(10,'Delivery container')")
        connection.execute("UPDATE eppm.resource_pool SET parent_pool_id=10 WHERE id=1")
    event = {"action": "show_pool_allocations", "pool_id": 0 if group else 1,
             "group_id": 10 if group else None, "nonce": "allocations-menu"}
    table = Mock(return_value=SimpleNamespace(action=None))
    register = st.components.v2.component
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=event), \
            patch("streamlit.components.v2.component", side_effect=lambda name, **kwargs:
                  table if name == "eppm_action_table" else register(name, **kwargs)):
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
    assert not app.exception and not app.error and app.get("dialog")
    payload = table.call_args.kwargs["data"]
    assert [row["id"] for row in payload["rows"]] == [1]
    assert payload["actions"] == {"open": "Go to"}
    assert "Hidden" not in json.dumps(payload)


@pytest.mark.parametrize("selection", [[1, 3], [3]])
def test_pool_filter_can_retain_other_filters_without_broadening_project_access(pg_database, business, selection):
    path, service, admin, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name,status) VALUES(3,'Other visible project','In Progress')")
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [3]})
    event = {"action": "filter_by_resource_pool", "pool_id": 1, "pool_name": "Reference pool",
             "start_date": "2026-01-01", "end_date": "2026-01-05", "clear_other_filters": False,
             "filter_scope": "this", "nonce": "retain-filter"}
    with patch("app.presentation.pages.planning._interactive_gantt", side_effect=[event, None]) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30)
        app.session_state["ms_multi_projects"] = selection
        app.run()
        assert not app.exception and not app.error
        assert app.session_state["ms_multi_projects"] == [1]
        assert app.session_state["active_resource_pool_filter"]["project_ids"] == [1]
        assert "Hidden" not in json.dumps(component.call_args.kwargs, default=str)


def test_active_user_without_project_grants_gets_no_planning_payload(business):
    path, service, admin, editor, _ = business
    for assignment in service.assignments(admin, editor.actor.user_id):
        service.revoke(admin, assignment["id"])
    with patch("app.presentation.pages.planning._interactive_gantt") as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
    assert not app.exception and "not permitted" in app.error[0].value
    component.assert_not_called()
    assert not app.multiselect and not app.button


def test_numeric_flex_filters_preserve_null_values_and_replace_an_incompatible_selection(pg_database, business):
    from app.main import create_schema_service

    path, service, admin, editor, manager = business
    schema = create_schema_service(path, access=manager)
    schema.create_parameter("SCORE", None, "Numeric score", "NUMBER", alias="Score")
    schema.create_parameter("WEIGHT", None, "Numeric weight", "NUMBER", alias="Score")
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name,status) VALUES(3,'Other visible project','In Progress')")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,number_value) VALUES(1,'SCORE','number',42),(2,'SCORE','number',99)")
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [3]})
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30)
        app.session_state["dashboard_flex_fields"] = ["SCORE"]
        app.session_state["ms_multi_projects"] = [3]
        app.run()
        assert not app.exception and not app.error
        options = app.multiselect(key="dashboard_flex_fields").options
        assert "Score" in options and "Score (WEIGHT)" in options
        choices = app.multiselect(key="dashboard_filter_SCORE").options
        assert len(choices) == 1 and float(choices[0]) == 42
        app.multiselect(key="dashboard_filter_SCORE").set_value(choices).run()
        assert not app.exception and not app.error
        assert app.session_state["ms_multi_projects"] == [1]
        assert "Hidden" not in json.dumps(component.call_args.kwargs, default=str)


def test_scoped_task_updates_refresh_only_the_affected_pool_within_nested_groups(pg_database, business):
    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(2,'Unused pool',1)")
        connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES(10,'First container'),(20,'Second container')")
        connection.execute("UPDATE eppm.resource_pool SET parent_pool_id=10 WHERE id=20")
        connection.execute("UPDATE eppm.resource_pool SET parent_pool_id=CASE id WHEN 1 THEN 10 ELSE 20 END WHERE id IN (1,2)")
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        assert not app.exception and not app.error
        hierarchy = component.call_args.kwargs["resource_pool_hierarchy"]
        assert len(hierarchy) == 1
        assert all(node["descendant_pool_ids"] == [1, 2] for node in hierarchy)
        app.session_state["before_event"] = {
            "action": "update_dates", "id": 10, "start_date": "2026-02-02", "end_date": "2026-02-06", "nonce": "cycle-update",
        }
        app.run()
        assert not app.exception and not app.error
        delta = component.call_args.kwargs["patch"]
        assert "Unused pool" not in json.dumps(delta, default=str)
        assert "Hidden" not in json.dumps(delta, default=str)
        assert [int(task["id"]) for task in delta["tasks"]] == [10]


def test_business_administrator_empty_portfolio_renders_no_planning_data(business):
    from app.main import create_project_service

    path, _, _, _, manager = business
    projects = create_project_service(path, access=manager)
    projects.delete_project(1)
    projects.delete_project(2)
    with patch("app.presentation.pages.planning._interactive_gantt") as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, manager.actor), default_timeout=30).run()
    assert not app.exception and not app.error
    assert any("No projects available" in item.value for item in app.info)
    assert not any("schema parameters" in item.value for item in app.info)
    component.assert_not_called()


def test_registered_gantt_receives_only_the_current_actor_project_projection(business):
    from pathlib import Path
    from unittest.mock import Mock

    path, _, _, editor, _ = business
    browser = Mock(return_value=None)
    with patch("app.presentation.pages.planning.components.declare_component", return_value=browser) as register:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
    assert not app.exception and not app.error
    assert register.call_args.args == ("interactive_gantt",)
    assert (Path(register.call_args.kwargs["path"]) / "index.html").is_file()
    payload = json.dumps(browser.call_args.kwargs, default=str)
    assert "Visible" in payload and "Hidden" not in payload


def test_active_allocation_inspector_does_not_show_assignments_outside_its_period(business):
    path, _, _, editor, _ = business

    def allocation_app(path, actor):
        from app.application.services.access import AuthorizationPolicy, SessionLimits
        from app.application.services.business_access import BusinessAccess
        from app.main import create_planning_workspace
        from app.presentation.pages.planning import _render_filtered_active_allocations

        access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
        workspace = create_planning_workspace(path, access=access)
        _render_filtered_active_allocations({
            "pool_id": 1, "pool_ids": [1], "pool_name": "Reference pool",
            "start_date": "2026-02-01", "end_date": "2026-02-28",
        }, {}, workspace)

    app = AppTest.from_function(allocation_app, args=(path, editor.actor)).run()
    assert not app.exception and not app.error
    assert "No active allocations found for Reference pool" in app.info[0].value
    assert not app.dataframe and not app.button
    assert not any("Hidden" in item.value for item in app.markdown)
