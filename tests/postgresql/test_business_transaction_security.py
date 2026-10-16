"""Native scope enforcement and scoped application/UI workflows."""

from tests.postgresql.plan_fixtures import seed_test_plans
from tests.postgresql.pool_helpers import create_container

from datetime import date

import psycopg
import pytest

from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, VerifiedIdentity
from app.infrastructure.postgresql.business import run_business
from tests.postgresql.business import business
from tests.business_ui import (
    project_permission_dialog, permission_control_app, scoped_planning_app, tag_catalog_app, shared_catalog_app, shared_directory_dialog_app,
)


def test_scope_is_applied_before_pages_totals_groups_and_relationship_labels(business):
    path, _, _, editor, _ = business

    def inspect(connection):
        assert connection.execute("SELECT id FROM eppm.project ORDER BY id LIMIT 1 OFFSET 1").fetchall() == []
        assert connection.execute("SELECT count(*) FROM eppm.project").fetchone() == (1,)
        assert connection.execute("SELECT project_id,count(*) FROM eppm.project_task GROUP BY project_id").fetchall() == [(1, 1)]
        assert connection.execute("SELECT predecessor_id FROM eppm.visible_project_task WHERE id=10").fetchone() == (None,)
        assert connection.execute("SELECT * FROM eppm.task_dependencies").fetchall() == []
        assert connection.execute("SELECT sum(fte_assigned) FROM eppm.resource_pool_assignment").fetchone() == (1,)
        assert connection.execute("SELECT id FROM eppm.resource_pool_assignment WHERE id=2").fetchall() == []

    run_business(path.database, path.key, editor, inspect)
    with pytest.raises(AccessDenied):
        run_business(path.database, path.key, editor,
                     lambda connection: connection.execute("SELECT predecessor_id FROM eppm.project_task WHERE id=10").fetchall())


def test_scoped_summary_cache_cannot_reuse_a_global_hidden_dependency_indicator(business, pg_database):
    from app.main import create_planning_service

    path, _, _, editor, manager = business
    privileged = create_planning_service(path, access=manager).get_project_summaries([1, 2])
    assert privileged[0]["hasViolations"]
    reader = create_planning_service(path, access=editor)
    summaries = reader.get_project_summaries([1, 2])
    assert [row["id"] for row in summaries] == [1]
    assert summaries[0]["hasViolations"] is False
    assert reader.get_project_summaries([1]) == summaries
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT summary->>'hasViolations' FROM eppm.planning_summary_cache "
                                  "WHERE user_id=%s AND project_id=1", (manager.actor.user_id,)).fetchone() == ("true",)


