"""Direct runtime SQL must preserve scoped data, ownership and mandatory audit."""

from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb
import pytest

from app.infrastructure.postgresql.pool import Database
from app.shared.config.database import DatabaseConfig


@pytest.fixture
def portfolio(authorized):
    with psycopg.connect(authorized.setup.operator_url) as operator:
        operator.execute("""INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date)
            VALUES (1,'Editable task','2026-01-01','2026-01-02'),(2,'Read only task','2026-01-01','2026-01-02'),
                   (3,'Hidden task','2026-01-01','2026-01-02')""")
        operator.execute("UPDATE eppm.project_task SET predecessor_id=3 WHERE id=1")
        operator.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES (1,2),(1,3)")
        operator.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_project_id) VALUES (1,3)")
        operator.execute("INSERT INTO eppm.resource_pool(name) VALUES ('Pool')")
        operator.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES (1,1,1,1),(1,3,3,9)")
        operator.execute("INSERT INTO eppm.wbs(code) VALUES ('WBS')")
        operator.execute("INSERT INTO eppm.project_wbs VALUES (1,1,10),(3,1,70)")
        operator.execute("INSERT INTO eppm.project_link(project_id,url,alias) VALUES (1,'https://example.invalid/visible','Visible'),(3,'https://example.invalid/hidden','Hidden')")
        operator.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES ('REGION','Region','ENUM'),('NOTE','Note','TEXT')")
        operator.execute("INSERT INTO eppm.schema_param_options(param_id,option_value) VALUES ('REGION','North'),('REGION','South')")
        operator.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES (1,'REGION','text','North'),(2,'REGION','text','South'),(3,'REGION','text','North')")
        operator.execute("INSERT INTO eppm.function(name,hierarchy_level) VALUES ('Manager',1)")
        operator.execute("INSERT INTO eppm.employee(firstname,lastname,email,mobile,employee_code,function_id) VALUES ('Public','Manager','private@example.invalid','secret-phone','STAFF',1)")
        operator.execute("UPDATE eppm.project SET function_id=1 WHERE id=1")
    return authorized


def test_scope_filters_before_counts_paging_joins_and_totals(portfolio):
    assert portfolio.query("SELECT count(*),sum(planned_budget) FROM eppm.project") == [(2, Decimal(0))]
    assert portfolio.query("SELECT id FROM eppm.project ORDER BY id DESC LIMIT 1") == [(2,)]
    assert portfolio.query("SELECT p.id,t.task_name FROM eppm.project p JOIN eppm.project_task t ON t.project_id=p.id ORDER BY p.id") == [(1, "Editable task"), (2, "Read only task")]
    assert portfolio.query("SELECT sum(fte_assigned) FROM eppm.resource_pool_assignment") == [(1.0,)]
    assert portfolio.query("SELECT sum(percentage) FROM eppm.project_wbs") == [(10,)]
    assert portfolio.query("SELECT alias FROM eppm.project_link") == [("Visible",)]


