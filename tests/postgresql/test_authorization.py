"""Trusted context, permission parity and revocation on real PostgreSQL sessions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hmac
import json
from secrets import token_bytes
from threading import Event

import psycopg
from psycopg.types.json import Jsonb
import pytest

from app.application.services.access import SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import APPLICATION_ROLES, ROLE_PERMISSIONS, AccessDenied, Actor, DeploymentActor
from app.infrastructure.postgresql.authorization import ActorBinding, configure_signing_key, signing_key


def test_persisted_permissions_exactly_match_fixed_domain_roles(pg_database):
    expected = {(role, str(permission), role in APPLICATION_ROLES)
                for role, permissions in ROLE_PERMISSIONS.items() for permission in permissions}
    with psycopg.connect(pg_database.operator_url) as operator:
        assert set(operator.execute("SELECT role,permission,application_wide FROM eppm.role_permission")) == expected


def test_permissions_keep_each_grants_read_and_edit_scope_together(authorized):
    assert authorized.query("SELECT eppm.permission_projects('project.read'), eppm.permission_projects('project.edit')") == [([1, 2], [1])]
    assert authorized.query("SELECT eppm.permission_projects('project.read')", user_id=2) == [([3],)]
    assert authorized.query("SELECT eppm.has_business_read()", user_id=3) == [(False,)]
    assert authorized.query("SELECT eppm.has_global_permission('project.read'), eppm.permission_projects('project.edit')", user_id=4) == [(True, [1, 2, 3])]
    assert authorized.query("SELECT eppm.has_global_permission('access.manage'), eppm.has_business_read()", user_id=5) == [(True, False)]


@pytest.mark.parametrize("scope", [
    {"kind": "projects", "project_ids": [3, 999]},
    {"kind": "projects", "project_ids": [True]},
    {"kind": "all", "injected": True},
    {"kind": "properties", "conditions": [{"property_id": "missing", "operator": "eq", "value_ids": [1]}]},
])
def test_corrupt_or_dangling_grants_do_not_add_access(authorized, scope):
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("UPDATE eppm.app_role_assignment SET scope_json=%s WHERE user_id=1 AND role='project_editor'", (Jsonb(scope),))
    assert authorized.query("SELECT eppm.permission_projects('project.read'),eppm.permission_projects('project.edit')") == [([2], [])]


def test_application_role_requires_all_scope_and_honors_mfa_policy(authorized):
    binding = authorized.binding(4, limits=SessionLimits(require_admin_mfa=True))
    read = lambda connection: connection.execute("SELECT eppm.has_global_permission('business.manage')").fetchone()[0]
    assert authorized.database.run(read, bind=binding) is False
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("UPDATE eppm.app_session SET mfa=true WHERE user_id=4")
    assert authorized.database.run(read, bind=binding) is True
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("UPDATE eppm.app_role_assignment SET scope_json=%s WHERE user_id=4", (Jsonb({"kind": "projects", "project_ids": [1]}),))
    assert authorized.database.run(read, bind=binding) is False
    # MFA on application roles does not silently change scoped editor semantics.
    assert authorized.database.run(lambda connection: connection.execute("SELECT eppm.permission_projects('project.edit')").fetchone()[0],
                                   bind=authorized.binding(limits=SessionLimits(require_admin_mfa=True))) == [1]


@pytest.mark.parametrize("mutation", [
    "DELETE FROM eppm.app_session WHERE user_id=1",
    "UPDATE eppm.app_session SET revoked=true WHERE user_id=1",
    "UPDATE eppm.app_session SET expires_at=1000 WHERE user_id=1",
    "UPDATE eppm.app_session SET last_activity=100 WHERE user_id=1",
    "UPDATE eppm.app_session SET auth_time=1031 WHERE user_id=1",
    "UPDATE eppm.app_session SET user_id=2 WHERE user_id=1",
])
def test_binding_rejects_missing_revoked_expired_idle_or_mismatched_sessions(authorized, mutation):
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute(mutation)
    with pytest.raises(AccessDenied):
        authorized.query("SELECT 1")


@pytest.mark.parametrize("status", ["pending", "disabled"])
def test_nonactive_account_context_is_limited_to_account_screen(authorized, status):
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("UPDATE eppm.app_user SET status=%s WHERE id=1", (status,))
    assert authorized.query("SELECT eppm.current_actor(false)->>'status'") == [(status,)]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query("SELECT eppm.permission_projects('project.read')")


def test_permission_reads_never_extend_activity_or_authentication(authorized):
    for _ in range(2):
        authorized.query("SELECT eppm.has_business_read()")
    with psycopg.connect(authorized.setup.operator_url) as operator:
        assert operator.execute("SELECT auth_time,last_activity,expires_at FROM eppm.app_session WHERE user_id=1").fetchone() == (950, 980, 2000)


@pytest.mark.parametrize("source", [
    "SELECT * FROM eppm.request_binding_key",
    "UPDATE eppm.request_binding_key SET secret=decode(repeat('00',32),'hex')",
    "SELECT * FROM eppm.role_permission",
    "SELECT eppm.resolve_scope('{\"kind\":\"all\"}')",
    "SELECT eppm.permission_scopes('project.read')",
    "SELECT eppm.verified_context('{}','bad')",
])
def test_runtime_cannot_read_secrets_change_role_mapping_or_call_private_helpers(authorized, source):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query(source, write=True)


def test_unsigned_actor_flags_and_forged_signature_do_not_grant_permissions(authorized):
    def forge(connection):
        connection.execute("SELECT set_config('eppm.actor','4',true),set_config('eppm.operator','true',true)")
        connection.execute("SELECT set_config('eppm.context','{}',true),set_config('eppm.signature',repeat('0',64),true)")
        connection.execute("SELECT eppm.has_global_permission('business.manage')")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.database.run(forge, write=True)


def test_context_cannot_be_replayed_in_another_transaction_or_connection(authorized):
    proof = authorized.query("SELECT current_setting('eppm.context'),current_setting('eppm.signature')")[0]
    def replay(connection):
        connection.execute("SELECT eppm.bind_actor(%s,%s)", proof)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.database.run(replay)
    with psycopg.connect(authorized.setup.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            replay(connection)
    # A missing binding and a newly bound different actor cannot inherit it.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.database.run(lambda connection: connection.execute("SELECT eppm.has_business_read()"))
    assert authorized.query("SELECT eppm.permission_projects('project.read')", user_id=2) == [([3],)]


@pytest.mark.parametrize("change", [
    {"backend": -1}, {"started": 0}, {"now": "invalid"}, {"now": None},
    {"idle_seconds": 0}, {"reauthentication_seconds": -1}, {"admin_mfa": "true"},
    {"user_id": None}, {"session_hash": ""}, {"correlation_id": ""},
])
def test_even_signed_invalid_context_is_rejected_safely(authorized, change):
    def invalid(connection):
        authorized.binding()(connection)
        context = connection.execute("SELECT current_setting('eppm.context')::jsonb").fetchone()[0]
        document = json.dumps(context | change)
        signature = hmac.digest(authorized.key, document.encode(), "sha256").hex()
        connection.execute("SELECT eppm.bind_actor(%s,%s)", (document, signature))
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="Application access denied"):
        authorized.database.run(invalid)


def test_request_key_is_explicit_and_rotation_takes_effect_on_next_transaction(authorized):
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("DELETE FROM eppm.request_binding_key")
    with pytest.raises(AccessDenied):
        authorized.query("SELECT 1")
    replacement = token_bytes(32)
    configure_signing_key(authorized.setup.operator_url, replacement.hex())
    with pytest.raises(AccessDenied):
        authorized.query("SELECT 1")
    assert authorized.database.run(lambda connection: connection.execute("SELECT eppm.has_business_read()").fetchone()[0],
                                   bind=replace(authorized.binding(), key=replacement)) is True


@pytest.mark.parametrize("value", ["", "not-a-key", "00" * 31, "00" * 33, None])
def test_signing_key_validation_does_not_echo_invalid_configuration(value):
    with pytest.raises(ValueError, match="Configure a valid PostgreSQL request signing key"):
        signing_key(value)


def test_runtime_binding_refuses_deployment_actor_or_invalid_key(authorized):
    binding = authorized.binding()
    with pytest.raises(AccessDenied):
        ActorBinding(BusinessAccess(DeploymentActor("operator", "request"), binding.access.policy), authorized.key)
    with pytest.raises(AccessDenied):
        replace(binding, key=b"short")
    assert authorized.key.hex() not in repr(binding)
    assert signing_key(authorized.key.hex()) == authorized.key


def test_prior_revocation_forces_complete_retry_and_reauthorization(authorized):
    snapshot, revoked = Event(), Event()
    attempts = []
    def binding(connection):
        attempts.append(1)
        connection.execute("SELECT COUNT(*) FROM eppm.schema_migration")
        if len(attempts) == 1:
            snapshot.set()
            assert revoked.wait(5)
        authorized.binding()(connection)
    def revoke():
        assert snapshot.wait(5)
        with psycopg.connect(authorized.setup.operator_url) as operator:
            operator.execute("UPDATE eppm.app_session SET revoked=true WHERE user_id=1")
        revoked.set()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(revoke)
        with pytest.raises(AccessDenied):
            authorized.database.run(lambda connection: connection.execute("SELECT 1"), write=True, bind=binding)
        future.result(timeout=5)
    assert len(attempts) == 2


@pytest.mark.parametrize("mutation", [
    "UPDATE eppm.app_session SET revoked=true WHERE user_id=1",
    "UPDATE eppm.app_user SET status='disabled' WHERE id=1",
    "DELETE FROM eppm.app_role_assignment WHERE user_id=1",
])
def test_later_revocation_waits_for_already_authorized_business_write(authorized, mutation):
    def write(connection):
        assert connection.execute("SELECT eppm.permission_projects('project.edit')").fetchone()[0] == [1]
        with psycopg.connect(authorized.setup.operator_url) as operator:
            operator.execute("SET LOCAL lock_timeout='100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                operator.execute(mutation)
    authorized.database.run(write, write=True, bind=authorized.binding())
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute(mutation)


def test_privileged_helpers_resolve_catalogs_before_temporary_objects(authorized):
    def shadow(connection):
        connection.execute("CREATE TEMP TABLE pg_roles(rolname name,rolsuper boolean)")
        connection.execute("INSERT INTO pg_temp.pg_roles VALUES (current_user,true)")
        connection.execute("CREATE TEMP TABLE app_user(id bigint,status text)")
        connection.execute("INSERT INTO pg_temp.app_user VALUES (1,'disabled')")
        assert connection.execute("SELECT eppm.has_business_read()").fetchone() == (True,)
        connection.execute("DROP TABLE pg_temp.pg_roles,pg_temp.app_user")
    authorized.database.run(shadow, write=True, bind=authorized.binding())
    with psycopg.connect(authorized.setup.operator_url) as operator:
        paths = operator.execute("""SELECT proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='eppm' AND p.prosecdef""").fetchall()
        assert paths and all("search_path=pg_catalog, eppm, pg_temp" in row[0] for row in paths)