@pytest.mark.parametrize("query,hidden_target", [
    ("UPDATE eppm.project SET name='Forbidden' WHERE id=2", True),
    ("UPDATE eppm.project_task SET task_name='Forbidden' WHERE id=20", True),
    ("UPDATE eppm.project_task SET project_id=2 WHERE id=10", False),
    ("UPDATE eppm.project_task SET project_id=0 WHERE id=10", False),
    ("UPDATE eppm.resource_pool_assignment SET project_id=1 WHERE id=2", True),
    ("UPDATE eppm.resource_pool_assignment SET task_id=20 WHERE id=1", False),
    ('INSERT INTO eppm.resource_pool_assignment(id,pool_id,project_id,task_id,fte_assigned,project_plan_id) VALUES (2,1,1,10,2,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)) ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,task_id=excluded.task_id,fte_assigned=excluded.fte_assigned', False),
    ("INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id,link_type,lag_days) VALUES(20,10,'FS',0)", False),
    ("INSERT INTO eppm.task_dependencies(task_id,predecessor_project_id,link_type,lag_days) VALUES(10,2,'FS',0)", False),
    ("INSERT INTO eppm.task_tag(task_id,free_tag) VALUES(20,'Unauthorized tag')", False),
    ("INSERT INTO eppm.task_tag(task_id,free_tag) VALUES(0,'Invalid owner')", False),
    ("INSERT INTO eppm.task_tag(task_id,free_tag) VALUES(999,'Missing owner')", False),
    ("DELETE FROM eppm.task_dependencies WHERE task_id=10", True),
    ("DELETE FROM eppm.project WHERE id=1", False),
    ("INSERT INTO eppm.project(name) VALUES('Forbidden')", False),
    ("UPDATE eppm.project_property_value SET text_value='Delivery' WHERE project_id=1", False),
    ("DELETE FROM eppm.project_property_value WHERE project_id=1", False),
    ("UPDATE eppm.resource_pool SET capacity_fte=999 WHERE id=1", False),
    ("DELETE FROM eppm.schema_param_options WHERE param_id='DEPT'", False),
])
def test_forged_child_owners_cross_project_writes_and_scope_property_edits_cannot_mutate_data(business, pg_database, query, hidden_target):
    path, _, _, editor, _ = business

    def mutate(connection):
        if hidden_target:
            # PostgreSQL RLS makes this target unavailable even to UPDATE/DELETE.
            assert connection.execute(query).rowcount == 0
        else:
            connection.execute("UPDATE eppm.project SET name='Would otherwise persist' WHERE id=1")
            connection.execute(query)

    if hidden_target:
        run_business(path.database, path.key, editor, mutate, write=True)
    else:
        with pytest.raises(AccessDenied):
            run_business(path.database, path.key, editor, mutate, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT id,name FROM eppm.project ORDER BY id").fetchall() == [(1, "Visible"), (2, "Hidden")]
        assert connection.execute("SELECT capacity_fte FROM eppm.resource_pool WHERE id=1").fetchone() == (3,)
        assert connection.execute("SELECT id,project_id,task_id,fte_assigned FROM eppm.resource_pool_assignment ORDER BY id").fetchall() == [(1,1,10,1),(2,2,20,2)]
        assert connection.execute("SELECT task_id,predecessor_task_id FROM eppm.task_dependencies").fetchall() == [(10,20)]
        assert connection.execute("SELECT text_value FROM eppm.project_property_value WHERE project_id=1").fetchone() == ("Finance",)


def test_ordinary_editor_can_change_project_fields_and_rewrite_unchanged_protected_value(business, pg_database):
    path, _, _, editor, _ = business

    def mutate(connection):
        connection.execute("UPDATE eppm.project SET name='Allowed' WHERE id=1")
        connection.execute("UPDATE eppm.project_property_value SET text_value='Finance' WHERE project_id=1")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES(1,'DEPT','text','Finance') "
                           "ON CONFLICT(project_id,param_id) DO UPDATE SET text_value=excluded.text_value")

    run_business(path.database, path.key, editor, mutate, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT name FROM eppm.project WHERE id=1").fetchone() == ("Allowed",)


def test_business_administrator_can_update_shared_capacity_through_the_guarded_transaction(business, pg_database):
    path, _, _, _, manager = business
    run_business(path.database, path.key, manager,
                 lambda connection: connection.execute("UPDATE eppm.resource_pool SET capacity_fte=4 WHERE id=1"), write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT capacity_fte FROM eppm.resource_pool WHERE id=1").fetchone() == (4,)


@pytest.mark.parametrize("boundary", ["read", "shared", "write", "correlation"])
def test_rejected_business_operations_log_safe_correlated_events_without_payloads(business, pg_database, caplog, boundary):
    import json
    import logging
    from dataclasses import replace
    from app.main import create_organization_service, create_project_service

    path, service, admin, editor, _ = business
    if boundary == "correlation":
        editor = BusinessAccess(replace(editor.actor, correlation_id="trace-reference\nforged.event"), editor.policy)
    logger = "app.infrastructure.postgresql.business"
    with caplog.at_level(logging.WARNING, logger=logger):
        create_project_service(path, access=editor).permissions()
        assert not caplog.records
        if boundary == "read":
            service.set_status(admin, editor.actor.user_id, "disabled")
        with pytest.raises(AccessDenied):
            if boundary == "read":
                create_project_service(path, access=editor).get_project_by_id(1)
            elif boundary in {"shared", "correlation"}:
                create_organization_service(path, access=editor).get_all_employees()
            else:
                def mutate(connection):
                    connection.execute("UPDATE eppm.project SET name='Private candidate change' WHERE id=1")
                    connection.execute("UPDATE eppm.project_task SET description='Private task payload',project_id=2 WHERE id=10")
                run_business(path.database, path.key, editor, mutate, write=True)
    messages = [record.getMessage() for record in caplog.records if record.name == logger]
    assert len(messages) == 1
    event = json.loads(messages[0].removeprefix("security.event "))
    assert event == {
        "action": "business.authorization_denied", "outcome": "denied",
        "actor": str(editor.actor.user_id), "correlation": editor.actor.correlation_id,
        "permission": "business.manage" if boundary in {"shared", "correlation"} else "scoped_operation",
    }
    assert editor.actor.session_hash not in messages[0]
    assert len(messages[0].splitlines()) == 1
    assert "Private" not in messages[0] and "Hidden" not in messages[0]
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT name FROM eppm.project WHERE id=1").fetchone() == ("Visible",)


def test_business_admin_protected_changes_are_audited_and_audit_failure_rolls_back(business, pg_database):
    path, service, admin, _, manager = business
    run_business(path.database, path.key, manager,
                 lambda connection: connection.execute("UPDATE eppm.project_property_value SET text_value='Delivery' WHERE project_id=1"), write=True)
    event = service.audit(admin)[0]
    assert event["action"] == "project.protected_property_change" and event["actor"] == str(admin.user_id)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_property_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test audit unavailable' USING ERRCODE='23514'; END $$""")
        connection.execute("CREATE TRIGGER audit_failure BEFORE INSERT ON eppm.app_security_audit "
                           "FOR EACH ROW EXECUTE FUNCTION eppm.reject_property_audit()")
    with pytest.raises(psycopg.errors.CheckViolation):
        run_business(path.database, path.key, manager,
                     lambda connection: connection.execute("UPDATE eppm.project_property_value SET text_value='Finance' WHERE project_id=1"), write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT text_value FROM eppm.project_property_value WHERE project_id=1").fetchone() == ("Delivery",)


def test_authorized_cascade_deletion_and_new_project_visibility_work_in_one_transaction(business, pg_database):
    path, _, _, _, manager = business

    def mutate(connection):
        connection.execute("DELETE FROM eppm.task_dependencies")
        connection.execute("UPDATE eppm.project_task SET predecessor_id=NULL")
        connection.execute("DELETE FROM eppm.project_task WHERE project_id=1")
        connection.execute("DELETE FROM eppm.project WHERE id=1")
        new_id = connection.execute("INSERT INTO eppm.project(name) VALUES('New authorized project') RETURNING id").fetchone()[0]
        seed_test_plans(connection)
        assert connection.execute("SELECT name FROM eppm.project WHERE id=%s", (new_id,)).fetchone() == ("New authorized project",)
        assert connection.execute("SELECT * FROM eppm.project_property_value WHERE project_id=1").fetchall() == []

    run_business(path.database, path.key, manager, mutate, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT id,project_id FROM eppm.resource_pool_assignment").fetchall() == [(2,2)]
        assert connection.execute("SELECT id,project_id FROM eppm.project_task").fetchall() == [(20,2)]


def test_revoked_session_and_invalid_context_cannot_open_business_transaction(business):
    path, service, _, editor, _ = business
    service.logout(editor.actor)
    with pytest.raises(AccessDenied):
        run_business(path.database, path.key, editor, lambda connection: None)
    with pytest.raises(AccessDenied):
        BusinessAccess(None, editor.policy)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        path.database.run(lambda connection: connection.execute("SELECT count(*) FROM eppm.project").fetchone())


@pytest.mark.parametrize("factory,operation", [
    ("create_organization_service", "get_all_employees"),
    ("create_organization_service", "get_all_functions"),
    ("create_schema_service", "get_snapshot"),
    ("create_schema_service", "get_all_parameters"),
    ("create_project_type_service", "get_all_types"),
    ("create_resource_pool_service", "get_all_mappings"),
    ("create_resource_pool_service", "get_all_pools"),
    ("create_resource_pool_service", "get_all_pools"),
    ("create_tag_service", "get_all_tags"),
    ("create_collaboration_service", "list_functions"),
    ("create_project_service", "generate_project_id"),
])
def test_public_shared_catalog_and_create_previews_deny_project_editors(business, factory, operation):
    from app import main

    path, _, _, editor, manager = business
    with pytest.raises(TypeError, match="access"):
        getattr(main, factory)(path)
    service = getattr(main, factory)(path, access=editor)
    with pytest.raises(AccessDenied):
        getattr(service, operation)()
    assert getattr(getattr(main, factory)(path, access=manager), operation)() is not None


def test_public_reads_and_references_never_expose_hidden_owners_or_employee_details(pg_database, business):
    from dataclasses import asdict
    from app import main

    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as conn:
        conn.execute("INSERT INTO eppm.function(function_id,name) VALUES(1,'Manager')")
        conn.execute("INSERT INTO eppm.employee(firstname,lastname,email,mobile,landline,function_id) VALUES('Fictional','Person','private@example.test','private-mobile','private-line',1)")
        conn.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES(1,'employee',1,100)")
    projects = main.create_project_service(path, access=editor)
    assert projects.get_project_by_id(2) is None
    assert [row["id"] for row in projects.get_planning_catalog()] == [1]
    assert main.create_planning_service(path, access=editor).get_totals() == {
        "projects": 1, "tasks": 1, "dependencies": 0, "pools": 1,
    }
    organization = main.create_organization_service(path, access=editor)
    assert asdict(organization.employee_references()[0]) == {
        "firstname": "Fictional", "lastname": "Person", "function_id": 1,
    }
    choices = main.create_collaboration_service(path, access=editor).function_choices()
    assert set(choices[0]) == {"function_id", "function_name", "person"}
    detail = main.create_pool_capacity_service(path, access=editor).get_details([1])[0]
    assert detail.contributing_resources == []
    assert {item["project_id"] for item in detail.assignments} == {1}
    assert set(asdict(main.create_resource_pool_service(path, access=editor).pool_choices()[0])) == {
        "id", "name", "capacity_fte",
    }


def test_cached_reads_are_actor_isolated_and_reauthorize_after_disable_or_expiry(business):
    from app import main
    from app.presentation.components.authorized_cache import authorized_cache

    path, access, admin, editor, manager = business
    calls = []

    @authorized_cache(ttl=60, show_spinner=False)
    def cached(revision: tuple, _service):
        calls.append(1)
        return _service.get_detail(2)

    editor_reader = main.create_portfolio_service(path, access=editor)
    manager_reader = main.create_portfolio_service(path, access=manager)
    try:
        assert cached(("same-old-revision",), manager_reader)["name"] == "Hidden"
        assert cached(("same-old-revision",), editor_reader) is None
        assert cached(("same-old-revision",), editor_reader) is None
        assert len(calls) == 2
        access.set_status(admin, editor.actor.user_id, "disabled")
        with pytest.raises(AccessDenied):
            cached(("same-old-revision",), editor_reader)
        access.policy.clock = lambda: 1900
        with pytest.raises(AccessDenied):
            cached(("same-old-revision",), manager_reader)
        assert len(calls) == 2
    finally:
        cached.clear()


def test_download_fetch_rechecks_ownership_and_revocation_without_cached_csv(business):
    from app import main
    from app.infrastructure.authentication.downloads import DownloadRoutes
    from app.infrastructure.authentication.http import SESSION_COOKIE
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    path, access, admin, editor, _ = business
    cookie = access.sign_in(VerifiedIdentity(access.issuer, "editor", "", "Editor", 1000, 100000, True))

    def export(actor, project_id):
        return main.create_planning_service(path, access=BusinessAccess(actor, access.policy)).export_project_template(project_id)

    application = Starlette(routes=DownloadRoutes(access, export).routes())
    with TestClient(application) as browser:
        endpoint = "/downloads/projects/1/template.csv"
        assert browser.get(endpoint).status_code == 403
        browser.cookies.set(SESSION_COOKIE, cookie)
        response = browser.get(endpoint)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "attachment" in response.headers["content-disposition"]
        assert "Visible task" in response.text and "Hidden task" not in response.text
        assert browser.get("/downloads/projects/2/template.csv").status_code == 403
        access.set_status(admin, editor.actor.user_id, "disabled")
        assert browser.get(endpoint).status_code == 403
        assert browser.head(endpoint).status_code == 403


def test_planning_fragment_replaces_retained_capacity_from_a_more_privileged_scope(business):
    import json
    from app import main
    from app.presentation.pages.planning import _load_planning_pool_payload

    path, _, _, editor, manager = business
    privileged = main.create_pool_capacity_service(path, access=manager).get_details([1])[0]
    assert {item["project_id"] for item in privileged.assignments} == {1, 2}
    retained = {1: privileged}
    workspace = main.create_planning_workspace(path, access=editor)
    try:
        payload = _load_planning_pool_payload(workspace, ("retained-fragment",), (1, 2), retained)
        assert "Hidden" not in json.dumps(payload)
        assert {item["project_id"] for item in retained[1].assignments} == {1}
    finally:
        _load_planning_pool_payload.clear()


def test_project_viewer_cannot_enable_editing_through_popup_state(business):
    from streamlit.testing.v1 import AppTest

    path, service, admin, _, _ = business
    actor = service.actor(service.sign_in(VerifiedIdentity(service.issuer, "viewer", "", "Viewer", 1000, 100000, True)))
    service.set_status(admin, actor.user_id, "active")
    service.grant(admin, actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})
    app = AppTest.from_function(project_permission_dialog, args=(path, actor))
    app.session_state["project_fields_editing"] = 1
    app.session_state["project_delete_confirmation"] = 1
    app.run()
    assert not app.exception and not app.error
    assert all(item.disabled for item in app.text_input)
    assert all(item.disabled for item in app.selectbox)
    assert not any(item.key in {"enable_project_edit_1", "portfolio_delete_project_1", "confirm_delete_project_1"}
                   for item in app.button)


def test_project_editor_can_save_details_but_scope_fields_stay_disabled(pg_database, business):
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    app = AppTest.from_function(project_permission_dialog, args=(path, editor.actor)).run()
    assert not app.exception
    app.button(key="enable_project_edit_1").click().run()
    assert not app.exception and not app.error
    assert app.selectbox(key="edit_type_1").disabled
    assert next(item for item in app.selectbox if "DEPT" in str(item.key)).disabled
    name = next(item for item in app.text_input if item.value == "Visible")
    assert not name.disabled
    assert not any(item.key == "portfolio_delete_project_1" for item in app.button)
    name.set_value("Updated within scope")
    next(item for item in app.button if "Update" in item.label).click().run()
    assert not app.exception and not app.error
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT name FROM eppm.project WHERE id=1").fetchone()[0] == "Updated within scope"
        assert connection.execute("SELECT text_value FROM eppm.project_property_value WHERE project_id=1").fetchone()[0] == "Finance"


def test_permission_projection_keeps_the_edit_scope_distinct_from_the_read_scope(business):
    from app.main import create_project_service
    from app.domain.access.models import Permission

    path, service, admin, editor, _ = business
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [2]})
    permissions = create_project_service(path, access=editor).permissions()
    assert permissions.allows(Permission.READ, 2)
    assert permissions.allows(Permission.EDIT, 1)
    assert not permissions.allows(Permission.EDIT, 2)
    assert not permissions.allows(Permission.PROPERTIES, 1)
    assert not permissions.allows(Permission.CREATE)
    assert not permissions.allows(Permission.DELETE, 1)


def test_direct_project_create_dialog_denies_an_ordinary_editor(pg_database, business):
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    app = AppTest.from_function(project_permission_dialog, args=(path, editor.actor, "create")).run()
    assert not app.exception and "permission to create" in app.error[0].value
    assert not app.text_input and not app.button and not app.selectbox
    assert "portfolio_create_draft_id" not in app.session_state
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT id,name FROM eppm.project ORDER BY id").fetchall() == [(1, "Visible"), (2, "Hidden")]


@pytest.mark.parametrize("action", ["create", "edit"])
def test_project_dialogs_reject_empty_names_without_mutating_projects_or_assignments(pg_database, business, action):
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, manager = business
    actor = manager.actor if action == "create" else editor.actor
    with psycopg.connect(pg_database.operator_url) as connection:
        projects = connection.execute("SELECT * FROM eppm.project ORDER BY id").fetchall()
        assignments = connection.execute("SELECT * FROM eppm.resource_pool_assignment ORDER BY id").fetchall()
    app = AppTest.from_function(project_permission_dialog, args=(path, actor, action)).run()
    if action == "edit":
        app.button(key="enable_project_edit_1").click().run()
    app.text_input[1].set_value(" ")
    next(button for button in app.button if button.label == "Create project" or "Update" in button.label).click().run()
    assert not app.exception and app.error and not app.toast
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT * FROM eppm.project ORDER BY id").fetchall() == projects
        assert connection.execute("SELECT * FROM eppm.resource_pool_assignment ORDER BY id").fetchall() == assignments


def test_business_administrator_project_deletion_clears_selected_project_and_retains_other_owners(pg_database, business):
    from streamlit.testing.v1 import AppTest

    path, _, _, _, manager = business
    app = AppTest.from_function(project_permission_dialog, args=(path, manager.actor))
    app.session_state["selected_portfolio_project_id"] = 1
    app.run()
    app.button(key="enable_project_edit_1").click().run()
    app.button(key="portfolio_delete_project_1").click().run()
    assert not app.exception and not app.error
    app.button(key="confirm_delete_project_1").click().run()
    assert not app.exception
    assert "selected_portfolio_project_id" not in app.session_state
    assert "project_delete_confirmation" not in app.session_state
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT id FROM eppm.project").fetchall() == [(2,)]
        assert connection.execute("SELECT id,project_id FROM eppm.project_task").fetchall() == [(20, 2)]
        assert connection.execute("SELECT id,project_id FROM eppm.resource_pool_assignment").fetchall() == [(2, 2)]
        assert connection.execute("SELECT * FROM eppm.task_dependencies").fetchall() == []
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize("surface", [
    "contacts", "log", "add_contact", "remove_contact", "edit_event", "project_tags",
    "task_tags", "project_pools", "task_pools", "import",
])
def test_viewer_panels_and_direct_modal_actions_offer_no_editing_controls(business, surface):
    from streamlit.testing.v1 import AppTest

    path, service, admin, _, _ = business
    actor = service.actor(service.sign_in(VerifiedIdentity(service.issuer, "viewer", "", "Viewer", 1000, 100000, True)))
    service.set_status(admin, actor.user_id, "active")
    service.grant(admin, actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})
    app = AppTest.from_function(permission_control_app, args=(path, actor, surface)).run()
    assert not app.exception and not app.error
    assert not app.button and not app.text_input and not app.selectbox
    if surface not in {"contacts", "log"}:
        assert "read-only" in app.info[0].value