def test_hidden_dependency_endpoints_are_filtered_and_legacy_predecessor_is_masked(portfolio):
    assert portfolio.query("SELECT predecessor_task_id FROM eppm.task_dependencies") == [(2,)]
    assert portfolio.query("SELECT predecessor_id FROM eppm.visible_project_task WHERE id=1") == [(None,)]
    assert portfolio.query("SELECT predecessor_id FROM eppm.visible_project_task WHERE id=1", user_id=4) == [(3,)]
    for source in ("SELECT predecessor_id FROM eppm.project_task", "SELECT * FROM eppm.project_task",
                   "SELECT id FROM eppm.project_task WHERE predecessor_id=3"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            portfolio.query(source)


def test_employee_contact_and_staffing_rows_remain_private(portfolio):
    assert portfolio.query("SELECT * FROM eppm.employee") == []
    assert portfolio.query("SELECT count(*) FROM eppm.employee_calendar_exception") == [(0,)]
    assert portfolio.query("SELECT function_id,label FROM eppm.project_manager_directory") == [(1, "Public Manager")]
    assert portfolio.query("SELECT email,mobile FROM eppm.employee", user_id=4) == [("private@example.invalid", "secret-phone")]
    assert portfolio.query("SELECT * FROM eppm.project_manager_directory", user_id=3) == []


@pytest.mark.parametrize("source", [
    "UPDATE eppm.project SET name='Changed' WHERE id=2",
    "DELETE FROM eppm.project WHERE id=1",
    "INSERT INTO eppm.project(name) VALUES ('Forbidden')",
    "UPDATE eppm.project_link SET project_id=2 WHERE id=1",
    "UPDATE eppm.project_task SET project_id=2 WHERE id=1",
    "INSERT INTO eppm.project_link(project_id,url,alias) VALUES (2,'https://example.invalid','Forbidden')",
    "INSERT INTO eppm.project_link(id,project_id,url,alias) VALUES (2,1,'https://example.invalid','Steal hidden owner') ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id",
    "UPDATE eppm.project_task SET predecessor_id=2 WHERE id=1",
    "UPDATE eppm.project_task SET predecessor_id=NULL WHERE id=1",
    "INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES (1,2)",
    "INSERT INTO eppm.task_dependencies(task_id,predecessor_project_id) VALUES (1,3)",
    "INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES (1,1,3,1)",
    "UPDATE eppm.project_property_value SET text_value='South' WHERE project_id=1",
    "UPDATE eppm.project_property_value SET param_id='NOTE' WHERE project_id=1",
    "DELETE FROM eppm.project_property_value WHERE project_id=1",
    "UPDATE eppm.project SET project_type_id=2 WHERE id=1",
    "INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES ('BAD','Bad','TEXT')",
    "UPDATE eppm.resource_pool SET name='Forbidden'",
    "INSERT INTO eppm.finance_snapshot(number,name,status,author,created_at) VALUES (1,'Forbidden','Draft','fake',1000)",
])
def test_direct_mutations_recheck_old_new_owners_protected_properties_and_capabilities(portfolio, source):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        portfolio.query(source, write=True)
    assert portfolio.query("SELECT name FROM eppm.project WHERE id=1") == [("Editable",)]
    assert portfolio.query("SELECT text_value FROM eppm.project_property_value WHERE project_id=1") == [("North",)]


def test_unreadable_mutations_cannot_target_hidden_rows(portfolio):
    assert portfolio.query("UPDATE eppm.project SET name='Forbidden' WHERE id=3 RETURNING id", write=True) == []
    assert portfolio.query("DELETE FROM eppm.project_link WHERE id=2 RETURNING id", write=True) == []
    assert portfolio.query("SELECT name FROM eppm.project WHERE id=3", user_id=4) == [("Hidden",)]


def test_ordinary_edit_and_unchanged_protected_upsert_are_allowed_without_audit_noise(portfolio):
    portfolio.query("UPDATE eppm.project SET name='Saved' WHERE id=1", write=True)
    portfolio.query("""INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value)
        VALUES (1,'REGION','text','North') ON CONFLICT(project_id,param_id) DO UPDATE SET text_value=excluded.text_value""", write=True)
    portfolio.query("""INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value)
        VALUES (1,'NOTE','text','Editable text') ON CONFLICT(project_id,param_id) DO UPDATE SET text_value=excluded.text_value""", write=True)
    assert portfolio.query("SELECT name FROM eppm.project WHERE id=1") == [("Saved",)]
    with psycopg.connect(portfolio.setup.operator_url) as operator:
        assert operator.execute("SELECT count(*) FROM eppm.app_security_audit").fetchone() == (0,)


def test_task_tag_upsert_cannot_steal_a_hidden_tasks_tag(portfolio):
    portfolio.query("INSERT INTO eppm.task_tag(task_id,free_tag) VALUES (3,'Hidden tag')", user_id=4, write=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        portfolio.query("INSERT INTO eppm.task_tag(id,task_id,free_tag) VALUES (1,1,'Stolen') ON CONFLICT(id) DO UPDATE SET task_id=excluded.task_id", write=True)
    assert portfolio.query("SELECT task_id,free_tag FROM eppm.task_tag", user_id=4) == [(3, "Hidden tag")]


def test_protected_list_items_cannot_be_moved_or_replaced_by_an_editor(portfolio):
    portfolio.query("UPDATE eppm.project_property_value SET kind='list',text_value=NULL WHERE project_id=1", user_id=4, write=True)
    portfolio.query("INSERT INTO eppm.project_property_value_item VALUES (1,'REGION',0,'North')", user_id=4, write=True)
    for source in (
        "UPDATE eppm.project_property_value_item SET value='South' WHERE project_id=1",
        "DELETE FROM eppm.project_property_value_item WHERE project_id=1",
        "INSERT INTO eppm.project_property_value_item VALUES (1,'REGION',0,'South') ON CONFLICT(project_id,param_id,position) DO UPDATE SET value=excluded.value",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            portfolio.query(source, write=True)
    portfolio.query("INSERT INTO eppm.project_property_value_item VALUES (1,'REGION',0,'North') ON CONFLICT(project_id,param_id,position) DO UPDATE SET value=excluded.value", write=True)
    assert portfolio.query("SELECT value FROM eppm.project_property_value_item") == [("North",)]


def test_property_scopes_change_visibility_from_persisted_values(portfolio):
    with psycopg.connect(portfolio.setup.operator_url) as operator:
        key = operator.execute("SELECT id FROM eppm.app_scope_property WHERE param_id='REGION'").fetchone()[0]
        scope = {"kind": "properties", "conditions": [{"property_id": f"enum:{key}", "operator": "eq", "value_ids": [1]}]}
        operator.execute("INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by) VALUES (3,'project_viewer',%s,1000,'setup')", (Jsonb(scope),))
    assert portfolio.query("SELECT id FROM eppm.project ORDER BY id", user_id=3) == [(1,), (3,)]
    portfolio.query("UPDATE eppm.project_property_value SET text_value='South' WHERE project_id=1", user_id=4, write=True)
    assert portfolio.query("SELECT id FROM eppm.project ORDER BY id", user_id=3) == [(3,)]


def test_task_tag_cascade_authorizes_before_parent_disappears(portfolio):
    portfolio.query("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date) VALUES (1,'Disposable','2026-01-01','2026-01-02')", write=True)
    portfolio.query("INSERT INTO eppm.task_tag(task_id,free_tag) VALUES (4,'Tag')", write=True)
    portfolio.query("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES (1,1,4,1)", write=True)
    portfolio.query("DELETE FROM eppm.project_task WHERE id=4", write=True)
    assert portfolio.query("SELECT count(*) FROM eppm.task_tag") == [(0,)]
    assert portfolio.query("SELECT count(*) FROM eppm.resource_pool_assignment WHERE task_id=4") == [(0,)]


def test_shared_tag_cascade_preserves_authorization_of_every_project(portfolio):
    portfolio.query("INSERT INTO eppm.tag_dictionnary(tag) VALUES ('Shared')", user_id=4, write=True)
    portfolio.query("INSERT INTO eppm.task_tag(tag_id,task_id) VALUES (1,1),(1,3)", user_id=4, write=True)
    portfolio.query("DELETE FROM eppm.tag_dictionnary WHERE id=1", user_id=4, write=True)
    assert portfolio.query("SELECT count(*) FROM eppm.task_tag", user_id=4) == [(0,)]


def test_required_audit_uses_trusted_actor_and_records_only_protected_changes(portfolio):
    portfolio.query("UPDATE eppm.project_property_value SET text_value='South' WHERE project_id=1", user_id=4, write=True)
    with psycopg.connect(portfolio.setup.operator_url) as operator:
        event = operator.execute("SELECT actor,target,action,correlation_id,details_json FROM eppm.app_security_audit").fetchone()
    assert event[:4] == ("4", "1", "project.protected_property_change", "request-4")
    assert event[4] == {"table": "project_property_value", "operation": "UPDATE", "property": "REGION",
                        "fields": ["text_value"], "changes": {"text_value": {"before": "North", "after": "South"}}}
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        portfolio.query("INSERT INTO eppm.app_security_audit(occurred_at,actor,target,action,outcome,correlation_id,details_json) VALUES (1000,'fake','1','fake','success','fake','{}')", user_id=4, write=True)


def test_failed_required_audit_rolls_back_all_business_changes(portfolio):
    with psycopg.connect(portfolio.setup.operator_url) as operator:
        operator.execute("CREATE FUNCTION eppm.fail_test_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Test audit unavailable' USING ERRCODE='23514'; END $$")
        operator.execute("CREATE TRIGGER fail_test_audit BEFORE INSERT ON eppm.app_security_audit FOR EACH ROW EXECUTE FUNCTION eppm.fail_test_audit()")
    def save(connection):
        connection.execute("UPDATE eppm.project SET name='Not committed' WHERE id=1")
        connection.execute("UPDATE eppm.project_property_value SET text_value='South' WHERE project_id=1")
    with pytest.raises(psycopg.errors.CheckViolation, match="Test audit unavailable"):
        portfolio.database.run(save, write=True, bind=portfolio.binding(4))
    assert portfolio.query("SELECT name FROM eppm.project WHERE id=1") == [("Editable",)]
    assert portfolio.query("SELECT text_value FROM eppm.project_property_value WHERE project_id=1") == [("North",)]


def test_finance_is_readable_by_valid_active_accounts_without_portfolio_grants(portfolio):
    portfolio.query("INSERT INTO eppm.finance_snapshot(number,name,status,author,created_at) VALUES (1,'Plan','Draft','4',1000)", user_id=4, write=True)
    assert portfolio.query("SELECT name FROM eppm.finance_snapshot", user_id=3) == [("Plan",)]
    assert portfolio.query("SELECT code FROM eppm.wbs", user_id=3) == [("WBS",)]
    assert portfolio.query("SELECT * FROM eppm.resource_pool", user_id=3) == []


def test_finance_permission_does_not_expose_project_identifiers(portfolio):
    with psycopg.connect(portfolio.setup.operator_url) as operator:
        operator.execute("INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by) VALUES (3,'finance_editor','{\"kind\":\"all\"}',1000,'setup')")
    assert portfolio.query("SELECT eppm.has_global_permission('finance.edit')", user_id=3) == [(True,)]
    for permission in ('project.read', 'project.edit', 'finance.edit', 'business.manage', 'access.manage'):
        assert portfolio.query("SELECT eppm.permission_projects(%s)", (permission,), user_id=3) == [([],)]
    assert portfolio.query("SELECT id FROM eppm.project", user_id=3) == []
    portfolio.query("INSERT INTO eppm.finance_snapshot(number,name,status,author,created_at) VALUES (1,'Allowed','Draft','forged author',0)", user_id=3, write=True)
    portfolio.query("UPDATE eppm.finance_snapshot SET sealed=true,author='forged again',created_at=1 WHERE id=1", user_id=3, write=True)
    assert portfolio.query("SELECT author,created_at FROM eppm.finance_snapshot", user_id=3) == [("3", 1000)]
    portfolio.query("INSERT INTO eppm.finance_cancellation VALUES (1,'Draft','forged author',0)", user_id=3, write=True)
    assert portfolio.query("SELECT author,occurred_at FROM eppm.finance_cancellation", user_id=3) == [("3", 1000)]


def test_ordinary_sql_cannot_disable_or_bypass_row_security(portfolio):
    def bypass(connection):
        connection.execute("SET LOCAL row_security=off")
        connection.execute("SELECT count(*) FROM eppm.project")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        portfolio.database.run(bypass, bind=portfolio.binding())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        portfolio.query("ALTER TABLE eppm.project DISABLE ROW LEVEL SECURITY", write=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        portfolio.query("ALTER TABLE eppm.project DISABLE TRIGGER ALL", write=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        portfolio.query("SELECT eppm.task_owner(3)")


def test_every_business_table_has_rls_and_explicit_write_authorization(pg_database):
    with psycopg.connect(pg_database.operator_url) as operator:
        tables = operator.execute("""SELECT c.relname,c.relrowsecurity,EXISTS (SELECT 1 FROM pg_trigger t
            WHERE t.tgrelid=c.oid AND t.tgname LIKE 'authorize_business%'),
            EXISTS(SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid AND p.polcmd IN ('a','*') AND p.polwithcheck IS NOT NULL)
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='eppm' AND c.relkind='r' AND has_table_privilege('eppm_runtime',c.oid,'INSERT')""").fetchall()
    policy_authorized = {'project_plan', 'project_plan_event', 'plan_task_actual',
                         'task_dependencies', 'task_tag', 'project_dependency'}
    assert policy_authorized <= {name for name, _, _, _ in tables}
    assert all(rls and (guarded or name in policy_authorized and policy)
               for name, rls, guarded, policy in tables)


def test_pooled_reuse_discards_temporary_copies_of_another_actors_data(portfolio):
    resource = Database(DatabaseConfig(portfolio.setup.runtime_url, pool_min=1, pool_max=1))
    resource.open()
    try:
        def retain(connection):
            connection.execute("CREATE TEMP TABLE retained_private AS SELECT email FROM eppm.employee")
            assert connection.execute("SELECT count(*) FROM retained_private").fetchone() == (1,)
            return connection.execute("SELECT pg_backend_pid()").fetchone()[0]
        first_backend = resource.run(retain, write=True, bind=portfolio.binding(4))
        second = resource.run(lambda connection: connection.execute(
            "SELECT pg_backend_pid(),to_regclass('pg_temp.retained_private')").fetchone(), bind=portfolio.binding())
        assert second == (first_backend, None)
    finally:
        resource.close()
