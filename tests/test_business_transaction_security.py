"""Real SQLite read filtering, ownership checks, cascades and audit in the mutation transaction."""

from contextlib import closing, contextmanager
from pathlib import Path
import secrets
import sqlite3

import pytest

from app.application.services.access import AccessService, AuthorizationPolicy, DeploymentAccessService, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, VerifiedIdentity
from app.infrastructure.database.business_security import SqliteBusinessSecurity
from app.infrastructure.database.business_security import authorized_business_transaction
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.repositories.access import SqliteAccessGateway


@pytest.fixture
def business(tmp_path: Path):
    path = str(tmp_path / "business.db")
    init_db(path)
    with closing(get_db(path)) as conn, conn:
        conn.execute("INSERT INTO project(id,name) VALUES(1,'Visible'),(2,'Hidden')")
        conn.execute("INSERT INTO project_task(id,project_id,task_name,start_date,end_date) VALUES(10,1,'Visible task','2026-01-01','2026-01-05'),(20,2,'Hidden task','2026-01-01','2026-01-05')")
        conn.execute("INSERT INTO task_dependencies(task_id,predecessor_task_id,link_type,lag_days) VALUES(10,20,'FS',0)")
        conn.execute("UPDATE project_task SET predecessor_id=20 WHERE id=10")
        conn.execute("INSERT INTO schema_parameters(param_id,param_name,param_type) VALUES('DEPT','Department','ENUM')")
        conn.execute("INSERT INTO schema_param_options(param_id,option_value) VALUES('DEPT','Finance'),('DEPT','Delivery')")
        conn.execute("INSERT INTO project_property_value(project_id,param_id,kind,text_value) VALUES(1,'DEPT','text','Finance')")
        conn.execute("INSERT INTO resource_pool(id,name,capacity_fte) VALUES(1,'Reference pool',3)")
        conn.execute("INSERT INTO resource_pool_assignment(id,pool_id,project_id,task_id,fte_assigned) VALUES(1,1,1,10,1),(2,1,2,20,2)")
    policy = AuthorizationPolicy(lambda: 1000, SessionLimits())
    service = AccessService(SqliteAccessGateway(path), policy, "https://provider.example.test", lambda: secrets.token_urlsafe(32))

    def login(subject: str):
        return service.actor(service.sign_in(VerifiedIdentity(service.issuer, subject, "", subject, 1000, 100000, True)))

    admin, editor = login("admin"), login("editor")
    DeploymentAccessService(service.gateway, lambda: 1000, "test", lambda: secrets.token_urlsafe(16)).bootstrap(admin.user_id)
    service.set_status(admin, editor.user_id, "active")
    service.grant(admin, editor.user_id, "project_editor", {"kind": "projects", "project_ids": [1]})
    service.grant(admin, admin.user_id, "business_admin", {"kind": "all"})
    return path, service, admin, BusinessAccess(editor, policy), BusinessAccess(admin, policy)