def test_collaboration_edit_controls_recheck_current_status(business):
    from app.main import create_collaboration_service

    path, access, admin, editor, _ = business
    service = create_collaboration_service(path, access=editor)
    assert service.can_edit(1)
    assert not service.can_edit(2)
    access.set_status(admin, editor.actor.user_id, "disabled")
    assert not service.can_edit(1)


@pytest.mark.parametrize("surface", ["allocations", "group_allocations"])
@pytest.mark.parametrize("event", [
    None, {"id": 2, "action": "open"}, {"id": True, "action": "open"},
    {"id": 1, "action": "unassign"}, {"id": 1, "action": ["open"]},
    {"id": 1, "action": "open"},
])
def test_scoped_allocation_popups_accept_only_visible_navigation_actions(pg_database, business, surface, event):
    import streamlit as st
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    from streamlit.testing.v1 import AppTest
    from app.domain.resources.models import ResourcePool
    from app.main import create_resource_pool_service
    from app.presentation.navigation import PAGE_PLANNING

    path, service, admin, editor, manager = business
    assignment = service.assignments(admin, editor.actor.user_id)[0]
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})
    service.revoke(admin, assignment["id"])
    resources = create_resource_pool_service(path, access=manager)
    create_container(resources, ResourcePool("Visible group"), pool_ids=[1])
    component = Mock(side_effect=[SimpleNamespace(action=event), SimpleNamespace(action=None)])
    register = st.components.v2.component
    with patch("streamlit.components.v2.component", side_effect=lambda name, **kwargs:
               component if name == "eppm_action_table" else register(name, **kwargs)):
        app = AppTest.from_function(
            permission_control_app, args=(path, editor.actor, surface), default_timeout=30,
        )
        app.session_state["active_resource_pool_filter"] = {"pool_id": 1}
        app.session_state["pending_resource_pool_filter"] = {"pool_id": 1}
        app.run()
    assert not app.exception and not app.error
    for call in component.call_args_list:
        payload = call.kwargs["data"]
        assert payload["actions"] == {"open": "Go to"}
        assert [(row["id"], row["project"], row["task"], row["fte"]) for row in payload["rows"]] == [
            (1, "Visible", "Visible task", "1.00"),
        ]
    if event == {"id": 1, "action": "open"} and type(event["id"]) is int:
        assert app.session_state["nav_redirect"] == PAGE_PLANNING
        assert app.session_state["target_planning_project_id"] == 1
        assert app.session_state["target_planning_task_id"] == 10
        assert app.session_state["ms_multi_projects"] == [1]
        assert "active_resource_pool_filter" not in app.session_state
        assert "pending_resource_pool_filter" not in app.session_state
    else:
        assert "nav_redirect" not in app.session_state
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT id,fte_assigned FROM eppm.resource_pool_assignment ORDER BY id").fetchall() == [(1, 1), (2, 2)]


