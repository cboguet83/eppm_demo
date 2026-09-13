"""Full access security contracts on restricted native callbacks and real PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import secrets
from threading import Barrier

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from app.application.services.access import AccessService, AuthorizationPolicy
from app.domain.access.models import AccessDenied, AccessStorageError, Actor, Permission, ReauthenticationRequired, VerifiedIdentity
from app.infrastructure.postgresql.access import PostgresAccessGateway
from tests.postgresql.conftest import PostgreSQLFixture
from tests.postgresql.test_access_service import pg_access


@pytest.fixture
def security(pg_access):
    """Retain original project/property examples with real native sign-in storage."""
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name=CASE id WHEN 1 THEN 'A' WHEN 2 THEN 'B' ELSE 'C' END")
        connection.execute("UPDATE eppm.project_type SET name='Finance' WHERE id=2")
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES('DEPT','Department','ENUM')")
        connection.execute("INSERT INTO eppm.schema_param_options(id,param_id,option_value) VALUES(100,'DEPT','Finance'),(101,'DEPT','Delivery')")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES(1,'DEPT','text','Finance')")
    return pg_access.setup, pg_access.now, pg_access.gateway, pg_access.service.policy, pg_access.service, pg_access.deployment


def projects(gateway: PostgresAccessGateway, policy: AuthorizationPolicy, actor: Actor,
             permission: Permission = Permission.READ) -> set[int]:
    """Evaluate scope in a complete transaction bound to this exact actor."""
    return gateway.run(lambda store: policy.projects(store, actor, permission), actor=actor)


def require(gateway: PostgresAccessGateway, policy: AuthorizationPolicy, actor: Actor,
            permission: Permission, project_ids: list[int] | None = None) -> None:
    """Check the retained application rule under native row-level authorization."""
    gateway.run(lambda store: policy.require(store, actor, permission, project_ids), actor=actor)


def active_administrators(setup: PostgreSQLFixture) -> int:
    """Independently inspect committed active administrator cardinality."""
    with psycopg.connect(setup.operator_url) as connection:
        return connection.execute("SELECT count(DISTINCT u.id) FROM eppm.app_user u JOIN eppm.app_role_assignment a ON a.user_id=u.id WHERE u.status='active' AND a.role='access_admin'").fetchone()[0]


def persisted_assignments(setup: PostgreSQLFixture, user_id: int) -> list[tuple[int, str]]:
    """Inspect stored grants independently of a subject's current session."""
    with psycopg.connect(setup.operator_url) as connection:
        return connection.execute('SELECT id,role FROM eppm.app_role_assignment WHERE user_id=%s ORDER BY id', (user_id,)).fetchall()


def stored_session(setup: PostgreSQLFixture, session_hash: str) -> dict[str, object]:
    """Inspect fixture-only persisted session fields, including revoked sessions."""
    with psycopg.connect(setup.operator_url, row_factory=dict_row) as connection:
        return connection.execute('SELECT revoked,last_activity,expires_at FROM eppm.app_session WHERE session_hash=%s', (session_hash,)).fetchone()


def bootstrap_complete(setup: PostgreSQLFixture) -> bool:
    """Read the durable one-time setup marker through operator inspection."""
    with psycopg.connect(setup.operator_url) as connection:
        return connection.execute('SELECT bootstrap_complete FROM eppm.app_security_state').fetchone()[0]


def identity(subject: str, *, issuer: str = "https://issuer.example.invalid", auth_time: int = 1000) -> VerifiedIdentity:
    """Test-only verified identity injection; production callers use the OIDC adapter."""
    return VerifiedIdentity(issuer, subject, "same@example.test", "Test Account", auth_time, 100000, True)