@contextmanager
def transaction(path: str, access: BusinessAccess):
    """Use the same real connection for the current scope and actual writes."""
    with closing(get_db(path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        with authorized_business_transaction(conn, access):
            yield conn


def test_scope_is_applied_before_pages_totals_groups_and_relationship_labels(business):
    path, _, _, editor, _ = business
    with transaction(path, editor) as conn:
        assert conn.execute("SELECT id FROM project ORDER BY id LIMIT 1 OFFSET 1").fetchall() == []
        assert conn.execute("SELECT count(*) FROM project").fetchone()[0] == 1
        assert conn.execute("SELECT project_id,count(*) FROM project_task GROUP BY project_id").fetchall() == [(1, 1)]
        assert conn.execute("SELECT predecessor_id FROM project_task WHERE id=10").fetchone()[0] is None
        assert conn.execute("SELECT * FROM task_dependencies").fetchall() == []
        assert conn.execute("SELECT sum(fte_assigned) FROM resource_pool_assignment").fetchone()[0] == 1
        assert conn.execute("SELECT id FROM resource_pool_assignment WHERE id=2").fetchall() == []


def test_scoped_summary_cache_cannot_reuse_a_global_hidden_dependency_indicator(business):
    from app.infrastructure.database.planning_summary_cache import install_summary_cache, read_project_summaries

    path, _, _, editor, _ = business
    with closing(get_db(path)) as conn, conn:
        install_summary_cache(conn)
        conn.execute("INSERT INTO planning_summary_cache VALUES(1,'Visible','2026-01-01','2026-01-05',1,0,1)")
    with transaction(path, editor) as conn:
        result = read_project_summaries(conn, [1, 2])
        assert [item["id"] for item in result] == [1]
        assert result[0]["hasViolations"] is False
    with closing(get_db(path)) as conn:
        assert conn.execute("SELECT has_violations FROM planning_summary_cache WHERE project_id=1").fetchone()[0] == 1


@pytest.mark.parametrize("sql", [
    "UPDATE main.project SET name='Forbidden' WHERE id=2",
    "UPDATE main.project_task SET task_name='Forbidden' WHERE id=20",
    "UPDATE main.project_task SET project_id=2 WHERE id=10",
    "UPDATE main.project_task SET project_id=0 WHERE id=10",
    "UPDATE main.resource_pool_assignment SET project_id=1 WHERE id=2",
    "UPDATE main.resource_pool_assignment SET task_id=20 WHERE id=1",
    "INSERT OR REPLACE INTO main.resource_pool_assignment(id,pool_id,project_id,task_id,fte_assigned) VALUES(2,1,1,10,2)",
    "INSERT INTO main.task_dependencies(task_id,predecessor_task_id,link_type,lag_days) VALUES(20,10,'FS',0)",
    "INSERT INTO main.task_dependencies(task_id,predecessor_project_id,link_type,lag_days) VALUES(10,2,'FS',0)",
    "INSERT INTO main.task_tag(task_id,free_tag) VALUES(20,'Unauthorized tag')",
    "INSERT INTO main.task_tag(task_id,free_tag) VALUES(0,'Invalid owner')",
    "INSERT INTO main.task_tag(task_id,free_tag) VALUES(999,'Missing owner')",
    "DELETE FROM main.task_dependencies WHERE task_id=10",
    "DELETE FROM main.project WHERE id=1",
    "INSERT INTO main.project(name) VALUES('Forbidden')",
    "UPDATE main.project_property_value SET text_value='Delivery' WHERE project_id=1",
    "DELETE FROM main.project_property_value WHERE project_id=1",
    "UPDATE main.resource_pool SET capacity_fte=999 WHERE id=1",
    "DELETE FROM main.schema_param_options WHERE param_id='DEPT'",
])
def test_forged_child_owners_cross_project_writes_and_scope_property_edits_are_denied(business, sql):
    path, _, _, editor, _ = business
    with pytest.raises(AccessDenied):
        with transaction(path, editor) as conn:
            conn.execute("UPDATE main.project SET name='Would otherwise persist' WHERE id=1")
            conn.execute(sql)
    with closing(get_db(path)) as conn:
        assert conn.execute("SELECT name FROM project WHERE id=1").fetchone()[0] == "Visible"
        assert conn.execute("SELECT capacity_fte FROM resource_pool WHERE id=1").fetchone()[0] == 3


def test_ordinary_editor_can_change_project_fields_and_rewrite_unchanged_protected_value(business):
    path, _, _, editor, _ = business
    with transaction(path, editor) as conn:
        conn.execute("UPDATE main.project SET name='Allowed' WHERE id=1")
        conn.execute("UPDATE main.project_property_value SET text_value='Finance' WHERE project_id=1")
        conn.execute("INSERT INTO main.project_property_value(project_id,param_id,kind,text_value) VALUES(1,'DEPT','text','Finance') "
                     "ON CONFLICT(project_id,param_id) DO UPDATE SET text_value=excluded.text_value")
    with closing(get_db(path)) as conn:
        assert conn.execute("SELECT name FROM project WHERE id=1").fetchone()[0] == "Allowed"


def test_business_administrator_can_update_shared_capacity_through_the_guarded_transaction(business):
    path, _, _, _, manager = business
    with transaction(path, manager) as connection:
        connection.execute("UPDATE main.resource_pool SET capacity_fte=4 WHERE id=1")
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT capacity_fte FROM resource_pool WHERE id=1").fetchone()[0] == 4
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_business_admin_protected_changes_are_audited_and_audit_failure_rolls_back(business):
    path, service, admin, _, manager = business
    with transaction(path, manager) as conn:
        conn.execute("UPDATE main.project_property_value SET text_value='Delivery' WHERE project_id=1")
    event = service.audit(admin)[0]
    assert event["action"] == "project.protected_property_change" and event["actor"] == str(admin.user_id)
    with closing(get_db(path)) as conn, conn:
        conn.execute("CREATE TRIGGER audit_failure BEFORE INSERT ON app_security_audit BEGIN SELECT RAISE(ABORT,'test audit unavailable'); END")
    with pytest.raises(sqlite3.Error):
        with transaction(path, manager) as conn:
            conn.execute("UPDATE main.project_property_value SET text_value='Finance' WHERE project_id=1")
    with closing(get_db(path)) as conn:
        assert conn.execute("SELECT text_value FROM project_property_value WHERE project_id=1").fetchone()[0] == "Delivery"


def test_authorized_cascade_deletion_and_new_project_visibility_work_in_one_transaction(business):
    path, _, _, _, manager = business
    with transaction(path, manager) as conn:
        conn.execute("DELETE FROM main.task_dependencies")
        conn.execute("UPDATE main.project_task SET predecessor_id=NULL")
        conn.execute("DELETE FROM main.project_task WHERE project_id=1")
        conn.execute("DELETE FROM main.project WHERE id=1")
        new_id = conn.execute("INSERT INTO main.project(name) VALUES('New authorized project')").lastrowid
        assert conn.execute("SELECT name FROM project WHERE id=?", (new_id,)).fetchone()[0] == "New authorized project"
        assert conn.execute("SELECT * FROM project_property_value WHERE project_id=1").fetchall() == []
    with closing(get_db(path)) as conn:
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_revoked_session_and_invalid_context_cannot_open_business_transaction(business):
    path, service, _, editor, _ = business
    service.logout(editor.actor)
    with pytest.raises(AccessDenied):
        with transaction(path, editor):
            pass
    with pytest.raises(AccessDenied):
        BusinessAccess(None, editor.policy)
    with closing(get_db(path)) as conn:
        with pytest.raises(ValueError, match="transaction"):
            SqliteBusinessSecurity(conn, editor).install()


@pytest.mark.parametrize("factory,operation", [
    ("create_organization_service", "get_all_employees"),
    ("create_organization_service", "get_all_functions"),
    ("create_organization_service", "generate_next_employee_code"),
    ("create_schema_service", "get_snapshot"),
    ("create_schema_service", "get_all_parameters"),
    ("create_project_type_service", "get_all_types"),
    ("create_resource_pool_service", "get_all_mappings"),
    ("create_resource_pool_service", "get_all_pools"),
    ("create_resource_pool_service", "get_all_pool_groups"),
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


def test_public_reads_and_references_never_expose_hidden_owners_or_employee_details(business):
    from dataclasses import asdict
    from app import main

    path, _, _, editor, _ = business
    with closing(get_db(path)) as conn, conn:
        conn.execute("INSERT INTO function(function_id,name,hierarchy_level) VALUES(1,'Manager',3)")
        conn.execute("INSERT INTO employee(firstname,lastname,email,mobile,landline,employee_code,function_id) "
                     "VALUES('Fictional','Person','private@example.test','private-mobile','private-line','private-code',1)")
        conn.execute("INSERT INTO resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES(1,'employee',1,100)")
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


def project_permission_dialog(path, actor):
    """Render the actual project popup with a current application identity."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_workspace
    from app.presentation.components.project_dialogs import open_edit_project_dialog

    workspace = create_project_workspace(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))
    open_edit_project_dialog(1, workspace, read_only=True)


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


def test_project_editor_can_save_details_but_scope_fields_stay_disabled(business):
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
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT name FROM project WHERE id=1").fetchone()[0] == "Updated within scope"
        assert connection.execute("SELECT text_value FROM project_property_value WHERE project_id=1").fetchone()[0] == "Finance"


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


def permission_control_app(path, actor, surface):
    """Render real services, including direct modal entry after a stale browser event."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_collaboration_service, create_planning_workspace
    from app.presentation.pages import collaboration, planning

    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    service = create_collaboration_service(path, access=access)
    workspace = create_planning_workspace(path, access=access)
    surfaces = {
        "contacts": lambda: collaboration.render_project_contacts(1, service),
        "log": lambda: collaboration.render_project_log(1, service),
        "add_contact": lambda: collaboration._contact_dialog(1, service),
        "remove_contact": lambda: collaboration._remove_contact_dialog(1, service, 1),
        "edit_event": lambda: collaboration._event_dialog(1, service),
        "project_tags": lambda: planning._manage_project_tags_dialog(1, "Visible", workspace),
        "task_tags": lambda: planning._manage_task_tags_dialog(10, "Forged label", workspace),
        "project_pools": lambda: planning._manage_project_resource_pools_dialog(1, "Visible", workspace),
        "task_pools": lambda: planning._manage_task_resource_pools_dialog(10, "Forged label", 2, workspace),
        "import": lambda: planning._schedule_csv_dialog(workspace, 1, "import_csv_template"),
    }
    surfaces[surface]()


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


@pytest.mark.parametrize("entity", ["project", "task"])
def test_scoped_editor_attaches_and_removes_free_and_dictionary_tags_without_changing_hidden_owners(business, entity):
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    prefix = "proj" if entity == "project" else "task"
    owner, hidden_owner = (1, 2) if entity == "project" else (10, 20)
    table, owner_column = entity + "_tag", entity + "_id"
    with closing(get_db(path)) as connection, connection:
        group = connection.execute("INSERT INTO tag_group(tag_group_name) VALUES(?)", (entity + "_tag",)).lastrowid
        dictionary = connection.execute(
            "INSERT INTO tag_dictionnary(tag,tag_group_id) VALUES('Scoped dictionary tag',?)", (group,),
        ).lastrowid
        connection.execute(f"INSERT INTO {table}({owner_column},free_tag) VALUES(?,'Hidden tag')", (hidden_owner,))
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
    with closing(get_db(path)) as connection:
        attached = connection.execute(
            f"SELECT id,tag_id,free_tag FROM {table} WHERE {owner_column}=? ORDER BY id", (owner,),
        ).fetchall()
    assert [(row[1], row[2]) for row in attached] == [(None, "Scoped free tag"), (dictionary, None)]
    assert any("Scoped dictionary tag" in item.value for item in app.markdown)
    delete_prefix = "pt" if entity == "project" else "tt"
    for assignment in attached:
        app.button(key=f"btn_del_{delete_prefix}_{assignment[0]}").click().run()
        assert not app.exception and not app.error
    app.button(key=f"btn_close_{prefix}_dialog").click().run()
    with closing(get_db(path)) as connection:
        assert connection.execute(f"SELECT {owner_column},free_tag FROM {table}").fetchall() == [(hidden_owner, "Hidden tag")]


@pytest.mark.parametrize("entity", ["project", "task"])
def test_scoped_editor_validates_dates_and_manages_custom_and_full_period_pool_assignments(business, entity):
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
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT count(*) FROM resource_pool_assignment WHERE notes='Scoped allocation'").fetchone()[0] == 0
    app.date_input(key=f"di_assign_{prefix}_e").set_value(date(2026, 1, 5))
    app.button(key=f"btn_confirm_assign_{prefix}_pool").click().run()
    assert not app.exception and not app.error
    with closing(get_db(path)) as connection:
        assignment = connection.execute(
            "SELECT id,project_id,task_id,fte_assigned,start_date,end_date FROM resource_pool_assignment WHERE notes='Scoped allocation'",
        ).fetchone()
    assert assignment[1:] == (1, None if entity == "project" else 10, 4.0, "2026-01-04", "2026-01-05")
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
    with closing(get_db(path)) as connection:
        assert connection.execute(
            "SELECT project_id,task_id,fte_assigned,start_date,end_date FROM resource_pool_assignment WHERE notes='Full period'",
        ).fetchone() == (1, None if entity == "project" else 10, 0.5, None, None)
        assert connection.execute(
            "SELECT pool_id,project_id,task_id,fte_assigned FROM resource_pool_assignment WHERE id=2",
        ).fetchone() == (1, 2, 20, 2.0)


@pytest.mark.parametrize("entity", ["project", "task"])
def test_open_assignment_dialog_cannot_save_after_edit_permission_is_revoked(business, entity):
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
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT id,project_id,task_id,fte_assigned FROM resource_pool_assignment ORDER BY id").fetchall() == [
            (1, 1, 10, 1.0), (2, 2, 20, 2.0),
        ]


@pytest.mark.parametrize("entity", ["project", "task"])
def test_assignment_dialog_with_no_configured_pools_explains_why_assignment_is_unavailable(business, entity):
    from streamlit.testing.v1 import AppTest

    path, _, _, editor, _ = business
    with closing(get_db(path)) as connection, connection:
        connection.execute("DELETE FROM resource_pool")
    app = AppTest.from_function(
        permission_control_app, args=(path, editor.actor, entity + "_pools"), default_timeout=30,
    ).run()
    assert not app.exception and not app.error and not app.button and not app.selectbox
    assert "No resource pools configured" in app.warning[0].value


def shared_catalog_app(path, actor, surface):
    """Render a shared catalog through the actual actor-required composition root."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_organization_service
    from app.presentation.pages import organization

    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    getattr(organization, "render_" + surface)(create_organization_service(path, access=access))


@pytest.mark.parametrize("surface,entity,display", [
    ("function_types", "function_type", "Engineering"),
    ("functions", "function", "Engineer"),
    ("teams", "team", "Delivery"),
    ("employees", "employee", "Rae"),
])
@pytest.mark.parametrize("action", ["add", "edit", "delete"])
def test_business_admin_catalog_menu_opens_the_requested_record_and_consumes_the_event_once(
    business, surface, entity, display, action,
):
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest

    path, _, _, _, manager = business
    with closing(get_db(path)) as connection, connection:
        connection.execute("INSERT INTO function_type(function_type_id,function_type) VALUES(10,'Engineering')")
        connection.execute("INSERT INTO function(function_id,name,hierarchy_level,function_type_id) VALUES(10,'Engineer',3,10)")
        connection.execute("INSERT INTO team(team_id,team_name,manager_function_id,leader_function_id) VALUES(10,'Delivery',10,10)")
        connection.execute("INSERT INTO team_function(team_id,function_id) VALUES(10,10)")
        connection.execute("INSERT INTO employee(employee_id,firstname,lastname,email,employee_code,function_id) VALUES(10,'Rae','Example','rae@example.test','EX10',10)")
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
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT count(*) FROM function").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM employee").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM team").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM app_user").fetchone()[0] == 2


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


def shared_directory_dialog_app(path, actor, surface, record_id=0):
    """Keep a real directory dialog open while AppTest submits its widgets."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_organization_service
    from app.presentation.components import organization_dialogs as dialogs
    from app.presentation.components.organization_frames import functions_frame
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    service = create_organization_service(path, access=access)
    functions = functions_frame(service.get_all_functions())
    if surface == "type_add":
        dialogs._open_add_function_type_dialog(service)
    elif surface == "type_edit":
        record = service.get_function_type_by_id(record_id)
        dialogs._open_edit_function_type_dialog(service, record_id, record.function_type)
    elif surface == "type_delete":
        dialogs._open_delete_function_type_dialog(service, record_id, "Reviewed type")
    elif surface == "employee_add":
        dialogs._open_add_employee_dialog(service, functions)
    elif surface == "employee_edit":
        dialogs._open_edit_employee_dialog(service, record_id, functions)
    elif surface == "employee_delete":
        dialogs._open_delete_employee_dialog(service, record_id, "Reviewed employee")


@pytest.mark.parametrize("entity", ["type", "employee"])
def test_business_only_administrator_can_manage_directory_records_without_changing_application_identities(business, entity):
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
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT count(*) FROM app_user").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM app_identity").fetchone()[0] == 3
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