@pytest.mark.parametrize("surface", ["allocations", "group_allocations"])
def test_allocation_popups_explain_when_the_selection_has_no_pools(pg_database, business, surface):
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("DELETE FROM eppm.resource_pool")
    app = AppTest.from_function(
        permission_control_app, args=(path, editor.actor, surface), default_timeout=30,
    ).run()
    assert not app.exception and not app.error
    assert app.info[0].value == "No resource pools found in this selection."


@pytest.mark.parametrize("scenario", ["invalid", "preview", "cross_project", "revoked", "replace"])
def test_csv_import_validates_preview_and_rechecks_every_affected_project_before_replacement(pg_database, business, scenario):
    from types import SimpleNamespace
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, service, admin, editor, _ = business
    header = "step_number,task_name,start_date,end_date,progress_pct,preceding_step,dependency_type,dependency_lag\n"
    content = header + "1,Replacement first,13/02/2026,14/02/2026,0,,,\n2,Replacement second,15/02/2026,16/02/2026,50,1,FS,0\n"
    if scenario == "invalid":
        content = content.replace("13/02/2026", "31/02/2026")
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "all"})
    if scenario == "replace":
        service.grant(admin, editor.actor.user_id, "project_editor", {"kind": "projects", "project_ids": [2]})

    def snapshot():
        with psycopg.connect(pg_database.operator_url) as connection:
            return {table: connection.execute(f"SELECT * FROM eppm.{table} ORDER BY id").fetchall()
                    for table in ("project_task", "task_dependencies", "resource_pool_assignment")}

    before = snapshot()
    with patch("streamlit.components.v2.component") as factory:
        factory.return_value.return_value = SimpleNamespace(upload={"name": "edited.csv", "content": content})
        app = AppTest.from_function(
            permission_control_app, args=(path, editor.actor, "import"), default_timeout=30,
        ).run()
        assert not app.exception
        assert snapshot() == before
        assert app.selectbox(key="template_date_format_1").value == "DD/MM/YYYY"
        assert "Nothing is deleted" in app.warning[0].value
        if scenario == "invalid":
            assert "Row 2" in app.error[0].value and "start_date" in app.error[0].value
            assert not app.dataframe and not app.button
            return
        assert not app.error
        preview = app.dataframe[0].value
        assert preview["start_date"].tolist() == ["2026-02-13", "2026-02-15"]
        assert preview["end_date"].tolist() == ["2026-02-14", "2026-02-16"]
        if scenario == "preview":
            return
        if scenario == "revoked":
            assignment = next(item for item in service.assignments(admin, editor.actor.user_id) if item["role"] == "project_editor")
            service.revoke(admin, assignment["id"])
        app.button[0].click().run()
    assert not app.exception
    if scenario == "replace":
        assert not app.error
        with psycopg.connect(pg_database.operator_url) as connection:
            assert connection.execute("SELECT task_name,start_date,end_date FROM eppm.current_project_task WHERE project_id=1 ORDER BY id").fetchall() == [
                ("Replacement first", date(2026, 2, 13), date(2026, 2, 14)), ("Replacement second", date(2026, 2, 15), date(2026, 2, 16)),
            ]
            assert connection.execute("SELECT id FROM eppm.resource_pool_assignment").fetchall() == [(2,)]
            assert connection.execute("SELECT count(*) FROM eppm.task_dependencies").fetchone()[0] == 1
            assert connection.execute("SELECT text_value FROM eppm.project_property_value WHERE project_id=1 AND param_id='DEPT'").fetchone()[0] == "Finance"
            assert connection.execute("SELECT task_name FROM eppm.project_task WHERE id=20").fetchone()[0] == "Hidden task"
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    else:
        assert snapshot() == before
        if scenario == "revoked":
            assert "read-only" in app.info[0].value and not app.button
        else:
            assert app.error and "Hidden task" not in app.error[0].value