@pytest.mark.parametrize("operation", [
    "list_users", "register", "set_status", "grant", "revoke", "assignments",
    "scope_catalog", "scope_project_choices", "effective_access", "audit",
])
def test_administration_denials_emit_one_safe_event_and_leave_security_data_unchanged(security, caplog, operation):
    import logging

    path, _, gateway, _, service, _ = security
    admin = administrator(security)
    cookie = service.sign_in(identity("ordinary-user"))
    user = service.actor(cookie)
    service.set_status(admin, user.user_id, "active")
    before = service.audit(admin)
    args = {
        "list_users": ("Private search",),
        "register": (service.issuer, "Private subject", "Private profile"),
        "set_status": (admin.user_id, "disabled"),
        "grant": (user.user_id, "business_admin", {"kind": "all"}),
        "revoke": (1,), "assignments": (admin.user_id,), "scope_catalog": (),
        "scope_project_choices": ("Private project search",),
        "effective_access": (admin.user_id, 1), "audit": (),
    }[operation]
    with caplog.at_level(logging.WARNING, logger="app.application.services.access"):
        with pytest.raises(AccessDenied):
            getattr(service, operation)(user, *args)
    records = [record for record in caplog.records if record.name == "app.application.services.access"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert json.loads(message.removeprefix("security.event ")) == {
        "action": "access.authorization_denied", "outcome": "denied", "actor": str(user.user_id),
        "correlation": user.correlation_id, "permission": "access.manage", "reauthentication_required": False,
    }
    assert "Private" not in message and cookie not in message and user.session_hash not in message
    assert service.audit(admin) == before
    assert service.assignments(admin, user.user_id) == []
    assert active_administrators(path) == 1
    assert len(service.list_users(admin)) == 2


@pytest.mark.parametrize("failure", ["last_admin", "invalid_scope", "reauthentication", "invalid_profile"])
def test_rejected_administration_changes_log_failure_category_after_atomic_rollback(security, caplog, failure):
    import logging

    path, now, gateway, _, service, _ = security
    admin = replace(administrator(security), correlation_id="request-reference\nforged.event")
    before = service.audit(admin)
    if failure == "reauthentication":
        now[0] += 300
    with caplog.at_level(logging.WARNING, logger="app.application.services.access"):
        with pytest.raises(ValueError):
            if failure == "last_admin":
                service.set_status(admin, admin.user_id, "disabled")
            elif failure == "invalid_scope":
                service.grant(admin, admin.user_id, "project_editor", {"kind": "projects", "project_ids": []})
            elif failure == "invalid_profile":
                service.register(admin, service.issuer, "Private subject", "Private profile\nInjected")
            else:
                service.grant(admin, admin.user_id, "business_admin", {"kind": "all"})
    records = [record for record in caplog.records if record.name == "app.application.services.access"]
    assert len(records) == 1
    message = records[0].getMessage()
    event = json.loads(message.removeprefix("security.event "))
    assert event["action"] == ("access.authorization_denied" if failure == "reauthentication" else "access.validation_failed")
    assert event["reauthentication_required"] == (failure == "reauthentication")
    assert event["correlation"] == admin.correlation_id and len(message.splitlines()) == 1
    assert "Private" not in message and "Injected" not in message and admin.session_hash not in message
    assert service.audit(admin) == before
    assert active_administrators(path) == 1
    assert len(service.list_users(admin)) == 1


@pytest.mark.parametrize("corrupt_scope", [
    {"kind": "unsupported"}, {"kind": "projects", "project_ids": [999]},
])
def test_corrupt_persisted_edit_scope_never_borrows_valid_viewer_access(security, corrupt_scope):
    path, _, gateway, policy, service, _ = security
    admin = administrator(security)
    user = service.actor(service.sign_in(identity("damaged-grant")))
    service.set_status(admin, user.user_id, "active")
    viewer = service.grant(admin, user.user_id, "project_viewer", {"kind": "all"})
    editor = service.grant(admin, user.user_id, "project_editor", {"kind": "projects", "project_ids": [1]})
    # Simulate damaged stored authorization data without disabling database constraints.
    with psycopg.connect(path.operator_url) as connection:
        connection.execute("UPDATE eppm.app_role_assignment SET scope_json=%s WHERE id=%s",
                                 (Jsonb(corrupt_scope), editor))
    assert projects(gateway, policy, user, Permission.READ) == {1, 2, 3}
    assert projects(gateway, policy, user, Permission.EDIT) == set()
    with pytest.raises(AccessDenied):
        require(gateway, policy, user, Permission.EDIT, [1])
    assert service.capabilities(user) == {Permission.READ}
    assert [item["assignment_id"] for item in service.effective_access(admin, user.user_id, 1)] == [viewer]
    damaged = next(item for item in service.assignments(admin, user.user_id) if item["id"] == editor)
    assert damaged["problem"] and damaged["matching_projects"] == 0


def test_verified_reauthentication_rotates_cookie_and_preserves_current_scoped_grants(security):
    path, now, gateway, policy, service, _ = security
    admin = administrator(security)
    original = service.sign_in(identity("rotated-user"))
    user = service.actor(original)
    service.set_status(admin, user.user_id, "active")
    service.grant(admin, user.user_id, "project_editor", {"kind": "projects", "project_ids": [1]})
    now[0] += 100
    replacement = service.sign_in(identity("rotated-user", auth_time=now[0]), original)
    assert replacement != original
    with pytest.raises(AccessDenied):
        service.actor(original)
    with pytest.raises(AccessDenied):
        service.actor(secrets.token_urlsafe(32))
    current = service.actor(replacement)
    assert current.user_id == user.user_id
    assert stored_session(path, user.session_hash)["revoked"]
    assert not stored_session(path, current.session_hash)["revoked"]
    assert projects(gateway, policy, current, Permission.EDIT) == {1}


@pytest.mark.parametrize("status", ["pending", "disabled"])
def test_last_administrator_state_change_rolls_back_status_and_audit(security, status):
    path, _, gateway, _, service, _ = security
    admin = administrator(security)
    before = service.audit(admin)
    with pytest.raises(ValueError, match="At least one active"):
        service.set_status(admin, admin.user_id, status)
    assert service.account(admin)["status"] == "active"
    assert service.audit(admin) == before
    assert active_administrators(path) == 1


def test_administration_rejects_unknown_targets_and_provider_mismatches_without_changes(security):
    path, _, _, _, service, _ = security
    admin = administrator(security)
    before = service.audit(admin)
    operations = [
        lambda: service.set_status(admin, 999, "active"),
        lambda: service.grant(admin, 999, "project_viewer", {"kind": "all"}),
        lambda: service.revoke(admin, 999),
        lambda: service.effective_access(admin, 999, 1),
    ]
    for operation in operations:
        with pytest.raises(AccessDenied):
            operation()
    with pytest.raises(ValueError, match="configured OIDC issuer"):
        service.register(admin, "https://different.example.test", "subject", "Same Name")
    with pytest.raises(ValueError, match="Unknown user status"):
        service.set_status(admin, admin.user_id, "deleted")
    assert service.audit(admin) == before
    assert len(service.list_users(admin)) == 1


@pytest.mark.parametrize("condition", [{}, "executable_expression()", {
    "property_id": 7, "operator": "eq", "value_ids": [1],
}, {"property_id": "", "operator": "eq", "value_ids": [1]}])
def test_scope_grants_reject_malformed_nested_property_conditions(security, condition):
    path, _, _, _, service, _ = security
    admin = administrator(security)
    before = service.audit(admin)
    with pytest.raises(ValueError, match="Invalid property"):
        service.grant(admin, admin.user_id, "project_viewer", {"kind": "properties", "conditions": [condition]})
    assert service.audit(admin) == before
    assert [row["role"] for row in service.assignments(admin, admin.user_id)] == ["access_admin"]


def test_deleted_reused_project_and_option_ids_never_retarget_old_grants(security):
    path, _, gateway, policy, service, _ = security
    admin = administrator(security)
    user = service.actor(service.sign_in(identity("reference-user")))
    service.set_status(admin, user.user_id, "active")
    service.grant(admin, user.user_id, "project_editor", {"kind": "projects", "project_ids": [2]})
    key = next(item["property_id"] for item in service.scope_catalog(admin) if item.get("param_id") == "DEPT")
    service.grant(admin, user.user_id, "project_viewer", {"kind": "properties", "conditions": [
        {"property_id": key, "operator": "eq", "value_ids": [100]},
    ]})
    with psycopg.connect(path.operator_url) as connection:
        assert projects(gateway, policy, user) == {1, 2}
        connection.execute("DELETE FROM eppm.project WHERE id=2")
        connection.execute("INSERT INTO eppm.project(id,name,project_type_id) VALUES(2,'Replacement',2)")
        connection.execute("DELETE FROM eppm.schema_param_options WHERE id=100")
        connection.execute("INSERT INTO eppm.schema_param_options(id,param_id,option_value) VALUES(100,'DEPT','Finance')")
    assert projects(gateway, policy, user) == set()
    assert all(item["problem"] for item in service.assignments(admin, user.user_id))
    with pytest.raises(ValueError, match="Revoke"):
        service.grant(admin, user.user_id, "project_editor", {"kind": "projects", "project_ids": [2]})


def test_replaced_project_type_and_retyped_enum_invalidate_existing_scopes(security):
    path, _, gateway, policy, service, _ = security
    admin = administrator(security)
    user = service.actor(service.sign_in(identity("property-user")))
    service.set_status(admin, user.user_id, "active")
    key = next(item["property_id"] for item in service.scope_catalog(admin) if item.get("param_id") == "DEPT")
    for prop, value in (("project_type_id", 2), (key, 100)):
        service.grant(admin, user.user_id, "project_viewer", {"kind": "properties", "conditions": [
            {"property_id": prop, "operator": "eq", "value_ids": [value]},
        ]})
    with psycopg.connect(path.operator_url) as connection:
        assert projects(gateway, policy, user) == {1, 2}
        connection.execute("UPDATE eppm.project SET project_type_id=1 WHERE project_type_id=2")
        connection.execute("DELETE FROM eppm.project_type WHERE id=2")
        connection.execute("INSERT INTO eppm.project_type(id,name) VALUES(2,'Replacement')")
        connection.execute("UPDATE eppm.project SET project_type_id=2 WHERE id=2")
        connection.execute("UPDATE eppm.schema_parameters SET param_type='TEXT' WHERE param_id='DEPT'")
        connection.execute("UPDATE eppm.schema_parameters SET param_type='ENUM' WHERE param_id='DEPT'")
    assert projects(gateway, policy, user) == set()
    assert all(item["problem"] for item in service.assignments(admin, user.user_id))


def test_business_reset_preserves_accounts_audit_setup_and_invalidates_old_project_scopes(security, clients, tmp_path):
    from app.operator_services import create_maintenance_service

    path, _, gateway, policy, service, operator = security
    admin = administrator(security)
    service.grant(admin, admin.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})
    before = service.audit(admin)
    maintenance = create_maintenance_service(path.operator_url, backup_directory=tmp_path, archive_tools=clients)
    for reset in (lambda: maintenance.flush(flush_all=True), lambda: maintenance.seed_defaults(force=True)):
        reset()
        assert service.account(admin)["status"] == "active"
        assert service.audit(admin) == before
        assert len(service.assignments(admin, admin.user_id)) == 2
        assert bootstrap_complete(path)
        assert projects(gateway, policy, admin) == set()
        with pytest.raises(ValueError, match="already complete"):
            operator.bootstrap(admin.user_id)


