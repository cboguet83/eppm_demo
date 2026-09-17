"""Deleted resources retain history but disappear from live capacity and demand."""

from datetime import date

import psycopg
import pytest

from app.application.services.organization import OrganizationService
from app.domain.resources.capacity import calculate_capacity
from app.infrastructure.postgresql.organization import PostgresOrganizationGateway, PostgresOrganizationStore
from app.infrastructure.postgresql.pool_capacity import PostgresCapacityReader
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolGateway
from app.infrastructure.postgresql.migration import discover_migrations, migrate, check_schema
from app.infrastructure.postgresql.plan_rows import read_plans, write_plan
from app.domain.resources.models import PoolAssignment
from app.domain.organization.models import Team, Employee
from tests.postgresql.test_pool_hierarchy import capacity_service


@pytest.fixture
def mapped_team(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function_type(function_type_id,function_type) VALUES (1,'Engineering')")
        connection.execute("INSERT INTO eppm.hierarchy_type(id,code) VALUES (1,'team')")
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level,function_type_id) VALUES (1,'A',1,1)")
        connection.execute("INSERT INTO eppm.team(team_id,team_name,hierarchy_type_id) VALUES (1,'Team 1',1)")
        connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (1,1)')
        connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code,function_id) VALUES (1,'Toto','One','toto@example.test','TOTO',1)")
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (1,'Mapped',0)")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) VALUES (1,'team',1)")
        connection.execute("INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) VALUES (1,'2026-01-01','2026-01-02',50)")
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,project_plan_id,fte_assigned,start_date,end_date) SELECT 1,1,id,2,'2026-01-01','2026-01-03' FROM eppm.project_plan WHERE project_id=1 AND is_current")
    return authorized


@pytest.mark.parametrize('table,key,method', [
    ('employee', 'employee_id', 'delete_employee'),
    ('function', 'function_id', 'delete_function'),
    ('team', 'team_id', 'delete_team'),
    ('resource_pool', 'id', 'delete_pool'),
])
def test_soft_delete_retains_mappings_but_removes_capacity(mapped_team, table, key, method):
    setup = mapped_team
    options = dict(access=setup.binding(4).access)
    reader = PostgresCapacityReader(setup.database, setup.key, **options)
    assert calculate_capacity(reader.read([1])[1], date(2026, 1, 1)).assigned_capacity_fte == 1
    gateway_type = PostgresResourcePoolGateway if table == 'resource_pool' else PostgresOrganizationGateway
    gateway = gateway_type(setup.database, setup.key, **options)
    assert gateway.run(lambda store: getattr(store, method)(1), write=True)
    assert not gateway.run(lambda store: getattr(store, method)(1), write=True)
    detail = calculate_capacity(reader.read([1])[1], date(2026, 1, 1))
    assert detail.assigned_capacity_fte == 0
    assert detail.effective_capacity_fte == 0
    assert detail.contributing_resources == []
    assert detail.daily_assigned_capacity == {}
    with psycopg.connect(setup.setup.operator_url) as connection:
        query = psycopg.sql.SQL('SELECT deleted_flag FROM eppm.{} WHERE {}=1').format(
            psycopg.sql.Identifier(table), psycopg.sql.Identifier(key))
        assert connection.execute(query).fetchone() == (True,)
        for retained in ('team_function', 'resource_pool_mapping', 'resource_pool_assignment', 'employee_calendar_exception'):
            assert connection.execute(psycopg.sql.SQL('SELECT count(*) FROM eppm.{}').format(psycopg.sql.Identifier(retained))).fetchone() == (1,)
    if table == 'resource_pool':
        assert detail.assignments == []
        data = setup.query("SELECT eppm.dashboard_resource_breakdown_scoped(ARRAY[1]::bigint[],'2026-01-01',NULL,NULL,'allocation',NULL,NULL)", user_id=4)[0][0]
        assert data['pools'] == []
        assert all(value == 0 for value in data['allocation'].values())


def test_types_in_use_cannot_be_deleted_even_when_referencing_record_is_deleted(mapped_team):
    setup = mapped_team
    service = OrganizationService(PostgresOrganizationGateway(setup.database, setup.key, access=setup.binding(4).access))
    assert service.delete_function(1)
    assert service.delete_team(1)
    with pytest.raises(ValueError, match='function type is in use'):
        service.delete_function_type(1)
    with pytest.raises(ValueError, match='hierarchy type is in use'):
        service.delete_hierarchy_type(1)