@pytest.mark.parametrize("mode,expected", [("Any", [1, 3]), ("All", [1])])
def test_flexible_filters_offer_only_visible_values_and_clear_without_widening_authorization(pg_database, business, mode, expected):
    import json
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, service, admin, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name,status) VALUES(3,'Visible alternative','In Progress')")
        seed_test_plans(connection)
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES(3,'DEPT','text','Finance')")
        connection.execute("INSERT INTO eppm.project_tag(project_id,free_tag) VALUES(1,'Alpha'),(1,'Beta'),(3,'Alpha'),(2,'Private tag')")
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [3]})
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30)
        app.session_state["planning_flex_fields"] = ["DEPT", "_project_tags"]
        app.session_state["planning_flex_values::DEPT"] = ["Finance"]
        app.session_state["planning_flex_values::_project_tags"] = ["Alpha", "Beta"]
        app.session_state["planning_flex_match_mode"] = mode
        app.run()
        assert not app.exception and not app.error
        assert app.multiselect(key="planning_flex_values::DEPT").options == ["Finance"]
        assert app.multiselect(key="planning_flex_values::_project_tags").options == ["Alpha", "Beta"]
        assert [int(item["id"]) for item in component.call_args.kwargs["all_projects"]] == expected
        assert "Private tag" not in json.dumps(component.call_args.kwargs, default=str)
        app.button(key="clear_all_planning_filters").click().run()
        assert not app.exception and not app.error
        assert app.multiselect(key="planning_flex_fields").value == []
        assert [int(item["id"]) for item in component.call_args.kwargs["all_projects"]] == [1, 3]
        assert "Hidden" not in json.dumps(component.call_args.kwargs, default=str)


@pytest.mark.parametrize("project_id", [1, 2, 999])
def test_gantt_dependency_choices_reauthorize_the_requested_project_before_browser_delivery(business, project_id):
    import json
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        assert not app.exception and not app.error
        app.session_state["before_event"] = {"action": "load_dependency_tasks", "project_id": project_id, "nonce": "choices"}
        app.run()
        assert not app.exception
        assert "Hidden" not in json.dumps(component.call_args.kwargs, default=str)
        response = component.call_args.kwargs.get("dependency_response")
        if project_id == 1:
            assert not app.error and response["project_id"] == "1"
            assert response["nonce"] == "choices"
            assert len(response["tasks"]) == 1 and "Visible task" in json.dumps(response["tasks"])
        else:
            assert not response or not response["tasks"]


@pytest.mark.parametrize("target", [2, 999, "invalid-reference"])
def test_planning_navigation_cannot_restore_a_hidden_or_invalid_project_selection(business, target):
    import json
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30)
        app.session_state["target_planning_project_id"] = target
        app.run()
    assert not app.exception and not app.error
    assert set(app.session_state["ms_multi_projects"]) <= {1}
    assert "Hidden" not in json.dumps(component.call_args.kwargs, default=str)
    assert [int(item["id"]) for item in component.call_args.kwargs["all_projects"]] == [1]