def test_access_explanation_names_the_matching_assignment_without_returning_business_data(security):
    path, _, _, _, service, _ = security
    admin = administrator(security)
    user = service.actor(service.sign_in(identity("explain-user")))
    service.set_status(admin, user.user_id, "active")
    reader = service.grant(admin, user.user_id, "project_viewer", {"kind": "all"})
    editor = service.grant(admin, user.user_id, "project_editor", {"kind": "projects", "project_ids": [1]})
    assert service.capabilities(admin) == {Permission.ACCESS}
    assert service.capabilities(user) == {Permission.READ, Permission.EDIT}
    assert [item["assignment_id"] for item in service.effective_access(admin, user.user_id, 1)] == [reader, editor]
    assert service.effective_access(admin, user.user_id, 2) == [
        {"assignment_id": reader, "role": "project_viewer", "permissions": [Permission.READ], "requires_mfa": False},
    ]
    assert service.scope_project_choices(admin, "B") == [{"id": 2, "name": "B"}]
    with pytest.raises(AccessDenied):
        service.scope_project_choices(user)
    with pytest.raises(AccessDenied):
        service.effective_access(user, admin.user_id, 1)
    service.set_status(admin, user.user_id, "disabled")
    assert service.effective_access(admin, user.user_id, 1) == []


