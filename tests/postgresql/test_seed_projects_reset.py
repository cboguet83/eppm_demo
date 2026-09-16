"""Native curated projects and reset invariants before maintenance orchestration."""

from tests.postgresql.plan_fixtures import seed_test_plans
from decimal import Decimal

import psycopg
import pytest

from app.application.services.finance import FinanceService
from app.infrastructure.postgresql.finance import PostgresFinanceGateway
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.reset import flush_projects
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog, install_organization_catalog, install_schema_catalog, install_tag_catalog
from app.infrastructure.postgresql.seed_projects import create_seed_project, seed_sample_projects


def install(connection):
    ensure_reference_catalog(connection)
    install_schema_catalog(connection)
    install_organization_catalog(connection)
    install_tag_catalog(connection)
    seed_sample_projects(connection)
    connection.execute("INSERT INTO eppm.operator_seed_state(catalog) VALUES ('demo')")


def test_curated_native_projects_have_exact_budgets_and_valid_dependency_owners(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*),sum(planned_budget),sum(actual_budget) FROM eppm.project').fetchone() == (5, Decimal('1250000'), Decimal('842000'))
        assert connection.execute('SELECT count(*) FROM eppm.project_task').fetchone() == (15,)
        assert connection.execute('SELECT count(*) FROM eppm.task_dependencies').fetchone() == (14,)
        assert connection.execute('SELECT count(*) FROM eppm.task_dependencies WHERE predecessor_project_id IS NOT NULL').fetchone() == (4,)
        assert connection.execute("SELECT count(*) FROM eppm.project p JOIN eppm.project_task t ON t.project_id=p.id "
                                  "WHERE p.status='Completed' AND t.progress_pct<>100").fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.project_property_value WHERE kind=%s', ('number',)).fetchone()[0] > 0


@pytest.mark.parametrize('fields', [
    {'name': ' '}, {'name': 'Invalid amount', 'planned_budget': 'NaN'},
    {'name': 'Invalid ID', 'project_id': 0}, {'name': 'Invalid ID', 'project_id': True},
    {'name': 'Unknown template', 'project_type_id': 999},
])
def test_invalid_seed_project_input_does_not_insert_a_row(pg_database, fields):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(lambda connection: (ensure_reference_catalog(connection), install_schema_catalog(connection)), write=True)
    with pytest.raises(ValueError):
        operator.run(lambda connection: create_seed_project(connection, **fields), write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.project').fetchone() == (0,)


def test_operator_creation_applies_required_template_defaults_and_advances_explicit_ids(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(lambda connection: (ensure_reference_catalog(connection), install_schema_catalog(connection)), write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        infrastructure = connection.execute("SELECT id FROM eppm.project_type WHERE name='Infrastructure'").fetchone()[0]
    with pytest.raises(ValueError, match='code_line'):
        operator.run(lambda connection: create_seed_project(connection, name='Missing required line', project_type_id=infrastructure), write=True)
    identity = operator.run(lambda connection: create_seed_project(connection, project_id=100, name='Validated',
        planned_budget='9007199254740993.01', project_type_id=infrastructure, dynamic_attributes={'PRM_017': '1'}), write=True)
    assert identity == 100
    assert operator.run(lambda connection: create_seed_project(connection, name='Next'), write=True) == 101
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT planned_budget FROM eppm.project WHERE id=100').fetchone() == (Decimal('9007199254740993.01'),)
        assert 'railway' in connection.execute("SELECT text_value FROM eppm.project_property_value WHERE project_id=100 AND param_id='PRM_011'").fetchone()[0]


def test_project_only_reset_cascades_planning_but_retains_references_and_monotonic_ids(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    counts = operator.run(flush_projects, write=True)
    assert counts == {'projects_deleted': 5, 'tasks_deleted': 15, 'dependencies_deleted': 14}
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.project_task').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.task_dependencies').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.employee').fetchone() == (50,)
        assert connection.execute('SELECT count(*) FROM eppm.project_type').fetchone() == (5,)
    assert operator.run(lambda connection: create_seed_project(connection, name='After reset'), write=True) > 5


def test_full_reset_preserves_accounts_approved_finance_hierarchy_choices_and_old_scope_isolation(authorized):
    operator = OperatorDatabase(authorized.setup.operator_url)
    operator.run(install, write=True)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.wbs(code) VALUES ('A')")
        before_users = connection.execute('SELECT id,status FROM eppm.app_user ORDER BY id').fetchall()
        connection.execute("UPDATE eppm.hierarchy_type_translation SET label='Configured' WHERE locale='fr'")
    finance = FinanceService(PostgresFinanceGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    snapshot = finance.save([{'code': 'A', 'amounts': {'2026': '1.01'}}], base_id=None, name='Preserved', status='Approved', year=2026)
    result = operator.run(lambda connection: flush_projects(connection, flush_all=True), write=True)
    assert result['projects_deleted'] == 8
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT id,status FROM eppm.app_user ORDER BY id').fetchall() == before_users
        assert connection.execute('SELECT count(*) FROM eppm.function').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.schema_parameters').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool').fetchone() == (0,)
        assert connection.execute('SELECT name,is_general FROM eppm.project_type').fetchall() == [('General', True)]
        assert connection.execute("SELECT DISTINCT label FROM eppm.hierarchy_type_translation WHERE locale='fr'").fetchall() == [('Configured',)]
        assert connection.execute("SELECT name FROM eppm.project_event_type WHERE system_code='blocking_point'").fetchone() == ('Blocking Point',)
        assert connection.execute("SELECT catalog FROM eppm.operator_seed_state").fetchall() == [('reference',)]
    assert finance.view(snapshot).selected.rows[0].amounts == {2026: Decimal('1.01')}
    assert operator.run(lambda connection: create_seed_project(connection, name='New identity'), write=True) > 8
    assert authorized.query('SELECT id FROM eppm.project') == []


def test_empty_full_reset_initializes_general_and_manual_identity_high_water_survives_reset(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    assert operator.run(lambda connection: flush_projects(connection, flush_all=True), write=True) == {
        'projects_deleted': 0, 'tasks_deleted': 0, 'dependencies_deleted': 0,
    }
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name) VALUES (999,'Manual operator identity')")
        seed_test_plans(connection)
        from app.infrastructure.postgresql.seed_plan import ensure_operator_plan
        ensure_operator_plan(connection, 999)
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (777,999,'Manual task','2026-01-01','2026-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=999 AND is_current))")
    operator.run(flush_projects, write=True)
    identity = operator.run(lambda connection: create_seed_project(connection, name='New project'), write=True)
    assert identity > 999
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date,project_plan_id) "
                                  "VALUES (%s,'New task','2026-01-01','2026-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=%s AND is_current)) RETURNING id", (identity, identity)).fetchone()[0] > 777