def test_empty_pool_consumption_filter_does_not_fall_back_to_the_entire_portfolio(business):
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    event = {"action": "filter_by_resource_pool", "pool_id": 1, "start_date": "2080-01-01",
             "end_date": "2080-01-02", "nonce": "empty-period"}
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=event) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        assert not app.exception and not app.error
        assert app.session_state["active_resource_pool_filter"]["count"] == 0
        assert any("No projects consume" in item.value for item in app.warning)
        assert component.call_count == 1
        component.return_value = None
        app.button(key="btn_clear_empty_rf_filter").click().run()
        assert not app.exception and not app.error
        assert "active_resource_pool_filter" not in app.session_state
        assert app.session_state["ms_multi_projects"] == [1]


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("scope,expected", [("this", [1]), ("all", [1, 3]), ("predecessors", [1])])
def test_pool_context_filters_and_allocation_totals_remain_inside_current_read_scope(pg_database, business, group, scope, expected):
    import json
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    from app.domain.resources.models import ResourcePool
    from app.main import create_resource_pool_service

    path, service, admin, editor, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name,status) VALUES(3,'Visible successor','In Progress')")
        seed_test_plans(connection)
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (30,3,'Successor task','2026-01-06','2026-01-07',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
        connection.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id,link_type,lag_days) VALUES(30,10,'FS',0)")
        connection.execute("INSERT INTO eppm.resource_pool_assignment(id,pool_id,project_id,fte_assigned,notes,project_plan_id) VALUES (3,1,1,0.25,'<script>visible notes</script>',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [3]})
    container_id = create_container(create_resource_pool_service(path, access=manager), ResourcePool("Delivery group"), pool_ids=[1])
    event = {
        "action": "filter_by_resource_pool", "pool_id": 1, "group_id": container_id if group else None,
        "filter_scope": scope, "start_date": "2026-01-01", "end_date": "2026-01-05", "nonce": "scope-filter",
    }
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=event) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        assert not app.exception and not app.error
        assert app.session_state["ms_multi_projects"] == expected
        active = app.session_state["active_resource_pool_filter"]
        assert active["project_ids"] == expected and active["count"] == len(expected)
        rendered = "\n".join(item.value for item in app.markdown)
        assert "1.25 FTE" in rendered and "Project Level" in rendered
        assert "&lt;script&gt;visible notes&lt;/script&gt;" in rendered
        assert "<script>visible notes</script>" not in rendered and "Hidden" not in rendered
        assert "Hidden" not in json.dumps([call.kwargs for call in component.call_args_list], default=str)
        component.return_value = None
        app.button(key="btn_clear_pool_filter_top").click().run()
        assert not app.exception and not app.error
        assert "active_resource_pool_filter" not in app.session_state
        assert app.session_state["ms_multi_projects"] == [1, 3]
        assert not any("Total Active Allocation" in item.value for item in app.markdown)


@pytest.mark.parametrize("action", ["manage_project_tags", "manage_project_pools", "manage_task_tags", "manage_task_pools", "edit_project_details"])
@pytest.mark.parametrize("visible", [True, False])
def test_gantt_context_menu_dialogs_resolve_owners_using_the_current_scope(business, action, visible):
    import json
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    project_id, task_id = (1, 10) if visible else (2, 20)
    event = {
        "action": action, "project_id": project_id, "id": task_id, "task_id": task_id,
        "task_name": "Forged task title", "nonce": "modal-event",
    }
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=event) as component:
        app = AppTest.from_function(
            scoped_planning_app, args=(path, editor.actor), default_timeout=30,
        )
        app.session_state['planning_edit_enabled'] = True
        app.run()
    assert not app.exception
    assert "Hidden" not in json.dumps([call.kwargs for call in component.call_args_list], default=str)
    displayed = "\n".join(item.value for item in app.markdown)
    assert "Hidden" not in displayed and "Forged task title" not in displayed
    dialog_inputs = [
        item for item in app.text_input
        if not (item.key or '').startswith('dashboard_filter_')
    ]
    if visible:
        assert not app.error
        if action == "edit_project_details":
            assert dialog_inputs and all(item.disabled for item in dialog_inputs)
            assert any(item.label == "Edit project" for item in app.button)
        elif "tags" in action:
            assert any(item.key and item.key.startswith("ti_attach_") for item in app.text_input)
        else:
            assert any(item.key and item.key.startswith("ni_assign_") for item in app.number_input)
    else:
        assert app.error or any("read-only" in item.value for item in app.info)
        assert not dialog_inputs and not app.number_input


@pytest.mark.parametrize("surface", ["group", "dictionary", "project", "task"])
@pytest.mark.parametrize("action", ["add", "edit", "delete"])
def test_business_admin_tag_catalog_actions_consume_the_component_event_once(pg_database, business, surface, action):
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, _, _, _, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.tag_group(id,tag_group_name) VALUES(10,'Classification')")
        connection.execute("INSERT INTO eppm.tag_dictionnary(id,tag) VALUES(10,'Priority')")
        connection.execute("INSERT INTO eppm.project_tag(id,project_id,free_tag) VALUES(10,1,'Visible project tag'),(20,2,'Hidden project tag')")
        connection.execute("INSERT INTO eppm.task_tag(id,task_id,free_tag) VALUES(10,10,'Visible task tag'),(20,20,'Hidden task tag')")
    kind = {"group": "tag_group", "dictionary": "tag", "project": "project_tag", "task": "task_tag"}[surface]
    event = {
        "action": f"{action}_{kind}", "nonce": "tag-event", "group_id": 10, "tag_group_name": "Classification",
        "tag_id": 10 if surface == "dictionary" else None, "tag": "Priority", "pt_id": 10, "project_id": 1,
        "tt_id": 10, "task_id": 10, "free_tag": f"Visible {surface} tag", "tag_label": "Selected tag",
    }
    with patch("streamlit.components.v1.declare_component") as factory:
        factory.return_value.return_value = event
        app = AppTest.from_function(tag_catalog_app, args=(path, manager.actor, surface), default_timeout=30).run()
        assert not app.exception and not app.error
        assert app.button
        if surface in {"project", "task"}:
            payload = factory.return_value.call_args.kwargs
            assert {item["id"] for item in payload[f"{surface}_tags"]} == {10, 20}
        app.run()
        assert not app.exception and not app.error
        assert not app.button and not app.text_input
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT id FROM eppm.project_tag ORDER BY id").fetchall() == [(10,), (20,)]
        assert connection.execute("SELECT id FROM eppm.task_tag ORDER BY id").fetchall() == [(10,), (20,)]


@pytest.mark.parametrize("surface", ["group", "dictionary", "project"])
def test_project_editor_cannot_render_shared_tag_catalogs_or_invoke_their_component_actions(business, surface):
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    with patch("streamlit.components.v1.declare_component") as factory:
        app = AppTest.from_function(tag_catalog_app, args=(path, editor.actor, surface), default_timeout=30).run()
    assert not app.exception and app.error
    factory.assert_not_called()