def administrator(security):
    """Create a verified pending account and appoint it through the deployment API."""
    path, _, _, _, service, operator = security
    cookie = service.sign_in(identity("administrator"))
    actor = service.actor(cookie)
    operator.bootstrap(actor.user_id)
    return actor


def test_unknown_and_concurrent_logins_are_pending_distinct_by_issuer_subject(security):
    path, _, gateway, policy, service, _ = security
    barrier = Barrier(2)

    def login():
        barrier.wait()
        return service.actor(service.sign_in(identity("same-subject")))

    with ThreadPoolExecutor(2) as executor:
        actors = list(executor.map(lambda _: login(), range(2)))
    assert actors[0].user_id == actors[1].user_id
    assert service.account(actors[0])["status"] == "pending"
    assert persisted_assignments(path, actors[0].user_id) == []
    with pytest.raises(AccessDenied):
        projects(gateway, policy, actors[0])
    other = service.actor(service.sign_in(identity("different-subject")))
    second_provider = AccessService(gateway, policy, "https://other.example.test", lambda: secrets.token_urlsafe(32))
    third = second_provider.actor(second_provider.sign_in(identity("same-subject", issuer=second_provider.issuer)))
    assert len({actors[0].user_id, other.user_id, third.user_id}) == 3
    with pytest.raises(AccessDenied):
        service.sign_in(identity("bad", issuer="https://unconfigured.example.test"))


