"""Native values and permanent invariants through an authorized nonowner pool."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from secrets import token_bytes
from threading import Barrier

import psycopg
from psycopg import sql
import pytest

from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.authorization import ActorBinding, configure_signing_key
from app.application.services.access import AuthorizationPolicy, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.shared.config.database import DatabaseConfig


@dataclass(frozen=True)
class BoundBusinessDatabase:
    """Use the production pool and permissions for a real test administrator."""

    database: Database
    binding: ActorBinding

    def run[Result](self, operation: Callable[[psycopg.Connection], Result], *, write: bool = False) -> Result:
        """Preserve complete callback execution with the fixture's trusted actor."""
        return self.database.run(operation, write=write, bind=self.binding)


@pytest.fixture
def business(pg_database):
    key = token_bytes(32)
    configure_signing_key(pg_database.operator_url, key.hex())
    with psycopg.connect(pg_database.operator_url) as operator:
        operator.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
        operator.execute("INSERT INTO eppm.project(name) VALUES ('First'),('Second')")
        operator.execute("INSERT INTO eppm.wbs(code) VALUES ('A'),('B')")
        operator.execute("INSERT INTO eppm.resource_pool(name) VALUES ('Pool')")
        operator.execute("INSERT INTO eppm.resource_pool_group(name) VALUES ('First'),('Second'),('Third')")
        operator.execute("INSERT INTO eppm.employee(firstname,lastname,email,employee_code) VALUES ('Test','Person','person@example.invalid','TEST')")
        operator.execute("INSERT INTO eppm.app_user(status,created_at,updated_at) VALUES ('active',900,900)")
        operator.execute("INSERT INTO eppm.app_session VALUES ('business-session',1,950,2000,980,true,false)")
        operator.execute("""INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES (1,'business_admin','{"kind":"all"}',900,'test setup')""")
    resource = Database(DatabaseConfig(pg_database.runtime_url, pool_min=1, pool_max=3))
    resource.open()
    try:
        access = BusinessAccess(Actor(1, "business-session", "integrity-check"), AuthorizationPolicy(lambda: 1000, SessionLimits()))
        yield BoundBusinessDatabase(resource, ActorBinding(access, key))
    finally:
        resource.close()


def execute(database, source, parameters=(), *, write=False):
    def operation(connection):
        cursor = connection.execute(source, parameters)
        return cursor.fetchall() if cursor.description is not None else []
    return database.run(operation, write=write)


def test_native_baseline_contains_every_current_business_table(pg_database):
    baseline = json.loads((Path(__file__).parents[2] / "docs/implementation/benchmarks/sqlite-baseline.json").read_text())
    replaced = {"schema_migration", "display_revision", "pool_capacity_revision", "pool_capacity_cache",
                "pool_capacity_employee", "planning_summary_cache"}
    expected = set(baseline["row_counts"]) - replaced
    with psycopg.connect(pg_database.operator_url) as operator:
        actual = {row[0] for row in operator.execute("SELECT tablename FROM pg_tables WHERE schemaname='eppm'")}
    assert actual == expected | {
        "schema_migration", "database_identity", "request_binding_key", "role_permission",
        "project_cache_revision", "pool_cache_revision", "catalog_cache_revision",
        "pool_capacity_cache", "planning_summary_cache", "operator_seed_state",
    }


def test_native_money_dates_booleans_and_json_round_trip_exactly(business):
    amount = Decimal("9007199254740993.01234567890123456789")
    execute(business, "UPDATE eppm.project SET planned_budget=%s WHERE id=1", (amount,), write=True)
    assert execute(business, "SELECT planned_budget FROM eppm.project WHERE id=1") == [(amount,)]
    rows = execute(business, """INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date)
        VALUES (1,'Task',%s,%s) RETURNING id,start_date,end_date""", (date(2026, 1, 1), date(2026, 1, 2)), write=True)
    assert type(rows[0][0]) is int and rows[0][1:] == (date(2026, 1, 1), date(2026, 1, 2))
    assert execute(business, "SELECT is_general FROM eppm.project_type") == [(True,)]


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_project_budgets_reject_nonfinite_amounts(business, value):
    with pytest.raises(psycopg.errors.CheckViolation):
        execute(business, "UPDATE eppm.project SET actual_budget=%s WHERE id=1", (value,), write=True)