def test_scoped_task_tag_page_filters_totals_and_rejects_deletion_of_a_hidden_assignment(pg_database, business):
    import json
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.task_tag(id,task_id,free_tag) VALUES(10,10,'Visible tag'),(20,20,'Hidden tag')")
    with patch("streamlit.components.v1.declare_component") as factory:
        factory.return_value.return_value = {"action": "delete_task_tag", "tt_id": 20, "nonce": "forged-delete"}
        app = AppTest.from_function(tag_catalog_app, args=(path, editor.actor, "task"), default_timeout=30).run()
        assert not app.exception and not app.error
        payload = factory.return_value.call_args.kwargs
        assert payload["page_info"]["total"] == 1
        assert [item["id"] for item in payload["task_tags"]] == [10]
        assert "Hidden" not in json.dumps(payload, default=str)
        # AppTest reruns the full page; reopen the production dialog for its submit.
        factory.return_value.return_value = {"action": "delete_task_tag", "tt_id": 20, "nonce": "forged-confirm"}
        app.button[0].click().run()
        assert not app.exception and app.error
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT id FROM eppm.task_tag ORDER BY id").fetchall() == [(10,), (20,)]


@pytest.mark.parametrize("entity", ["project", "task"])
def test_scoped_editor_attaches_and_removes_free_and_dictionary_tags_without_changing_hidden_owners(pg_database, business, entity):
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    prefix = "proj" if entity == "project" else "task"
    owner, hidden_owner = (1, 2) if entity == "project" else (10, 20)
    table, owner_column = entity + "_tag", entity + "_id"
    with psycopg.connect(pg_database.operator_url) as connection:
        group = connection.execute("INSERT INTO eppm.tag_group(tag_group_name) VALUES(%s) RETURNING id", (entity + "_tag",)).fetchone()[0]
        dictionary = connection.execute(
            "INSERT INTO eppm.tag_dictionnary(tag,tag_group_id) VALUES('Scoped dictionary tag',%s) RETURNING id", (group,),
        ).fetchone()[0]
        connection.execute(f"INSERT INTO eppm.{table}({owner_column},free_tag) VALUES(%s,'Hidden tag')", (hidden_owner,))
    app = AppTest.from_function(
        permission_control_app, args=(path, editor.actor, entity + "_tags"), default_timeout=30,
    ).run()
    assert not app.exception and not app.error
    assert not any("Hidden tag" in item.value for item in app.markdown)
    app.button(key=f"btn_confirm_attach_{prefix}_tag").click().run()
    assert not app.exception and app.error
    app.text_input(key=f"ti_attach_{prefix}_free_tag").set_value("  Scoped free tag  ")
    app.button(key=f"btn_confirm_attach_{prefix}_tag").click().run()
    assert not app.exception and not app.error
    app.text_input(key=f"ti_attach_{prefix}_free_tag").set_value("")
    app.selectbox(key=f"sb_attach_{prefix}_tag").set_value((dictionary, "Scoped dictionary tag"))
    app.button(key=f"btn_confirm_attach_{prefix}_tag").click().run()
    assert not app.exception and not app.error
    with psycopg.connect(pg_database.operator_url) as connection:
        attached = connection.execute(
            f"SELECT id,tag_id,free_tag FROM eppm.{table} WHERE {owner_column}=%s ORDER BY id", (owner,),
        ).fetchall()
    assert [(row[1], row[2]) for row in attached] == [(None, "Scoped free tag"), (dictionary, None)]
    assert any("Scoped dictionary tag" in item.value for item in app.markdown)
    delete_prefix = "pt" if entity == "project" else "tt"
    for assignment in attached:
        app.button(key=f"btn_del_{delete_prefix}_{assignment[0]}").click().run()
        assert not app.exception and not app.error
    app.button(key=f"btn_close_{prefix}_dialog").click().run()
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute(f"SELECT {owner_column},free_tag FROM eppm.{table}").fetchall() == [(hidden_owner, "Hidden tag")]


@pytest.mark.parametrize("entity", ["project", "task"])
def test_scoped_editor_validates_dates_and_manages_custom_and_full_period_pool_assignments(pg_database, business, entity):
    from datetime import date
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    prefix = "proj" if entity == "project" else "task"
    app = AppTest.from_function(
        permission_control_app, args=(path, editor.actor, entity + "_pools"), default_timeout=30,
    ).run()
    assert not app.exception and not app.error
    if entity == "task":
        assert any("Visible task" in item.value and "Project #1" in item.value for item in app.markdown)
        assert not any("Forged label" in item.value for item in app.markdown)
        app.button(key="btn_del_assign_task_1").click().run()
    app.radio(key=f"rb_assign_{prefix}_period_mode").set_value("custom").run()
    app.date_input(key=f"di_assign_{prefix}_s").set_value(date(2026, 1, 4))
    app.date_input(key=f"di_assign_{prefix}_e").set_value(date(2026, 1, 3))
    app.number_input(key=f"ni_assign_{prefix}_fte").set_value(4.0)
    app.text_input(key=f"ti_assign_{prefix}_notes").set_value("  Scoped allocation  ")
    app.button(key=f"btn_confirm_assign_{prefix}_pool").click().run()
    assert not app.exception and app.error
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.resource_pool_assignment WHERE notes='Scoped allocation'").fetchone()[0] == 0
    app.date_input(key=f"di_assign_{prefix}_e").set_value(date(2026, 1, 5))
    app.button(key=f"btn_confirm_assign_{prefix}_pool").click().run()
    assert not app.exception and not app.error
    with psycopg.connect(pg_database.operator_url) as connection:
        assignment = connection.execute(
            "SELECT id,project_id,task_id,fte_assigned,start_date,end_date FROM eppm.resource_pool_assignment WHERE notes='Scoped allocation'",
        ).fetchone()
    assert assignment[1:] == (1, None if entity == "project" else 10, 4.0, date(2026, 1, 4), date(2026, 1, 5))
    assert any("Custom Period" in item.value and "Overassigned" in item.value for item in app.markdown)
    app.button(key=f"btn_del_assign_{prefix}_{assignment[0]}").click().run()
    assert not app.exception and not app.error
    app.radio(key=f"rb_assign_{prefix}_period_mode").set_value("full").run()
    app.number_input(key=f"ni_assign_{prefix}_fte").set_value(0.5)
    app.text_input(key=f"ti_assign_{prefix}_notes").set_value("Full period")
    app.button(key=f"btn_confirm_assign_{prefix}_pool").click().run()
    assert not app.exception and not app.error
    assert any("Full " + entity.title() + " Duration" in item.value and "OK" in item.value for item in app.markdown)
    app.button(key=f"btn_close_{prefix}_pool_dialog").click().run()
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute(
            "SELECT project_id,task_id,fte_assigned,start_date,end_date FROM eppm.resource_pool_assignment WHERE notes='Full period'",
        ).fetchone() == (1, None if entity == "project" else 10, 0.5, None, None)
        assert connection.execute(
            "SELECT pool_id,project_id,task_id,fte_assigned FROM eppm.resource_pool_assignment WHERE id=2",
        ).fetchone() == (1, 2, 20, 2.0)