def test_fixed_permissions_do_not_borrow_another_assignments_scope(security):
    path, _, gateway, policy, service, _ = security
    admin = administrator(security)
    user = service.actor(service.sign_in(identity("scoped")))
    service.set_status(admin, user.user_id, "active")
    service.grant(admin, user.user_id, "project_viewer", {"kind": "all"})
    service.grant(admin, user.user_id, "project_editor", {"kind": "projects", "project_ids": [1]})
    service.grant(admin, user.user_id, "project_approver", {"kind": "properties", "conditions": [
        {"property_id": "project_type_id", "operator": "eq", "value_ids": [2]}]})
    assert projects(gateway, policy, user) == {1, 2, 3}
    assert projects(gateway, policy, user, Permission.EDIT) == {1}
    assert projects(gateway, policy, user, Permission.APPROVE) == {2}
    assert projects(gateway, policy, admin) == set()
    for permission, ids in ((Permission.EDIT, [2]), (Permission.APPROVE, [1]), (Permission.CREATE, None)):
        with pytest.raises(AccessDenied):
            require(gateway, policy, user, permission, ids)
    business = service.actor(service.sign_in(identity("business")))
    service.set_status(admin, business.user_id, "active")
    service.grant(admin, business.user_id, "business_admin", {"kind": "all"})
    assert projects(gateway, policy, business, Permission.EDIT) == {1, 2, 3}
    assert projects(gateway, policy, business, Permission.APPROVE) == set()
    with pytest.raises(AccessDenied):
        require(gateway, policy, business, Permission.ACCESS)


def test_property_scopes_use_current_values_and_deleted_references_never_retarget(security):
    path, _, gateway, policy, service, _ = security
    admin = administrator(security)
    user = service.actor(service.sign_in(identity("enum-scope")))
    service.set_status(admin, user.user_id, "active")
    catalog = service.scope_catalog(admin)
    key = next(item["property_id"] for item in catalog if item.get("param_id") == "DEPT")
    grant = service.grant(admin, user.user_id, "project_editor", {"kind": "properties", "conditions": [
        {"property_id": key, "operator": "in", "value_ids": [100]},
        {"property_id": "project_type_id", "operator": "eq", "value_ids": [1]},
    ]})
    assert projects(gateway, policy, user, Permission.EDIT) == {1}
    with psycopg.connect(path.operator_url) as connection:
        connection.execute("UPDATE eppm.project_property_value SET text_value='Delivery' WHERE project_id=1")
    assert projects(gateway, policy, user, Permission.EDIT) == set()
    with psycopg.connect(path.operator_url) as connection:
        connection.execute("DELETE FROM eppm.project_property_value WHERE param_id='DEPT'")
        connection.execute("DELETE FROM eppm.schema_param_options WHERE param_id='DEPT'")
        connection.execute("DELETE FROM eppm.schema_parameters WHERE param_id='DEPT'")
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES('DEPT','Replacement','ENUM')")
        connection.execute("INSERT INTO eppm.schema_param_options(id,param_id,option_value) VALUES(100,'DEPT','Finance')")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES(1,'DEPT','text','Finance')")
    assert projects(gateway, policy, user, Permission.EDIT) == set()
    assert next(row for row in service.assignments(admin, user.user_id) if row["id"] == grant)["problem"]