def test_unused_types_are_flagged_and_hidden(authorized):
    setup = authorized
    service = OrganizationService(PostgresOrganizationGateway(setup.database, setup.key, access=setup.binding(4).access))
    with psycopg.connect(setup.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function_type(function_type_id,function_type) VALUES (1,'Unused')")
        connection.execute("INSERT INTO eppm.hierarchy_type(id,code) VALUES (1,'unused')")
    assert service.delete_function_type(1)
    assert service.delete_hierarchy_type(1)
    assert service.get_all_function_types() == []
    assert service.get_all_hierarchy_types() == []
    with psycopg.connect(setup.setup.operator_url) as connection:
        store = PostgresOrganizationStore(connection)
        assert store.get_function_type_by_id(1) is None
        for table in ('function_type', 'hierarchy_type'):
            assert connection.execute(psycopg.sql.SQL('SELECT deleted_flag FROM eppm.{}').format(psycopg.sql.Identifier(table))).fetchone() == (True,)


def test_migration_backfills_false_and_rejects_null_flags(empty_database, tmp_path):
    for migration in discover_migrations()[:52]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.team(team_name) VALUES ('Existing')")
        connection.execute("INSERT INTO eppm.function(name,hierarchy_level) VALUES ('Existing',1)")
        connection.execute("INSERT INTO eppm.employee(firstname,lastname,email,employee_code) VALUES ('Existing','Employee','old@example.test','OLD')")
        connection.execute("INSERT INTO eppm.resource_pool(name) VALUES ('Existing')")
        connection.execute("INSERT INTO eppm.function_type(function_type) VALUES ('Existing')")
        connection.execute("INSERT INTO eppm.hierarchy_type(code) VALUES ('existing')")
    assert migrate(empty_database.operator_url) == ('0053_resource_soft_deletion.sql',)
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        for table in ('team', 'function', 'employee', 'resource_pool', 'function_type', 'hierarchy_type'):
            query = psycopg.sql.SQL('SELECT deleted_flag FROM eppm.{}').format(psycopg.sql.Identifier(table))
            assert connection.execute(query).fetchall() == [(False,)]
            with pytest.raises(psycopg.errors.NotNullViolation), connection.transaction():
                connection.execute(psycopg.sql.SQL('UPDATE eppm.{} SET deleted_flag=NULL').format(psycopg.sql.Identifier(table)))
    assert migrate(empty_database.operator_url) == ()


def test_plan_edits_preserve_hidden_allocations_to_deleted_pools(mapped_team):
    setup = mapped_team
    plan_id = setup.query('SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current', user_id=4)[0][0]
    def read(connection):
        return read_plans(connection, [plan_id])[plan_id]
    assert len(setup.database.run(read, bind=setup.binding(4)).assignments) == 1
    setup.query('UPDATE eppm.resource_pool SET deleted_flag=true WHERE id=1', user_id=4, write=True)
    setup.query("INSERT INTO eppm.resource_pool(id,name) VALUES (2,'New pool')", user_id=4, write=True)
    def edit(connection):
        previous = read(connection)
        assert previous.assignments == []
        current = read(connection)
        current.assignments.append(PoolAssignment(pool_id=2, project_id=1, fte_assigned=1,
                                                  start_date='2026-01-01', end_date='2026-01-03'))
        write_plan(connection, plan_id, 1, current, previous=previous)
    setup.database.run(edit, write=True, bind=setup.binding(4))
    assert [row.pool_id for row in setup.database.run(read, bind=setup.binding(4)).assignments] == [2]
    with psycopg.connect(setup.setup.operator_url) as connection:
        assert connection.execute('SELECT pool_id FROM eppm.resource_pool_assignment ORDER BY pool_id').fetchall() == [(1,), (2,)]


def test_parent_team_deletion_requires_moving_or_deleting_active_children(authorized):
    setup = authorized
    service = OrganizationService(PostgresOrganizationGateway(setup.database, setup.key, access=setup.binding(4).access))
    parent = service.create_team(Team('Parent'))
    child = service.create_team(Team('Child', parent_team_id=parent))
    with pytest.raises(ValueError, match='children'):
        service.delete_team(parent)
    assert service.delete_team(child)
    assert service.delete_team(parent)
    with psycopg.connect(setup.setup.operator_url) as connection:
        assert connection.execute('SELECT parent_team_id,deleted_flag FROM eppm.team WHERE team_id=%s', (child,)).fetchone() == (parent, True)


def test_deleted_employee_invalidates_cached_capacity_and_cannot_be_remapped(mapped_team):
    setup = mapped_team
    capacity = capacity_service(setup)
    assert capacity.get_details([1])[0].assigned_capacity_fte == 1
    service = OrganizationService(PostgresOrganizationGateway(setup.database, setup.key, access=setup.binding(4).access))
    assert service.delete_employee(1)
    assert capacity.get_details([1])[0].assigned_capacity_fte == 0
    assert not service.update_employee(Employee('Changed', 'Name', 'changed@example.test', 'CHANGED', employee_id=1))
    from app.domain.resources.models import PoolMapping
    pools = PostgresResourcePoolGateway(setup.database, setup.key, access=setup.binding(4).access)
    with pytest.raises(ValueError, match='no longer exists'):
        pools.run(lambda store: store.create_mapping(PoolMapping(1, 'employee', 1)), write=True)
