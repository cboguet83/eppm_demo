"""Application access workflows on real PostgreSQL with restricted credentials."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import json
from secrets import token_bytes, token_urlsafe

import psycopg
import pytest

from app.application.services.access import AccessService, AuthorizationPolicy, DeploymentAccessService, SessionLimits, session_digest
from app.domain.access.models import AccessDenied, AccessStorageError, Permission, ProjectScope, ReauthenticationRequired, VerifiedIdentity
from app.infrastructure.postgresql.access import PostgresAccessGateway, PostgresDeploymentAccessGateway
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.infrastructure.postgresql.pool import OperatorDatabase
from tests.postgresql.conftest import PostgreSQLFixture


@dataclass
class AccessScenario:
    """Shared real resources with an explicitly controllable policy clock."""

    setup: PostgreSQLFixture
    now: list[int]
    gateway: PostgresAccessGateway
    service: AccessService
    deployment: DeploymentAccessService


@pytest.fixture
def pg_access(pg_database, database):
    key = token_bytes(32)
    configure_signing_key(pg_database.operator_url, key.hex())
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
        connection.execute("INSERT INTO eppm.project_type(name) VALUES ('Other')")
        connection.execute("INSERT INTO eppm.project(name,project_type_id) VALUES ('First',1),('Second',2),('Third',1)")
    now = [1000]
    policy = AuthorizationPolicy(lambda: now[0], SessionLimits())
    gateway = PostgresAccessGateway(database, key, policy)
    service = AccessService(gateway, policy, "https://issuer.example.invalid", lambda: token_urlsafe(32))
    deployment = DeploymentAccessService(PostgresDeploymentAccessGateway(OperatorDatabase(pg_database.operator_url)),
                                        policy.clock, "test-operator", lambda: token_urlsafe(16))
    return AccessScenario(pg_database, now, gateway, service, deployment)


def identity(subject, *, now=1000, expires=100000, mfa=True):
    return VerifiedIdentity("https://issuer.example.invalid", subject, "same@example.invalid", "Test Account", now, expires, mfa)


def administrator(scenario):
    cookie = scenario.service.sign_in(identity("administrator"))
    actor = scenario.service.actor(cookie)
    scenario.deployment.bootstrap(actor.user_id)
    return actor


def test_sign_in_bootstrap_and_profile_use_the_actual_application_services(pg_access):
    cookie = pg_access.service.sign_in(identity("first"))
    actor, status, revision = pg_access.service.browser_identity(cookie)
    assert status == "pending" and revision == 0
    assert pg_access.service.account(actor)["display_name"] == "Test Account"
    assert [row["id"] for row in pg_access.deployment.pending_accounts()] == [actor.user_id]
    pg_access.deployment.bootstrap(actor.user_id)
    assert pg_access.service.capabilities(actor) == {Permission.ACCESS}
    assert pg_access.service.browser_identity(cookie)[1:] == ("active", 1)
    with pytest.raises(ValueError, match="already complete"):
        pg_access.deployment.bootstrap(actor.user_id)
    assert pg_access.service.scope_project_choices(actor, "second") == [{"id": 2, "name": "Second"}]
    assert pg_access.service.scope_catalog(actor)[0]["property_id"] == "project_type_id"


@pytest.mark.parametrize("operation", ["list_users", "register", "set_status", "grant", "revoke", "assignments", "scope_catalog", "scope_project_choices", "effective_access", "audit"])
def test_service_administration_denials_have_one_safe_log_and_no_mutations(pg_access, caplog, operation):
    admin = administrator(pg_access)
    user = pg_access.service.actor(pg_access.service.sign_in(identity("ordinary")))
    pg_access.service.set_status(admin, user.user_id, "active")
    before = pg_access.service.audit(admin)
    arguments = {"list_users": ("Private search",), "register": (pg_access.service.issuer, "Private subject", "Private label"),
                 "set_status": (admin.user_id, "disabled"), "grant": (user.user_id, "business_admin", {"kind": "all"}),
                 "revoke": (1,), "assignments": (admin.user_id,), "scope_catalog": (), "scope_project_choices": ("Private project",),
                 "effective_access": (admin.user_id, 1), "audit": ()}[operation]
    with pytest.raises(AccessDenied):
        getattr(pg_access.service, operation)(user, *arguments)
    events = [record.message for record in caplog.records if "access.authorization_denied" in record.message]
    assert len(events) == 1 and "Private" not in events[0]
    assert pg_access.service.audit(admin) == before


def test_distinct_scopes_and_property_grants_preserve_application_policy(pg_access):
    admin = administrator(pg_access)
    user = pg_access.service.actor(pg_access.service.sign_in(identity("editor")))
    pg_access.service.set_status(admin, user.user_id, "active")
    pg_access.service.grant(admin, user.user_id, "project_editor", {"kind": "projects", "project_ids": [1]})
    pg_access.service.grant(admin, user.user_id, "project_viewer", {"kind": "properties", "conditions": [
        {"property_id": "project_type_id", "operator": "eq", "value_ids": [2]}]})
    def inspect(store):
        return (pg_access.service.policy.projects(store, user),
                pg_access.service.policy.projects(store, user, Permission.EDIT))
    assert pg_access.gateway.run(inspect, actor=user) == ({1, 2}, {1})
    assert pg_access.service.capabilities(user) == {Permission.READ, Permission.EDIT}
    grants = pg_access.service.effective_access(admin, user.user_id, 2)
    assert [grant["role"] for grant in grants] == ["project_viewer"]
    assert [grant["matching_projects"] for grant in pg_access.service.assignments(admin, user.user_id)] == [1, 1]


def test_dangling_scope_does_not_abort_other_valid_grants_in_the_same_snapshot(pg_access):
    admin = administrator(pg_access)
    user = pg_access.service.actor(pg_access.service.sign_in(identity("reader")))
    pg_access.service.set_status(admin, user.user_id, "active")
    first = pg_access.service.grant(admin, user.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})
    pg_access.service.grant(admin, user.user_id, "project_editor", {"kind": "projects", "project_ids": [2]})
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_role_assignment SET scope_json='{\"kind\":\"projects\",\"project_ids\":[999]}' WHERE id=%s", (first,))
    assert pg_access.service.capabilities(user) == {Permission.READ, Permission.EDIT}
    assert pg_access.gateway.run(lambda store: pg_access.service.policy.projects(store, user), actor=user) == {2}
    assert pg_access.service.assignments(admin, user.user_id)[0]["problem"]


def test_global_finance_policy_evaluation_does_not_grant_portfolio_access(pg_access):
    admin = administrator(pg_access)
    user = pg_access.service.actor(pg_access.service.sign_in(identity("finance")))
    pg_access.service.set_status(admin, user.user_id, "active")
    pg_access.service.grant(admin, user.user_id, "finance_editor", {"kind": "all"})
    assert pg_access.service.capabilities(user) == {Permission.FINANCE}
    assert pg_access.gateway.run(lambda store: pg_access.service.policy.projects(store, user, Permission.FINANCE), actor=user) == {1, 2, 3}
    assert pg_access.gateway.run(lambda store: pg_access.service.policy.projects(store, user), actor=user) == set()


def test_session_rotation_activity_and_logout_preserve_authentication_and_revisions(pg_access):
    admin = administrator(pg_access)
    old_cookie = pg_access.service.sign_in(identity("user"))
    user = pg_access.service.actor(old_cookie)
    pg_access.service.set_status(admin, user.user_id, "active")
    revision = pg_access.service.browser_identity(old_cookie)[2]
    pg_access.now[0] = 1100
    new_cookie = pg_access.service.sign_in(identity("user", now=1100), old_cookie)
    with pytest.raises(AccessDenied):
        pg_access.service.actor(old_cookie)
    actor = pg_access.service.actor(new_cookie)
    assert actor.user_id == user.user_id
    pg_access.now[0] = 1200
    pg_access.service.activity(actor)
    current = pg_access.gateway.run(lambda store: store.session(actor.session_hash), actor=actor)
    assert (current["auth_time"], current["last_activity"], current["expires_at"]) == (1100, 1200, 2100)
    assert pg_access.service.browser_identity(new_cookie)[2] == revision
    pg_access.service.logout(actor)
    with pytest.raises(AccessDenied):
        pg_access.service.actor(new_cookie)
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute("SELECT revision FROM eppm.app_security_state").fetchone() == (revision,)
        assert connection.execute("SELECT count(*) FROM eppm.app_security_audit WHERE action='session.logout'").fetchone() == (1,)


@pytest.mark.parametrize("invalid", ["expired", "idle", "future_auth", "revoked", "missing"])
def test_browser_identity_rejects_invalid_current_sessions_without_activity(pg_access, invalid):
    cookie = pg_access.service.sign_in(identity("session"))
    digest = session_digest(cookie)
    statements = {"expired": "UPDATE eppm.app_session SET expires_at=1000", "idle": "UPDATE eppm.app_session SET last_activity=100",
                  "future_auth": "UPDATE eppm.app_session SET auth_time=1031", "revoked": "UPDATE eppm.app_session SET revoked=true",
                  "missing": "DELETE FROM eppm.app_session"}
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        connection.execute(statements[invalid])
    with pytest.raises(AccessDenied):
        pg_access.service.actor(cookie)
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_security_audit").fetchone() == (1,)


def test_recent_authentication_mfa_and_last_admin_rules_survive_service_adapter(pg_access):
    admin = administrator(pg_access)
    with pytest.raises(ValueError, match="At least one active"):
        pg_access.service.set_status(admin, admin.user_id, "disabled")
    pg_access.now[0] = 1300
    with pytest.raises(ReauthenticationRequired):
        pg_access.service.register(admin, pg_access.service.issuer, "other", "Other")
    assert pg_access.service.list_users(admin)
    policy = AuthorizationPolicy(lambda: 1000, SessionLimits(require_admin_mfa=True))
    gateway = PostgresAccessGateway(pg_access.gateway.database, pg_access.gateway.signer.key, policy)
    strict = AccessService(gateway, policy, pg_access.service.issuer, lambda: token_urlsafe(32))
    cookie = strict.sign_in(identity("administrator", mfa=False))
    assert strict.capabilities(strict.actor(cookie)) == set()


def test_registration_recovery_and_account_paging_preserve_safe_dtos(pg_access):
    admin = administrator(pg_access)
    pending = pg_access.service.register(admin, pg_access.service.issuer, "preregistered", "Pending label")
    assert pg_access.deployment.pending_accounts(after_id=pending - 1, limit=1)[0]["id"] == pending
    with pytest.raises(ValueError, match="verified OIDC"):
        pg_access.deployment.recover(pending, "Explicit recovery")
    actor = pg_access.service.actor(pg_access.service.sign_in(identity("preregistered")))
    assert actor.user_id == pending
    pg_access.deployment.recover(pending, "Explicit recovery")
    assert pg_access.service.account(actor)["status"] == "active"
    event = pg_access.service.audit(actor)[0]
    assert event["actor"] == "operator:test-operator" and json.loads(event["details_json"])["reason"] == "Explicit recovery"


def test_concurrent_logins_for_one_external_identity_create_one_account(pg_access):
    with ThreadPoolExecutor(max_workers=2) as executor:
        cookies = list(executor.map(lambda _: pg_access.service.sign_in(identity("shared")), range(2)))
    assert cookies[0] != cookies[1]
    actors = [pg_access.service.actor(cookie) for cookie in cookies]
    assert actors[0].user_id == actors[1].user_id
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_user").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM eppm.app_session").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM eppm.app_security_audit").fetchone() == (2,)


def retry_authentication_once(scenario):
    with psycopg.connect(scenario.setup.operator_url) as connection:
        connection.execute("CREATE SEQUENCE eppm.test_auth_attempt")
        connection.execute("""CREATE FUNCTION eppm.retry_test_authentication() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF nextval('eppm.test_auth_attempt')=1 THEN RAISE EXCEPTION 'Known rollback' USING ERRCODE='40001'; END IF;
            RETURN NEW; END $$""")
        connection.execute("CREATE TRIGGER retry_test_authentication BEFORE INSERT ON eppm.app_security_audit FOR EACH ROW EXECUTE FUNCTION eppm.retry_test_authentication()")


def test_whole_login_replay_preserves_cookie_and_correlation_without_duplicate_audit(pg_access):
    retry_authentication_once(pg_access)
    prepared = ["prepared-cookie-" + "x" * 32, "prepared-correlation-" + "y" * 32]
    generated = []
    def token():
        result = prepared[len(generated)]
        generated.append(result)
        return result
    service = AccessService(pg_access.gateway, pg_access.service.policy, pg_access.service.issuer, token)
    assert service.sign_in(identity("retried")) == prepared[0]
    assert generated == prepared
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_user").fetchone() == (1,)
        assert connection.execute("SELECT session_hash FROM eppm.app_session").fetchone() == (session_digest(prepared[0]),)
        assert connection.execute("SELECT correlation_id FROM eppm.app_security_audit").fetchall() == [(prepared[1],)]


def test_whole_login_replay_revalidates_token_expiry_before_second_attempt(pg_access):
    retry_authentication_once(pg_access)
    moments = iter([1000, 1002])
    policy = AuthorizationPolicy(lambda: next(moments), SessionLimits())
    service = AccessService(pg_access.gateway, policy, pg_access.service.issuer, lambda: token_urlsafe(32))
    with pytest.raises(AccessDenied):
        service.sign_in(identity("expires-during-retry", expires=1001))
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_user").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM eppm.app_session").fetchone() == (0,)


def test_failed_sign_in_audit_rolls_back_profile_session_rotation_and_audit(pg_access):
    cookie = pg_access.service.sign_in(identity("rotating"))
    actor = pg_access.service.actor(cookie)
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        connection.execute("CREATE FUNCTION eppm.fail_login_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'sensitive internal detail' USING ERRCODE='23514'; END $$")
        connection.execute("CREATE TRIGGER fail_login_audit BEFORE INSERT ON eppm.app_security_audit FOR EACH ROW EXECUTE FUNCTION eppm.fail_login_audit()")
    with pytest.raises(AccessStorageError) as error:
        pg_access.service.sign_in(replace(identity("rotating"), display_name="Changed"), cookie)
    assert "sensitive" not in str(error.value)
    assert pg_access.service.account(actor)["display_name"] == "Test Account"
    assert pg_access.service.actor(cookie).user_id == actor.user_id
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_session").fetchone() == (1,)


def test_service_revocation_removes_effective_access_and_appends_one_audit(pg_access):
    admin = administrator(pg_access)
    user = pg_access.service.actor(pg_access.service.sign_in(identity("revoked-reader")))
    pg_access.service.set_status(admin, user.user_id, "active")
    assignment = pg_access.service.grant(admin, user.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})
    assert pg_access.gateway.run(lambda store: store.assignment(assignment), actor=user)["user_id"] == user.user_id
    before = pg_access.service.audit(admin)
    pg_access.service.revoke(admin, assignment)
    assert pg_access.service.capabilities(user) == set()
    assert pg_access.gateway.run(lambda store: store.assignment(assignment), actor=admin) is None
    after = pg_access.service.audit(admin)
    assert len(after) == len(before) + 1 and after[0]["action"] == "role.revoke"


def test_native_permission_and_recency_failures_are_translated_at_gateway_boundary(pg_access):
    admin = administrator(pg_access)
    user = pg_access.service.actor(pg_access.service.sign_in(identity("ordinary-native")))
    pg_access.service.set_status(admin, user.user_id, "active")
    with pytest.raises(AccessDenied):
        pg_access.gateway.run(lambda store: store.change_status(admin.user_id, "disabled", user, 1000), write=True, actor=user)
    with pytest.raises(ReauthenticationRequired, match="Sign in again"):
        pg_access.gateway.run(lambda store: store.change_status(user.user_id, "disabled", admin, 1301), write=True, actor=admin)
    assert pg_access.service.account(user)["status"] == "active"
    pending = pg_access.service.register(admin, pg_access.service.issuer, "duplicate", "First")
    with pytest.raises(ValueError, match="already exists"):
        pg_access.service.register(admin, pg_access.service.issuer, "duplicate", "Second")
    assert [item["display_name"] for item in pg_access.service.list_users(admin) if item["id"] == pending] == ["First"]


def test_store_cannot_cross_actor_session_or_reveal_unbound_security_revision(pg_access):
    admin = administrator(pg_access)
    user = pg_access.service.actor(pg_access.service.sign_in(identity("private-session")))
    assert pg_access.gateway.run(lambda store: store.session(user.session_hash), actor=admin) is None
    assert pg_access.gateway.run(lambda store: store.security_revision(), actor=admin) == 1
    with pytest.raises(AccessDenied):
        pg_access.gateway.run(lambda store: store.security_revision())
    with pytest.raises(AccessDenied):
        pg_access.gateway.run(lambda store: store.scope_projects(ProjectScope("all")))


@pytest.mark.parametrize("operation", ["read_only", "different_actor", "activity_expiry", "bound_sign_in", "read_only_sign_in"])
def test_store_rejects_mismatched_mutation_context_before_any_change(pg_access, operation):
    admin = administrator(pg_access)
    user = pg_access.service.actor(pg_access.service.sign_in(identity("context-user")))
    calls = {
        "read_only": lambda store: store.change_status(user.user_id, "active", admin, 1000),
        "different_actor": lambda store: store.change_status(user.user_id, "active", user, 1000),
        "activity_expiry": lambda store: store.record_activity(admin, 1000, 9999),
        "bound_sign_in": lambda store: store.record_sign_in(identity("forged"), pg_access.service.issuer, "a" * 64, None, 1000, 1900, "request"),
        "read_only_sign_in": lambda store: store.record_sign_in(identity("forged"), pg_access.service.issuer, "a" * 64, None, 1000, 1900, "request"),
    }
    with pytest.raises(AccessDenied):
        pg_access.gateway.run(calls[operation], write=operation not in {"read_only", "read_only_sign_in"},
                              actor=None if operation == "read_only_sign_in" else admin)
    assert pg_access.service.account(user)["status"] == "pending"
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_session").fetchone() == (2,)


def test_failed_logout_audit_preserves_valid_session_and_security_revision(pg_access):
    cookie = pg_access.service.sign_in(identity("audit-logout"))
    actor = pg_access.service.actor(cookie)
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        connection.execute("CREATE FUNCTION eppm.fail_logout_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private audit detail' USING ERRCODE='23514'; END $$")
        connection.execute("CREATE TRIGGER fail_logout_audit BEFORE INSERT ON eppm.app_security_audit FOR EACH ROW EXECUTE FUNCTION eppm.fail_logout_audit()")
    with pytest.raises(AccessStorageError):
        pg_access.service.logout(actor)
    assert pg_access.service.browser_identity(cookie)[1:] == ("pending", 0)
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute("SELECT action FROM eppm.app_security_audit").fetchall() == [("authentication.success",)]


def test_exhausted_login_retries_return_safe_error_without_partial_identity(pg_access):
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        connection.execute("CREATE SEQUENCE eppm.exhausted_auth_attempt")
        connection.execute("""CREATE FUNCTION eppm.exhaust_test_authentication() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN PERFORM nextval('eppm.exhausted_auth_attempt'); RAISE EXCEPTION 'private retry diagnostic' USING ERRCODE='40001'; END $$""")
        connection.execute("CREATE TRIGGER exhaust_test_authentication BEFORE INSERT ON eppm.app_security_audit FOR EACH ROW EXECUTE FUNCTION eppm.exhaust_test_authentication()")
    with pytest.raises(AccessStorageError) as error:
        pg_access.service.sign_in(identity("exhausted"))
    assert "private" not in str(error.value)
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute("SELECT last_value FROM eppm.exhausted_auth_attempt").fetchone() == (3,)
        assert connection.execute("SELECT count(*) FROM eppm.app_identity").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM eppm.app_session").fetchone() == (0,)