def test_missing_and_unsupported_scope_references_are_rejected_before_grant(security):
    path, _, gateway, _, service, _ = security
    admin = administrator(security)
    scopes = [{"kind":"projects", "project_ids":[999]}, {"kind":"properties", "conditions":[
        {"property_id":"project_type_id", "operator":"in", "value_ids":[999]}]},
        {"kind":"properties", "conditions":[{"property_id":"email", "operator":"eq", "value_ids":[1]}]}]
    for scope in scopes:
        with pytest.raises(ValueError):
            service.grant(admin, admin.user_id, "project_viewer", scope)
    assert len(persisted_assignments(path, admin.user_id)) == 1
    with pytest.raises(ValueError):
        service.grant(admin, admin.user_id, "invented_admin", {"kind":"all"})
    with pytest.raises(ValueError):
        service.grant(admin, admin.user_id, "business_admin", {"kind":"projects", "project_ids":[1]})


def test_revocation_disabling_and_logout_affect_existing_sessions_immediately(security):
    path, _, gateway, policy, service, _ = security
    admin = administrator(security)
    cookie = service.sign_in(identity("user"))
    tab1, tab2 = service.actor(cookie), service.actor(cookie)
    service.set_status(admin, tab1.user_id, "active")
    assignment = service.grant(admin, tab1.user_id, "project_editor", {"kind":"projects", "project_ids":[1]})
    service.revoke(admin, assignment)
    for actor in (tab1, tab2):
        with pytest.raises(AccessDenied):
            require(gateway, policy, actor, Permission.EDIT, [1])
    service.set_status(admin, tab1.user_id, "disabled")
    next_login = service.actor(service.sign_in(identity("user")))
    assert service.account(next_login)["status"] == "disabled"
    service.logout(tab1)
    with pytest.raises(AccessDenied):
        service.account(tab2)
    assert service.account(next_login)["id"] == tab1.user_id


def test_idle_expiry_and_recent_authentication_with_active_sessions_beyond_token_and_eight_hours(security):
    path, now, _, _, service, _ = security
    admin = administrator(security)
    now[0] = 1300
    with pytest.raises(ReauthenticationRequired):
        service.grant(admin, admin.user_id, "project_viewer", {"kind":"all"})
    # Rendering and background checks do not extend the idle timestamp.
    for timestamp in (1400, 1600, 1899):
        now[0] = timestamp
        service.account(admin)
    now[0] = 1900
    with pytest.raises(AccessDenied):
        service.account(admin)
    with pytest.raises(AccessDenied):
        service.actor(service.sign_in(replace(identity("expired"), expires_at=now[0])))
    now[0] = 1000
    short = service.actor(service.sign_in(replace(identity("short"), expires_at=1100)))
    now[0] = 1100
    service.account(short)
    now[0] = 1000
    active = service.actor(service.sign_in(identity("long")))
    for timestamp in range(1500, 29800, 500):
        now[0] = timestamp
        service.activity(active)
    now[0] = 29800
    service.activity(active)
    now[0] = 30699
    service.account(active)
    now[0] = 30700
    with pytest.raises(AccessDenied):
        service.account(active)
    service.sign_in(identity("long"))


