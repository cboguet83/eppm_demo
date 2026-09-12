"""Native access administration, mandatory audit and concurrent continuity."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
from psycopg.types.json import Jsonb
import pytest

from app.application.services.access import SessionLimits


def test_account_and_grant_reads_are_self_scoped_except_for_access_admins(authorized):
    assert authorized.query("SELECT id FROM eppm.app_user ORDER BY id") == [(1,)]
    assert authorized.query("SELECT DISTINCT user_id FROM eppm.app_role_assignment") == [(1,)]
    assert authorized.query("SELECT id FROM eppm.app_user ORDER BY id", user_id=5) == [(1,), (2,), (3,), (4,), (5,)]
    assert authorized.query("SELECT id FROM eppm.app_user ORDER BY id", user_id=4) == [(4,)]
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("UPDATE eppm.app_user SET status='pending' WHERE id=1")
    assert authorized.query("SELECT id,status FROM eppm.app_user") == [(1, "pending")]
    assert authorized.query("SELECT id FROM eppm.app_role_assignment") == []


@pytest.mark.parametrize("source", [
    "SELECT eppm.admin_set_status(3,'active')",
    "SELECT eppm.admin_grant(3,'business_admin','{\"kind\":\"all\"}')",
    "SELECT eppm.admin_revoke(1)",
    "SELECT eppm.admin_register('https://issuer.invalid','subject','Name')",
    "SELECT eppm.admin_resolve_scope('{\"kind\":\"all\"}')",
    "SELECT * FROM eppm.admin_project_choices('')",
    "SELECT eppm.admin_scope_catalog()",
    "UPDATE eppm.app_user SET status='active' WHERE id=3",
    "UPDATE eppm.app_role_assignment SET role='access_admin' WHERE user_id=1",
    "SELECT eppm.operator_appoint_admin(1,'fake operator','fake',1000,'fake',false)",
])
def test_ordinary_actors_cannot_administer_access_or_invoke_operator_paths(authorized, source):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query(source, write=True)


def test_registration_grant_and_revoke_have_atomic_trusted_audit(authorized):
    user_id = authorized.query("SELECT eppm.admin_register(%s,%s,%s)",
                               ("https://issuer.invalid", "external-subject", "Pending Person"), user_id=5, write=True)[0][0]
    assert authorized.query("SELECT status,display_name FROM eppm.app_user WHERE id=%s", (user_id,), user_id=5) == [("pending", "Pending Person")]
    grant = authorized.query("SELECT eppm.admin_grant(%s,'project_editor',%s)",
                             (user_id, Jsonb({"kind": "projects", "project_ids": [2, 1, 2]})), user_id=5, write=True)[0][0]
    repeated = authorized.query("SELECT eppm.admin_grant(%s,'project_editor',%s)",
                                (user_id, Jsonb({"kind": "projects", "project_ids": [1, 2]})), user_id=5, write=True)[0][0]
    assert repeated == grant
    assert authorized.query("SELECT scope_json FROM eppm.app_role_assignment WHERE id=%s", (grant,), user_id=5) == [(
        {"kind": "projects", "project_ids": [1, 2], "conditions": []},)]
    authorized.query("SELECT eppm.admin_set_status(%s,'active')", (user_id,), user_id=5, write=True)
    authorized.query("SELECT eppm.admin_revoke(%s)", (grant,), user_id=5, write=True)
    events = authorized.query("SELECT actor,target,action,correlation_id FROM eppm.app_security_audit ORDER BY id", user_id=5)
    assert [event[2] for event in events] == ["user.register", "role.grant", "role.grant", "user.status", "role.revoke"]
    assert all((actor, target, correlation) == ("5", str(user_id), "request-5") for actor, target, _, correlation in events)
    assert authorized.query("SELECT eppm.access_security_revision()") == [(5,)]
    assert authorized.query("SELECT id FROM eppm.app_security_audit") == []


@pytest.mark.parametrize("role,scope", [
    ("invented_role", {"kind": "all"}),
    ("business_admin", {"kind": "projects", "project_ids": [1]}),
    ("project_viewer", {"kind": "projects", "project_ids": [999]}),
    ("project_viewer", {"kind": "projects", "project_ids": [True]}),
])
def test_invalid_grants_do_not_change_assignments_audit_or_revision(authorized, role, scope):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        authorized.query("SELECT eppm.admin_grant(3,%s,%s)", (role, Jsonb(scope)), user_id=5, write=True)
    assert authorized.query("SELECT id FROM eppm.app_role_assignment WHERE user_id=3", user_id=5) == []
    assert authorized.query("SELECT eppm.access_security_revision()") == [(0,)]


def test_access_admin_scope_configuration_does_not_grant_business_reads(authorized):
    assert authorized.query("SELECT * FROM eppm.project", user_id=5) == []
    assert authorized.query("SELECT * FROM eppm.admin_project_choices('hidden')", user_id=5) == [(3, "Hidden")]
    assert authorized.query("SELECT eppm.admin_resolve_scope('{\"kind\":\"all\"}')", user_id=5) == [([1, 2, 3],)]
    assert authorized.query("SELECT * FROM eppm.project", user_id=5) == []
    assert authorized.query("SELECT * FROM eppm.admin_project_choices(%s)", ("%",), user_id=5) == []
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        authorized.query("SELECT * FROM eppm.admin_project_choices(%s)", ("x" * 257,), user_id=5)


def test_access_mutations_require_recent_authentication_and_configured_mfa(authorized):
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("UPDATE eppm.app_session SET auth_time=700 WHERE user_id=5")
    assert authorized.query("SELECT eppm.is_access_administrator()", user_id=5) == [(True,)]
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="Sign in again"):
        authorized.query("SELECT eppm.admin_set_status(3,'active')", user_id=5, write=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.database.run(lambda connection: connection.execute("SELECT eppm.admin_set_status(3,'active')"),
                                write=True, bind=authorized.binding(5, limits=SessionLimits(require_admin_mfa=True)))
    assert authorized.query("SELECT eppm.access_security_revision()") == [(0,)]


@pytest.mark.parametrize("operation", ["status", "revoke"])
def test_last_active_administrator_cannot_be_removed(authorized, operation):
    grant = authorized.query("SELECT id FROM eppm.app_role_assignment WHERE user_id=5", user_id=5)[0][0]
    source, parameters = ("SELECT eppm.admin_set_status(5,'disabled')", ()) if operation == "status" else ("SELECT eppm.admin_revoke(%s)", (grant,))
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="At least one active"):
        authorized.query(source, parameters, user_id=5, write=True)
    assert authorized.query("SELECT status FROM eppm.app_user WHERE id=5", user_id=5) == [("active",)]
    assert authorized.query("SELECT eppm.access_security_revision()") == [(0,)]


@pytest.mark.parametrize("source", [
    "SELECT eppm.admin_set_status(3,'disabled')",
    "SELECT eppm.admin_grant(3,'business_admin','{\"kind\":\"all\"}')",
    "SELECT eppm.admin_revoke(1)",
    "SELECT eppm.admin_register('https://issuer.invalid','subject','Pending user')",
])
def test_failed_access_audit_rolls_back_status_grants_accounts_and_revision(authorized, source):
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("CREATE FUNCTION eppm.fail_access_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Audit unavailable' USING ERRCODE='23514'; END $$")
        operator.execute("CREATE TRIGGER fail_access_audit BEFORE INSERT ON eppm.app_security_audit FOR EACH ROW EXECUTE FUNCTION eppm.fail_access_audit()")
    with pytest.raises(psycopg.errors.CheckViolation, match="Audit unavailable"):
        authorized.query(source, user_id=5, write=True)
    assert authorized.query("SELECT status FROM eppm.app_user WHERE id=3", user_id=5) == [("active",)]
    assert authorized.query("SELECT eppm.access_security_revision()") == [(0,)]
    assert authorized.query("SELECT count(*) FROM eppm.app_user", user_id=5) == [(5,)]
    assert authorized.query("SELECT count(*) FROM eppm.app_role_assignment", user_id=5) == [(5,)]


def test_categorical_scope_catalog_and_normalized_grants_share_stable_references(authorized):
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES ('REGION','Region','ENUM')")
        operator.execute("INSERT INTO eppm.schema_param_options(param_id,option_value) VALUES ('REGION','North')")
        operator.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES (1,'REGION','text','North')")
    catalog = authorized.query("SELECT eppm.admin_scope_catalog()", user_id=5)[0][0]
    assert catalog == [
        {"property_id": "project_type_id", "label": "Project template", "values": [{"id": 1, "label": "General"}]},
        {"property_id": "enum:1", "param_id": "REGION", "label": "Region", "values": [{"id": 1, "label": "North"}]},
    ]
    scope = {"kind": "properties", "conditions": [{"property_id": "enum:1", "operator": "eq", "value_ids": [1, 1]}]}
    grant = authorized.query("SELECT eppm.admin_grant(3,'project_viewer',%s)", (Jsonb(scope),), user_id=5, write=True)[0][0]
    assert authorized.query("SELECT id FROM eppm.project", user_id=3) == [(1,)]
    saved = authorized.query("SELECT scope_json FROM eppm.app_role_assignment WHERE id=%s", (grant,), user_id=5)[0][0]
    assert saved["project_ids"] == [] and saved["conditions"][0]["value_ids"] == [1]


def test_invalidated_assignment_requires_explicit_revocation_before_regrant(authorized):
    scope = Jsonb({"kind": "projects", "project_ids": [1]})
    grant = authorized.query("SELECT eppm.admin_grant(3,'project_viewer',%s)", (scope,), user_id=5, write=True)[0][0]
    authorized.query("DELETE FROM eppm.project WHERE id=1", user_id=4, write=True)
    authorized.query("INSERT INTO eppm.project(id,name) VALUES (1,'Replacement')", user_id=4, write=True)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="Revoke the invalid"):
        authorized.query("SELECT eppm.admin_grant(3,'project_viewer',%s)", (scope,), user_id=5, write=True)
    authorized.query("SELECT eppm.admin_revoke(%s)", (grant,), user_id=5, write=True)
    replacement = authorized.query("SELECT eppm.admin_grant(3,'project_viewer',%s)", (scope,), user_id=5, write=True)[0][0]
    assert replacement != grant
    assert authorized.query("SELECT id FROM eppm.project", user_id=3) == [(1,)]


@pytest.mark.parametrize("operation", ["status", "revoke"])
def test_concurrent_admin_removals_retry_and_preserve_one_active_admin(authorized, operation):
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("INSERT INTO eppm.app_user(id,status,created_at,updated_at) VALUES (6,'active',900,900)")
        operator.execute("INSERT INTO eppm.app_session VALUES ('session-6',6,950,2000,980,false,false)")
        operator.execute("INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by) VALUES (6,'access_admin','{\"kind\":\"all\"}',900,'setup')")
        grants = dict(operator.execute("SELECT user_id,id FROM eppm.app_role_assignment WHERE role='access_admin'"))
    barrier, attempts = Barrier(2), [0, 0]
    def remove(index):
        user_id = 5 + index
        def operation_body(connection):
            attempts[index] += 1
            if attempts[index] == 1:
                barrier.wait(timeout=10)
            if operation == "status":
                connection.execute("SELECT eppm.admin_set_status(%s,'disabled')", (user_id,))
            else:
                connection.execute("SELECT eppm.admin_revoke(%s)", (grants[user_id],))
        try:
            authorized.database.run(operation_body, write=True, bind=authorized.binding(user_id))
            return True
        except psycopg.errors.InvalidParameterValue:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(remove, range(2))) == [False, True]
    assert sum(attempts) >= 3
    with psycopg.connect(authorized.setup.operator_url) as operator:
        assert operator.execute("SELECT eppm.active_access_administrators()").fetchone() == (1,)
        assert operator.execute("SELECT count(*) FROM eppm.app_security_audit").fetchone() == (1,)


def test_bootstrap_is_once_only_requires_verified_identity_and_audits_recovery(pg_database):
    with psycopg.connect(pg_database.operator_url, autocommit=True) as operator:
        operator.execute("INSERT INTO eppm.app_user(created_at,updated_at) VALUES (900,900)")
        with operator.transaction():
            operator.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            with pytest.raises(psycopg.errors.InvalidParameterValue, match="verified OIDC"):
                operator.execute("SELECT eppm.operator_appoint_admin(1,'deployment','correlation',1000,'Initial setup',true)")
        operator.execute("INSERT INTO eppm.app_identity(user_id,issuer,subject,verified_at) VALUES (1,'https://issuer.invalid','subject',950)")
        with operator.transaction():
            operator.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            operator.execute("SELECT eppm.operator_appoint_admin(1,'deployment','correlation',1000,'Initial setup',true)")
        with operator.transaction():
            operator.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            with pytest.raises(psycopg.errors.InvalidParameterValue, match="already complete"):
                operator.execute("SELECT eppm.operator_appoint_admin(1,'deployment','correlation',1000,'Initial setup',true)")
        with operator.transaction():
            operator.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            operator.execute("SELECT eppm.operator_appoint_admin(1,'deployment','correlation',1001,'Documented recovery',false)")
        assert operator.execute("SELECT bootstrap_complete,revision FROM eppm.app_security_state").fetchone() == (True, 2)
        assert operator.execute("SELECT actor,action,details_json->>'reason' FROM eppm.app_security_audit ORDER BY id").fetchall() == [
            ("operator:deployment", "access.bootstrap", "Initial setup"),
            ("operator:deployment", "access.recover", "Documented recovery"),
        ]


def test_competing_bootstraps_create_one_initial_administrator(pg_database):
    with psycopg.connect(pg_database.operator_url) as operator:
        operator.execute("INSERT INTO eppm.app_user(created_at,updated_at) VALUES (900,900),(900,900)")
        operator.execute("INSERT INTO eppm.app_identity(user_id,issuer,subject,verified_at) VALUES (1,'https://issuer.invalid','first',950),(2,'https://issuer.invalid','second',950)")
    barrier, attempts = Barrier(2), [0, 0]
    def appoint(index):
        for _ in range(3):
            attempts[index] += 1
            try:
                with psycopg.connect(pg_database.operator_url) as operator:
                    operator.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                    operator.execute("SELECT count(*) FROM eppm.app_user")
                    if attempts[index] == 1:
                        barrier.wait(timeout=10)
                    operator.execute("SELECT eppm.operator_appoint_admin(%s,'deployment','correlation',1000,'Initial setup',true)", (index + 1,))
                return True
            except psycopg.errors.SerializationFailure:
                continue
            except psycopg.errors.InvalidParameterValue:
                return False
        pytest.fail("Bootstrap retry bound exhausted")
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(appoint, range(2))) == [False, True]
    with psycopg.connect(pg_database.operator_url) as operator:
        assert operator.execute("SELECT count(*) FROM eppm.app_role_assignment").fetchone() == (1,)
        assert operator.execute("SELECT count(*) FROM eppm.app_security_audit").fetchone() == (1,)


def test_failed_bootstrap_audit_rolls_back_account_grant_and_completion_marker(pg_database):
    with psycopg.connect(pg_database.operator_url, autocommit=True) as operator:
        operator.execute("INSERT INTO eppm.app_user(created_at,updated_at) VALUES (900,900)")
        operator.execute("INSERT INTO eppm.app_identity(user_id,issuer,subject,verified_at) VALUES (1,'https://issuer.invalid','subject',950)")
        operator.execute("CREATE FUNCTION eppm.fail_bootstrap_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Audit unavailable' USING ERRCODE='23514'; END $$")
        operator.execute("CREATE TRIGGER fail_bootstrap_audit BEFORE INSERT ON eppm.app_security_audit FOR EACH ROW EXECUTE FUNCTION eppm.fail_bootstrap_audit()")
        with pytest.raises(psycopg.errors.CheckViolation, match="Audit unavailable"):
            with operator.transaction():
                operator.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                operator.execute("SELECT eppm.operator_appoint_admin(1,'deployment','correlation',1000,'Initial setup',true)")
        assert operator.execute("SELECT status FROM eppm.app_user WHERE id=1").fetchone() == ("pending",)
        assert operator.execute("SELECT count(*) FROM eppm.app_role_assignment").fetchone() == (0,)
        assert operator.execute("SELECT bootstrap_complete,revision FROM eppm.app_security_state").fetchone() == (False, 0)
