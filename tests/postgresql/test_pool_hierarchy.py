"""Real migrations, Python business guards, concurrent edits and container totals."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from threading import Barrier
from unittest.mock import patch

import psycopg
import pytest

from app.application.services.pool_capacity import PoolCapacityService
from app.domain.resources.models import PoolAssignment, PoolCapacityException, PoolMapping, ResourcePool
from app.infrastructure.postgresql.capacity_cache import PostgresCapacityCache
from app.infrastructure.postgresql.derived_cache import DerivedCacheState
from app.infrastructure.postgresql.errors import MigrationError
from app.infrastructure.postgresql.migration import discover_migrations, migrate
from app.infrastructure.postgresql.pool_capacity import PostgresCapacityReader
from tests.postgresql.test_resource_pools import service


def legacy_database(empty_database, tmp_path):
    for migration in discover_migrations()[:39]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    return empty_database.operator_url


def capacity_service(authorized, user_id=4):
    access = authorized.binding(user_id).access
    today = lambda: date(2026, 1, 1)
    return PoolCapacityService(PostgresCapacityReader(authorized.database, authorized.key, access=access),
        PostgresCapacityCache(authorized.database, authorized.key, DerivedCacheState(), today, access=access), today)


def test_migration_preserves_leaf_ids_assignments_and_converts_groups(empty_database, tmp_path):
    url = legacy_database(empty_database, tmp_path)
    with psycopg.connect(url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (1,'Leaf',3)")
        connection.execute("SELECT setval(pg_get_serial_sequence('eppm.resource_pool','id'),1)")
        connection.execute("INSERT INTO eppm.resource_pool_group(id,name) VALUES (1,'Root'),(2,'Branch')")
        connection.execute("INSERT INTO eppm.resource_pool_group_member(group_id,child_group_id) VALUES (1,2)")
        connection.execute("INSERT INTO eppm.resource_pool_group_member(group_id,pool_id) VALUES (2,1)")
        connection.execute("INSERT INTO eppm.project_type(id,name) VALUES (1,'General')")
        connection.execute("INSERT INTO eppm.project(id,name) VALUES (1,'Project')")
        connection.execute('INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned) VALUES (1,1,2)')
    assert migrate(url) == tuple(item.name for item in discover_migrations()[39:])
    assert migrate(url) == ()
    with psycopg.connect(url) as connection:
        rows = connection.execute("SELECT p.name,parent.name,p.capacity_fte FROM eppm.resource_pool p "
                                  "LEFT JOIN eppm.resource_pool parent ON parent.id=p.parent_pool_id ORDER BY p.name").fetchall()
        assert rows == [('Branch', 'Root', None), ('Leaf', 'Branch', 3), ('Root', None, None)]
        assert connection.execute("SELECT a.pool_id,a.fte_assigned FROM eppm.resource_pool_assignment a "
                                  "JOIN eppm.project_plan p ON p.id=a.project_plan_id WHERE p.is_current").fetchall() == [(1, 2)]
        assert connection.execute("SELECT to_regclass('eppm.resource_pool_group')").fetchone()[0] is None


@pytest.mark.parametrize('conflict', ['pool', 'group', 'name', 'cycle'])
def test_migration_conflicts_report_identities_and_roll_back_all_changes(empty_database, tmp_path, conflict):
    url = legacy_database(empty_database, tmp_path)
    with psycopg.connect(url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES (1,'Leaf')")
        connection.execute("INSERT INTO eppm.resource_pool_group(id,name) VALUES (1,'Root'),(2,'Branch'),(3,'Other')")
        if conflict == 'pool':
            connection.execute("INSERT INTO eppm.resource_pool_group_member(group_id,pool_id) VALUES (1,1),(2,1)")
        elif conflict == 'group':
            connection.execute("INSERT INTO eppm.resource_pool_group_member(group_id,child_group_id) VALUES (1,3),(2,3)")
        elif conflict == 'name':
            connection.execute("UPDATE eppm.resource_pool_group SET name='Leaf' WHERE id=1")
        else:
            # Simulate imported legacy corruption, then restore the old guard.
            connection.execute('ALTER TABLE eppm.resource_pool_group_member DISABLE TRIGGER pool_group_no_cycle')
            connection.execute('INSERT INTO eppm.resource_pool_group_member(group_id,child_group_id) VALUES (1,2),(2,1)')
            connection.execute('ALTER TABLE eppm.resource_pool_group_member ENABLE TRIGGER pool_group_no_cycle')
    with pytest.raises(MigrationError, match='migration blocked'):
        migrate(url)
    with psycopg.connect(url) as connection:
        assert connection.execute('SELECT max(version) FROM eppm.schema_migration').fetchone()[0] == 39
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_group').fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='eppm' "
                                  "AND table_name='resource_pool' AND column_name='parent_pool_id'").fetchone()[0] == 0


def test_only_leaves_are_assignable_and_conversion_clears_parent_capacity(authorized):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Parent', capacity_fte=100))
    leaf = pools.create_pool(ResourcePool('Leaf', capacity_fte=3, parent_pool_id=parent))
    assert pools.get_pool_by_id(parent).capacity_fte == 0
    assert [row.id for row in pools.pool_choices()] == [leaf]
    assert pools.descendant_pool_ids(parent) == [leaf]
    with pytest.raises(ValueError, match='without children'):
        pools.create_assignment(PoolAssignment(parent, 1, 1))
    assignment = pools.create_assignment(PoolAssignment(leaf, 1, 1))
    with pytest.raises(ValueError, match='without children'):
        pools.update_assignment(PoolAssignment(parent, 1, 1, id=assignment))
    with pytest.raises(ValueError, match='cannot be edited'):
        pools.update_pool(replace(pools.get_pool_by_id(parent), capacity_fte=5))
    with pytest.raises(ValueError, match='without children'):
        pools.create_mapping(PoolMapping(parent, 'team', 1))
    with pytest.raises(ValueError, match='without children'):
        pools.save_capacity_exception(PoolCapacityException(parent, '2026-01-01', '2026-01-02', 1))
    with pytest.raises(ValueError, match='children before deleting'):
        pools.delete_pool(parent)
    pools.update_pool(replace(pools.get_pool_by_id(leaf), parent_pool_id=None))
    assert set(row.id for row in pools.pool_choices()) == {leaf, parent}
    assert pools.create_assignment(PoolAssignment(parent, 1, 1))


def test_assigned_parent_blocks_child_creation_and_reparenting_atomically(authorized):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Assigned', capacity_fte=10))
    other = pools.create_pool(ResourcePool('Other'))
    pools.create_assignment(PoolAssignment(parent, 3, 0))
    warning = pools.parent_pool_warning(parent)
    assert 'project or task assignments' in warning
    assert 'Remove or reassign' in warning
    with pytest.raises(ValueError, match='Cannot add a child'):
        pools.create_pool(ResourcePool('Blocked', parent_pool_id=parent))
    original = pools.get_pool_by_id(other)
    with pytest.raises(ValueError, match='Cannot add a child'):
        pools.update_pool(replace(original, name='Lost', parent_pool_id=parent))
    assert pools.get_pool_by_id(other) == original
    assert pools.get_pool_by_id(parent).capacity_fte == 10
    assert len(pools.get_all_pools()) == 2


def test_parent_guard_sees_hidden_assignments_without_exposing_project_data(authorized):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Parent'))
    pools.create_assignment(PoolAssignment(parent, 3, 1))
    # Scoped readers cannot use the shared-only existence projection.
    assert service(authorized, 1).get_assignments(pool_id=parent) == []
    def query(connection):
        return connection.execute('SELECT pool_id FROM eppm.assigned_pool_ids').fetchall()
    assert authorized.database.run(query, bind=authorized.binding(1)) == []
    assert authorized.database.run(query, bind=authorized.binding(4)) == [(parent,)]
    assert 'project or task assignments' in pools.parent_pool_warning(parent)


def test_cycles_and_simultaneous_assignment_conversion_are_rejected(authorized):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Parent'))
    child = pools.create_pool(ResourcePool('Child', parent_pool_id=parent))
    with pytest.raises(ValueError, match='circular'):
        pools.update_pool(replace(pools.get_pool_by_id(parent), parent_pool_id=child))
    target = pools.create_pool(ResourcePool('Concurrent'))
    barrier = Barrier(2)
    def save(kind):
        barrier.wait(timeout=10)
        try:
            if kind == 'assignment':
                pools.create_assignment(PoolAssignment(target, 1, 1))
            else:
                pools.create_pool(ResourcePool('Concurrent child', parent_pool_id=target))
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(2) as executor:
        assert sum(executor.map(save, ['assignment', 'child'])) == 1


def test_parent_totals_refresh_after_leaf_edits_and_reparenting(authorized):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Parent'))
    branch = pools.create_pool(ResourcePool('Branch', parent_pool_id=parent))
    first = pools.create_pool(ResourcePool('First', capacity_fte=3, parent_pool_id=branch))
    second = pools.create_pool(ResourcePool('Second', capacity_fte=5, parent_pool_id=parent))
    pools.create_assignment(PoolAssignment(first, 1, 2, start_date='2026-01-01', end_date='2026-01-01'))
    pools.create_assignment(PoolAssignment(second, 1, 4, start_date='2026-01-02', end_date='2026-01-02'))
    capacity = capacity_service(authorized)
    detail = capacity.get_details([parent])[0]
    assert detail.total_capacity_fte == 8 and detail.peak_assigned_fte == 4
    pools.save_capacity_exception(PoolCapacityException(second, '2026-01-02', '2026-01-02', 2))
    assert capacity.get_details([parent])[0].capacity_calendar['2026-01-02'] == 6
    pools.update_pool(replace(pools.get_pool_by_id(first), capacity_fte=7))
    assert capacity.get_summaries([parent])[0].total_capacity_fte == 12
    pools.update_pool(replace(pools.get_pool_by_id(second), parent_pool_id=None))
    assert capacity.get_details([parent])[0].total_capacity_fte == 7
    assert capacity.get_details([parent], project_ids={2})[0].peak_assigned_fte == 0


def test_role_changes_during_cache_calculation_cannot_leave_stale_leaf_capacity(authorized):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Initially empty'))
    capacity = capacity_service(authorized)
    calculate = capacity.calculate_many
    children = []
    def conversion_during_calculation(pool_ids, day):
        if not children:
            children.append(pools.create_pool(ResourcePool('Late child', capacity_fte=5, parent_pool_id=parent)))
        return calculate(pool_ids, day)
    with patch.object(capacity, 'calculate_many', side_effect=conversion_during_calculation):
        assert capacity.get_details([parent])[0].total_capacity_fte == 5
    pools.delete_pool(children[0])
    assert capacity.get_details([parent])[0].total_capacity_fte == 0


def test_reparenting_zeros_new_parent_and_failed_child_save_restores_capacity(authorized):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Parent with capacity', capacity_fte=20))
    child = pools.create_pool(ResourcePool('Existing leaf', capacity_fte=4))
    with pytest.raises(ValueError):
        pools.create_pool(ResourcePool('Invalid tags', parent_pool_id=parent), tag_ids=[999999])
    assert pools.get_pool_by_id(parent).capacity_fte == 20
    pools.update_pool(replace(pools.get_pool_by_id(child), parent_pool_id=parent))
    assert pools.get_pool_by_id(parent).capacity_fte == 0
    pools.update_pool(replace(pools.get_pool_by_id(parent), name='Renamed parent'))
    assert pools.get_pool_by_id(parent).capacity_fte == 0
    assert capacity_service(authorized).get_details([parent])[0].total_capacity_fte == 4


def test_initial_capacity_exception_is_atomic_with_pool_creation(authorized):
    pools = service(authorized)
    exception = PoolCapacityException(999, '2026-01-01', '2026-01-03', 0.5, 'Initial leave')
    identity = pools.create_pool(ResourcePool('Pool with initial leave', capacity_fte=2), capacity_exceptions=[exception])
    saved = pools.capacity_exceptions(identity)
    assert len(saved) == 1 and saved[0].pool_id == identity and saved[0].reduction_fte == 0.5
    with pytest.raises(ValueError):
        pools.create_pool(ResourcePool('Invalid initial leave'), capacity_exceptions=[replace(exception, reduction_fte=-1)])
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("CREATE FUNCTION eppm.reject_initial_exception() RETURNS trigger LANGUAGE plpgsql AS $$ "
                           "BEGIN RAISE EXCEPTION 'test failure'; END $$")
        connection.execute('CREATE TRIGGER reject_initial_exception BEFORE INSERT ON eppm.resource_pool_capacity_exception '
                           'FOR EACH ROW EXECUTE FUNCTION eppm.reject_initial_exception()')
    from app.application.exceptions import ResourcePoolStorageError
    with pytest.raises(ResourcePoolStorageError):
        pools.create_pool(ResourcePool('Rolled back'), capacity_exceptions=[exception])
    assert [pool.name for pool in pools.get_all_pools()] == ['Pool with initial leave']


def test_today_capacity_uses_mapping_availability_or_pool_exceptions_and_status_scopes_peak(authorized):
    from app.main import create_organization_service
    from app.runtime import RuntimeResources
    from app.domain.organization.models import Employee, EmployeeCalendarException, Team
    from app.domain.resources.hierarchy import PoolHierarchy

    pools = service(authorized)
    org = create_organization_service(RuntimeResources(authorized.database, authorized.key), access=authorized.binding(4).access)
    root = pools.create_pool(ResourcePool('Root'))
    mapped = pools.create_pool(ResourcePool('Mapped', capacity_fte=10, parent_pool_id=root))
    fallback = pools.create_pool(ResourcePool('Fallback', capacity_fte=4, parent_pool_id=root))
    empty = pools.create_pool(ResourcePool('Empty team', capacity_fte=9, parent_pool_id=root))
    employee = org.create_employee(Employee('Ada', 'Lovelace', 'current@example.test', 'CURRENT'))
    org.create_employee_calendar_exception(EmployeeCalendarException(employee, date(2026, 1, 1), date(2026, 1, 1), 0))
    pools.create_mapping(PoolMapping(mapped, 'employee', employee, 100))
    pools.create_mapping(PoolMapping(empty, 'team', org.create_team(Team('Empty team')), 100))
    pools.save_capacity_exception(PoolCapacityException(fallback, '2026-01-01', '2026-01-01', 1))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status=CASE id WHEN 1 THEN 'In Progress' WHEN 2 THEN 'Completed' ELSE 'Draft' END")
    pools.create_assignment(PoolAssignment(mapped, 1, 2, start_date='2026-01-01', end_date='2026-01-01'))
    pools.create_assignment(PoolAssignment(mapped, 2, 7, start_date='2026-01-02', end_date='2026-01-02'))
    pools.create_assignment(PoolAssignment(fallback, 1, 3, start_date='2026-01-01', end_date='2026-01-01'))
    capacity = capacity_service(authorized)
    tree = PoolHierarchy(pools.get_all_pools())
    ids = list(tree.pools)
    mapped_ids = {row.pool_id for row in pools.get_all_mappings()}
    scoped = capacity.get_details(ids, project_ids=pools.project_ids_for_statuses(['In Progress']))
    assert capacity.current_capacities(tree, scoped, mapped_ids) == {root: 3, mapped: 0, fallback: 3, empty: 0}
    assert next(row for row in scoped if row.pool_id == root).peak_assigned_fte == 5
    all_statuses = capacity.get_details(ids, project_ids=pools.project_ids_for_statuses(['In Progress', 'Completed']))
    assert next(row for row in all_statuses if row.pool_id == root).peak_assigned_fte == 7
    assert capacity.current_capacities(tree, all_statuses, mapped_ids) == capacity.current_capacities(tree, scoped, mapped_ids)
    assert all(row.peak_assigned_fte == 0 for row in capacity.get_details(ids, project_ids=pools.project_ids_for_statuses([])))
    capacity._today = lambda: date(2026, 1, 2)
    assert capacity.current_capacities(tree, scoped, mapped_ids) == {root: 5, mapped: 1, fallback: 4, empty: 0}
    with pytest.raises(ValueError, match='Unknown project status'):
        pools.project_ids_for_statuses(['Unknown'])