@pytest.mark.parametrize("entity", ["project", "task"])
def test_open_assignment_dialog_cannot_save_after_edit_permission_is_revoked(pg_database, business, entity):
    from streamlit.testing.v1 import AppTest

    path, service, admin, editor, _ = business
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})
    editor_grant = next(row["id"] for row in service.assignments(admin, editor.actor.user_id) if row["role"] == "project_editor")
    prefix = "proj" if entity == "project" else "task"
    app = AppTest.from_function(
        permission_control_app, args=(path, editor.actor, entity + "_pools"), default_timeout=30,
    ).run()
    assert not app.exception and not app.error
    app.text_input(key=f"ti_assign_{prefix}_notes").set_value("Stale pending assignment")
    service.revoke(admin, editor_grant)
    app.button(key=f"btn_confirm_assign_{prefix}_pool").click().run()
    assert not app.exception and not app.error and not app.button
    assert "read-only" in app.info[0].value
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT id,project_id,task_id,fte_assigned FROM eppm.resource_pool_assignment ORDER BY id").fetchall() == [
            (1, 1, 10, 1.0), (2, 2, 20, 2.0),
        ]


@pytest.mark.parametrize("entity", ["project", "task"])
def test_assignment_dialog_with_no_configured_pools_explains_why_assignment_is_unavailable(pg_database, business, entity):
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("DELETE FROM eppm.resource_pool")
    app = AppTest.from_function(
        permission_control_app, args=(path, editor.actor, entity + "_pools"), default_timeout=30,
    ).run()
    assert not app.exception and not app.error and not app.button and not app.selectbox
    assert "No resource pools configured" in app.warning[0].value


@pytest.mark.parametrize("surface,entity,display", [
    ("function_types", "function_type", "Engineering"),
    ("functions", "function", "Engineer"),
    ("teams", "team", "Delivery"),
    ("employees", "employee", "Rae"),
])
@pytest.mark.parametrize("action", ["add", "edit", "delete"])
def test_business_admin_catalog_menu_opens_the_requested_record_and_consumes_the_event_once(pg_database,
    business, surface, entity, display, action,
):
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, _, _, _, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function_type(function_type_id,function_type) VALUES(10,'Engineering')")
        connection.execute("INSERT INTO eppm.function(function_id,name,function_type_id) VALUES(10,'Engineer',10)")
        connection.execute("INSERT INTO eppm.team(team_id,team_name,manager_function_id) VALUES(10,'Delivery',10)")
        connection.execute("INSERT INTO eppm.team_function(team_id,function_id) VALUES(10,10)")
        connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email,function_id) VALUES(10,'Rae','Example','rae@example.test',10)")
    event = {
        "action": action + "_" + entity, entity + "_id": 10,
        entity + "_name": display, "nonce": "open-record",
    }
    with patch("app.presentation.pages.organization._table", return_value=event) as component:
        app = AppTest.from_function(
            shared_catalog_app, args=(path, manager.actor, surface), default_timeout=30,
        ).run()
        assert not app.exception and not app.error
        payload = component.call_args.kwargs
        assert len(payload["types" if surface == "function_types" else surface]) == 1
        if action == "edit":
            assert any(item.value == display for item in app.text_input)
        assert app.button
        app.run()
        assert not app.exception and not app.error and not app.button and not app.text_input
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.function").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM eppm.employee").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM eppm.team").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM eppm.app_user").fetchone()[0] == 2


@pytest.mark.parametrize("surface", ["function_types", "functions", "teams", "employees"])
def test_project_editor_cannot_render_shared_directory_payloads_or_open_forged_catalog_actions(business, surface):
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    with patch("app.presentation.pages.organization._table", return_value={"action": "add_employee", "nonce": "forged"}) as component:
        app = AppTest.from_function(
            shared_catalog_app, args=(path, editor.actor, surface), default_timeout=30,
        ).run()
    assert not app.exception and app.error and not app.button and not app.text_input
    component.assert_not_called()


@pytest.mark.parametrize("entity", ["type", "employee"])
def test_business_only_administrator_can_manage_directory_records_without_changing_application_identities(pg_database, business, entity):
    from streamlit.testing.v1 import AppTest
    from app.main import create_organization_service

    path, service, admin, _, _ = business
    manager = service.actor(service.sign_in(VerifiedIdentity(
        service.issuer, "directory-manager", "directory@example.test", "Directory Manager", 1000, 100000, True,
    )))
    service.set_status(admin, manager.user_id, "active")
    service.grant(admin, manager.user_id, "business_admin", {"kind": "all"})
    organization = create_organization_service(path, access=BusinessAccess(manager, service.policy))
    before_account = service.account(manager)
    with pytest.raises(AccessDenied):
        service.list_users(manager)

    def open_dialog(action, record_id=0):
        return AppTest.from_function(
            shared_directory_dialog_app, args=(path, manager, entity + "_" + action, record_id), default_timeout=30,
        ).run()

    app = open_dialog("add")
    assert not app.exception and not app.error
    if entity == "type":
        app.text_input[0].set_value("Reviewed type")
    else:
        next(item for item in app.text_input if "First Name" in item.label).set_value("Rae")
        next(item for item in app.text_input if "Last Name" in item.label).set_value("Record")
        next(item for item in app.text_input if "Email" in item.label).set_value("directory@example.test")
    next(item for item in app.button if "Save" in item.label).click().run()
    assert not app.exception and not app.error
    record_id = (organization.get_all_function_types()[0].function_type_id if entity == "type"
                 else organization.get_all_employees()[0].employee_id)
    assert service.account(manager) == before_account

    app = open_dialog("edit", record_id)
    if entity == "type":
        app.text_input[0].set_value("Renamed type")
    else:
        next(item for item in app.text_input if "First Name" in item.label).set_value("Robin")
        next(item for item in app.number_input if "Occupation" in item.label).set_value(60.0)
    next(item for item in app.button if "Save Changes" in item.label).click().run()
    assert not app.exception and not app.error
    if entity == "type":
        assert organization.get_function_type_by_id(record_id).function_type == "Renamed type"
    else:
        employee = organization.get_employee_by_id(record_id)
        assert employee.firstname == "Robin" and employee.occupation_percentage == 60.0
    app = open_dialog("delete", record_id)
    next(item for item in app.button if "Yes, Delete" in item.label).click().run()
    assert not app.exception and not app.error
    assert (organization.get_all_function_types() if entity == "type" else organization.get_all_employees()) == []
    assert service.account(manager) == before_account
    assert [assignment["role"] for assignment in service.assignments(admin, manager.user_id)] == ["business_admin"]
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_user").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM eppm.app_identity").fetchone()[0] == 3
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
