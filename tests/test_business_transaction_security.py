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
    "UPDATE main.resource_pool_assignment SET project_id=1 WHERE id=2",
    "UPDATE main.resource_pool_assignment SET task_id=20 WHERE id=1",
    "INSERT OR REPLACE INTO main.resource_pool_assignment(id,pool_id,project_id,task_id,fte_assigned) VALUES(2,1,1,10,2)",
    "INSERT INTO main.task_dependencies(task_id,predecessor_task_id,link_type,lag_days) VALUES(20,10,'FS',0)",
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