def test_runtime_direct_writes_require_serializable_transactions(pg_database, business):
    with psycopg.connect(pg_database.runtime_url) as connection:
        with pytest.raises(psycopg.errors.ActiveSqlTransaction, match="serializable"):
            business.binding(connection)
    with psycopg.connect(pg_database.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("UPDATE eppm.project SET name='not committed' WHERE id=1")
    assert execute(business, "SELECT name FROM eppm.project WHERE id=1") == [("First",)]


def test_case_insensitive_catalog_and_single_general_constraints(business):
    with pytest.raises(psycopg.errors.UniqueViolation):
        execute(business, "INSERT INTO eppm.project_type(name) VALUES ('GENERAL')", write=True)
    with pytest.raises(psycopg.errors.UniqueViolation):
        execute(business, "INSERT INTO eppm.project_type(name,is_general) VALUES ('Other',true)", write=True)
    with pytest.raises(psycopg.errors.RestrictViolation):
        execute(business, "DELETE FROM eppm.project_type", write=True)


def test_typed_properties_preserve_kind_and_order_invariants(business):
    execute(business, "INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES ('P','Property','TEXT')", write=True)
    with pytest.raises(psycopg.errors.CheckViolation):
        execute(business, "INSERT INTO eppm.project_property_value(project_id,param_id,kind) VALUES (1,'P','number')", write=True)
    execute(business, "INSERT INTO eppm.project_property_value(project_id,param_id,kind) VALUES (1,'P','list')", write=True)
    execute(business, "INSERT INTO eppm.project_property_value_item VALUES (1,'P',0,'first')", write=True)
    with pytest.raises(psycopg.errors.UniqueViolation):
        execute(business, "INSERT INTO eppm.project_property_value_item VALUES (1,'P',1,'first')", write=True)
    execute(business, "DELETE FROM eppm.project_property_value WHERE project_id=1", write=True)
    assert execute(business, "SELECT COUNT(*) FROM eppm.project_property_value_item") == [(0,)]


def test_hierarchy_codes_are_stable_optional_and_referenced_deletion_is_restricted(business):
    hierarchy = execute(business, "INSERT INTO eppm.hierarchy_type(code) VALUES ('service') RETURNING id", write=True)[0][0]
    execute(business, "INSERT INTO eppm.hierarchy_type_translation VALUES (%s,'en','Service')", (hierarchy,), write=True)
    execute(business, "UPDATE eppm.resource_pool SET hierarchy_type_id=%s WHERE id=1", (hierarchy,), write=True)
    with pytest.raises(psycopg.errors.CheckViolation):
        execute(business, "UPDATE eppm.hierarchy_type SET code='changed'", write=True)
    with pytest.raises(psycopg.errors.RestrictViolation):
        execute(business, "DELETE FROM eppm.hierarchy_type", write=True)
    execute(business, "UPDATE eppm.resource_pool SET hierarchy_type_id=NULL", write=True)
    execute(business, "DELETE FROM eppm.hierarchy_type", write=True)
    assert execute(business, "SELECT COUNT(*) FROM eppm.hierarchy_type_translation") == [(0,)]


def test_pool_group_membership_rejects_cycles_on_insert_and_update(business):
    execute(business, "INSERT INTO eppm.resource_pool_group_member(group_id,child_group_id) VALUES (1,2),(2,3)", write=True)
    with pytest.raises(psycopg.errors.CheckViolation, match="cycle"):
        execute(business, "INSERT INTO eppm.resource_pool_group_member(group_id,child_group_id) VALUES (3,1)", write=True)
    with pytest.raises(psycopg.errors.CheckViolation, match="cycle"):
        execute(business, "UPDATE eppm.resource_pool_group_member SET group_id=3 WHERE group_id=1", write=True)
    with pytest.raises(psycopg.errors.CheckViolation):
        execute(business, "INSERT INTO eppm.resource_pool_group_member(group_id,pool_id,child_group_id) VALUES (1,1,3)", write=True)


def test_calendar_exception_intervals_are_inclusive_and_can_be_updated(business):
    first = execute(business, """INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage)
        VALUES (1,'2026-01-01','2026-01-03',50) RETURNING exception_id""", write=True)[0][0]
    with pytest.raises(psycopg.errors.CheckViolation, match="overlap"):
        execute(business, """INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage)
            VALUES (1,'2026-01-03','2026-01-04',0)""", write=True)
    execute(business, "UPDATE eppm.employee_calendar_exception SET end_date='2026-01-04' WHERE exception_id=%s", (first,), write=True)
    execute(business, """INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage)
        VALUES (1,'2026-01-05','2026-01-06',25)""", write=True)
    execute(business, "DELETE FROM eppm.employee WHERE employee_id=1", write=True)
    assert execute(business, "SELECT COUNT(*) FROM eppm.employee_calendar_exception") == [(0,)]


def test_wbs_total_is_enforced_across_projects_on_insert_and_update(business):
    execute(business, "INSERT INTO eppm.project_wbs VALUES (1,1,60),(2,1,40)", write=True)
    execute(business, "UPDATE eppm.project_wbs SET percentage=60 WHERE project_id=1", write=True)
    with pytest.raises(psycopg.errors.CheckViolation, match="100"):
        execute(business, "UPDATE eppm.project_wbs SET percentage=41 WHERE project_id=2", write=True)
    execute(business, "UPDATE eppm.project_wbs SET wbs_id=2 WHERE project_id=2", write=True)
    with pytest.raises(psycopg.errors.RestrictViolation):
        execute(business, "DELETE FROM eppm.wbs WHERE id=1", write=True)


def test_task_and_assignment_ownership_and_date_invariants(business):
    task = execute(business, """INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date)
        VALUES (1,'Task','2026-01-01','2026-01-02') RETURNING id""", write=True)[0][0]
    with pytest.raises(psycopg.errors.CheckViolation):
        execute(business, "UPDATE eppm.project_task SET end_date='2025-01-01'", write=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        execute(business, "INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES (1,2,%s,1)", (task,), write=True)
    execute(business, "INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES (1,1,%s,1)", (task,), write=True)
    with pytest.raises(psycopg.errors.CheckViolation):
        execute(business, "UPDATE eppm.project_task SET project_id=2", write=True)
    execute(business, "DELETE FROM eppm.project_task", write=True)
    assert execute(business, "SELECT COUNT(*) FROM eppm.resource_pool_assignment") == [(0,)]


def create_finance(database):
    def save(connection):
        identity = connection.execute("""INSERT INTO eppm.finance_snapshot(number,name,status,author,created_at)
            VALUES (1,'Plan','Draft','test',1) RETURNING id""").fetchone()[0]
        connection.execute("INSERT INTO eppm.finance_row VALUES (%s,'WBS',0)", (identity,))
        connection.execute("INSERT INTO eppm.finance_amount VALUES (%s,'WBS',2026,%s)", (identity, Decimal("90071992547409.91")))
        connection.execute("UPDATE eppm.finance_snapshot SET sealed=true WHERE id=%s", (identity,))
        return identity
    return database.run(save, write=True)


@pytest.mark.parametrize("source", [
    "UPDATE eppm.finance_snapshot SET name='changed'", "DELETE FROM eppm.finance_snapshot",
    "INSERT INTO eppm.finance_row VALUES (1,'OTHER',1)", "INSERT INTO eppm.finance_amount VALUES (1,'WBS',2027,1)",
    "UPDATE eppm.finance_row SET position=1", "DELETE FROM eppm.finance_row",
    "UPDATE eppm.finance_amount SET amount=1", "DELETE FROM eppm.finance_amount",
])
def test_sealed_finance_records_cannot_be_changed(business, source):
    create_finance(business)
    with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
        execute(business, source, write=True)
    assert execute(business, "SELECT amount FROM eppm.finance_amount") == [(Decimal("90071992547409.91"),)]


def test_finance_cancellation_is_validated_and_immutable(business):
    create_finance(business)
    with pytest.raises(psycopg.errors.CheckViolation, match="cancellation"):
        execute(business, "INSERT INTO eppm.finance_cancellation VALUES (1,'Approved','test',2)", write=True)
    execute(business, "INSERT INTO eppm.finance_cancellation VALUES (1,'Draft','test',2)", write=True)
    with pytest.raises(psycopg.errors.UniqueViolation):
        execute(business, "INSERT INTO eppm.finance_cancellation VALUES (1,'Draft','test',3)", write=True)
    with pytest.raises(psycopg.errors.CheckViolation):
        execute(business, "DELETE FROM eppm.finance_cancellation", write=True)


@pytest.mark.parametrize("amount", [Decimal("-0.01"), Decimal("0.001"), Decimal("NaN"), Decimal("Infinity")])
def test_finance_rejects_negative_nonfinite_and_subcent_values_without_rounding(business, amount):
    execute(business, "INSERT INTO eppm.finance_snapshot(number,name,status,author,created_at) VALUES (1,'Plan','Draft','test',1)", write=True)
    execute(business, "INSERT INTO eppm.finance_row VALUES (1,'WBS',0)", write=True)
    with pytest.raises(psycopg.errors.CheckViolation):
        execute(business, "INSERT INTO eppm.finance_amount VALUES (1,'WBS',2026,%s)", (amount,), write=True)


def test_audit_history_is_append_only_even_for_the_operator(pg_database, business):
    # An ordinary authorized protected write creates its mandatory audit event.
    execute(business, "INSERT INTO eppm.project_type(name) VALUES ('Audited')", write=True)
    with psycopg.connect(pg_database.operator_url, autocommit=True) as operator:
        assert operator.execute("SELECT count(*) FROM eppm.app_security_audit").fetchone()[0] == 1
        for source in ("UPDATE eppm.app_security_audit SET action='changed'", "DELETE FROM eppm.app_security_audit"):
            with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
                operator.execute(source)


@pytest.mark.parametrize("kind", ["wbs", "calendar", "group"])
def test_concurrent_aggregate_and_hierarchy_writes_preserve_integrity(business, kind):
    barrier = Barrier(2)
    attempts = [0, 0]
    source, statements = {
        "wbs": ("project_wbs", ["INSERT INTO eppm.project_wbs VALUES (1,1,60)", "INSERT INTO eppm.project_wbs VALUES (2,1,60)"]),
        "calendar": ("employee_calendar_exception", [
            "INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) VALUES (1,'2026-01-01','2026-01-05',10)",
            "INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) VALUES (1,'2026-01-05','2026-01-06',50)"]),
        "group": ("resource_pool_group_member", [
            "INSERT INTO eppm.resource_pool_group_member(group_id,child_group_id) VALUES (1,2)",
            "INSERT INTO eppm.resource_pool_group_member(group_id,child_group_id) VALUES (2,1)"]),
    }[kind]

    def save(index):
        def operation(connection):
            attempts[index] += 1
            connection.execute(sql.SQL("SELECT COUNT(*) FROM eppm.{}").format(sql.Identifier(source))).fetchone()
            if attempts[index] == 1:
                barrier.wait(timeout=10)
            connection.execute(statements[index])
        try:
            business.run(operation, write=True)
            return True
        except psycopg.errors.CheckViolation:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(save, range(2))) == [False, True]
    assert sum(attempts) >= 3
    assert execute(business, sql.SQL("SELECT COUNT(*) FROM eppm.{}").format(sql.Identifier(source))) == [(1,)]


def test_protected_trigger_helpers_are_not_publicly_executable(business):
    exposed = execute(business, """SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='eppm' AND has_function_privilege(current_user,p.oid,'EXECUTE')""")
    assert {row[0] for row in exposed} == {
        "bind_actor", "current_actor", "has_global_permission", "permission_projects", "has_business_read",
        "is_access_administrator", "admin_set_status", "admin_grant", "admin_revoke", "admin_register",
        "admin_resolve_scope", "admin_project_choices", "access_security_revision",
        "admin_scope_catalog",
        "oidc_state_store", "oidc_state_consume", "session_lookup", "authenticate_identity",
        "session_activity", "session_logout", "policy_scope_projects",
        "project_contacts", "pool_staffing", "display_cache_revisions", "read_derived_cache", "publish_derived_cache",
        "dashboard_revision", "dashboard_resources",
        "wbs_options", "project_id_preview", "allocate_project_id",
    }