def test_shared_cookie_activity_extends_both_tabs_and_expired_sessions_cannot_revive(security):
    path, now, gateway, _, service, _ = security
    cookie = service.sign_in(identity('shared-browser'))
    first_tab = service.actor(cookie)
    second_tab = service.actor(cookie)
    now[0] = 1500
    service.activity(first_tab)
    session = stored_session(path, second_tab.session_hash)
    assert session['last_activity'] == 1500
    assert session['expires_at'] == 2400
    now[0] = 2300
    service.account(second_tab)
    now[0] = 2400
    with pytest.raises(AccessDenied):
        service.activity(first_tab)
    with pytest.raises(AccessDenied):
        service.account(second_tab)


def test_concurrent_bootstrap_is_one_time_and_grants_only_access_admin(security):
    path, _, gateway, _, service, operator = security
    users = [service.actor(service.sign_in(identity(name))) for name in ("one", "two")]
    barrier = Barrier(2)

    def appoint(actor):
        barrier.wait()
        try:
            operator.bootstrap(actor.user_id)
            return "success"
        except ValueError:
            return "refused"

    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(appoint, users)) == ["refused", "success"]
    assert active_administrators(path) == 1
    assert sum(len(persisted_assignments(path, user.user_id)) for user in users) == 1
    assert bootstrap_complete(path)
    with pytest.raises(ValueError):
        operator.bootstrap(users[0].user_id)


def test_concurrent_disables_and_revocations_cannot_remove_last_administrator(security):
    path, _, gateway, _, service, _ = security
    first = administrator(security)
    second = service.actor(service.sign_in(identity("second-admin")))
    service.set_status(first, second.user_id, "active")
    grant = service.grant(first, second.user_id, "access_admin", {"kind":"all"})
    barrier = Barrier(2)

    def demote(number):
        barrier.wait()
        try:
            if number == 0:
                service.set_status(first, first.user_id, "disabled")
            else:
                service.revoke(second, grant)
            return "success"
        except (ValueError, AccessDenied):
            return "refused"

    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(demote, range(2))) == ["refused", "success"]
    assert active_administrators(path) == 1


def test_recovery_requires_verified_account_and_reason_and_audit_failure_rolls_back(security):
    path, _, gateway, _, service, operator = security
    admin = administrator(security)
    unverified = service.register(admin, service.issuer, "pre-registered", "Pending")
    with pytest.raises(ValueError):
        operator.recover(unverified, "Verified by operator")
    user = service.actor(service.sign_in(identity("recover")))
    for reason in ("", "line\nbreak"):
        with pytest.raises(ValueError):
            operator.recover(user.user_id, reason)
    with psycopg.connect(path.operator_url) as connection:
        connection.execute("CREATE FUNCTION eppm.reject_security_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit unavailable' USING ERRCODE='23514'; END $$")
        connection.execute("CREATE TRIGGER reject_security_audit BEFORE INSERT ON eppm.app_security_audit FOR EACH ROW EXECUTE FUNCTION eppm.reject_security_audit()")
    with pytest.raises(AccessStorageError):
        operator.recover(user.user_id, "Operator verified identity")
    assert service.account(user)["status"] == "pending"
    assert persisted_assignments(path, user.user_id) == []
    with psycopg.connect(path.operator_url) as connection:
        connection.execute("DROP TRIGGER reject_security_audit ON eppm.app_security_audit")
    operator.recover(user.user_id, "Operator verified identity")
    event = service.audit(admin)[0]
    assert event["action"] == "access.recover"
    assert event["actor"] == "operator:test-operator"
    assert json.loads(event["details_json"])["reason"] == "Operator verified identity"
    with psycopg.connect(path.operator_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute("DELETE FROM eppm.app_security_audit")
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute("UPDATE eppm.app_security_audit SET actor='rewritten'")


def test_production_administrator_access_requires_verified_mfa(security):
    path, _, gateway, policy, service, _ = security
    admin = administrator(security)
    cookie = service.sign_in(replace(identity("administrator"), mfa=False))
    actor = service.actor(cookie)
    strict = AuthorizationPolicy(policy.clock, replace(policy.limits, require_admin_mfa=True))
    with pytest.raises(AccessDenied):
        require(gateway, strict, actor, Permission.ACCESS)
    require(gateway, strict, admin, Permission.ACCESS)
