"""Native staffing parity, bounded demand snapshots and employee privacy."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
import math
import random
from threading import Event

import psycopg
import pytest

from app.infrastructure.postgresql.staffing_projection import refresh_staffing

from app.application.exceptions import ResourcePoolStorageError
from app.application.services.pool_capacity import PoolCapacityService
from app.domain.access.models import AccessDenied
from app.domain.organization.models import EmployeeCalendarException
from app.domain.resources.capacity import calculate_capacity
from app.domain.resources.inputs import CapacityInputs
from app.infrastructure.postgresql.organization import PostgresOrganizationStore
from app.infrastructure.postgresql.pool_capacity import PostgresCapacityReader, read_capacity_inputs
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolGateway, PostgresResourcePoolStore


DAY = date(2026, 1, 3)


def reader(authorized, user_id=4):
    return PostgresCapacityReader(authorized.database, authorized.key, access=authorized.binding(user_id).access)


def gateway(authorized, user_id=4):
    return PostgresResourcePoolGateway(authorized.database, authorized.key, access=authorized.binding(user_id).access)


@pytest.fixture
def staffing(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.function(function_id,name,hierarchy_level,manager_function_id,fte_percentage)
            VALUES (1,'Manager',1,NULL,100),(2,'Vacant',2,1,200),(3,'Occupied',2,1,100),
                   (4,'Tiny',1,NULL,1),(5,'Unmapped',1,NULL,100)""")
        connection.execute("""INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code,function_id,occupation_percentage)
            VALUES (1,' Ada ','One','ada@example.test','A',1,80),(2,'Ben','Two','ben@example.test','B',3,60),
                   (3,'Cara','Three','cara@example.test','C',3,40),(4,'Dan','Four','dan@example.test','D',NULL,100)""")
        connection.execute("""INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage,reason)
            VALUES (1,'2026-01-02','2026-01-04',0,'Private leave reason'),
                   (2,'2026-01-03','2026-01-05',20,'Another private reason'),
                   (4,'2026-01-02','2026-01-03',50,'Third private reason')""")
        connection.execute("""INSERT INTO eppm.team(team_id,team_name,manager_function_id)
            VALUES (1,'Implicit',1),(2,'Explicit',1),(3,'Manager only',1)""")
        connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (2,2)')
        connection.execute("""INSERT INTO eppm.resource_pool(id,name,capacity_fte)
            VALUES (1,'Staffed',10),(2,'Defined only',2),(3,'Zero override',10),
                   (4,'Tiny',NULL),(5,'Empty',NULL),(6,'Unrelated',1)""")
        connection.execute("""INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id,allocation_pct)
            VALUES (1,'team',1,50),(1,'team',2,75),(1,'function',3,30),(1,'employee',2,10),
                   (1,'employee',4,25),(1,'employee',99,50),(1,'function',99,50),
                   (3,'employee',1,0),(4,'function',4,35),(6,'team',3,100)""")
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (1,1,'Visible','2026-01-01','2026-01-05',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(2,2,'Read only','2026-01-02','2026-01-04',(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current)),(3,3,'Hidden','2026-01-01','2026-01-06',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,start_date,end_date,project_plan_id) VALUES (1,1,NULL,1,NULL,NULL,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(1,1,1,0.75,NULL,'2026-01-04',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(1,2,2,0.5,'2026-01-03',NULL,(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current)),(1,3,3,20,NULL,NULL,(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current)),(2,1,NULL,0.5,NULL,NULL,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(3,1,1,0.25,NULL,NULL,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(6,3,3,30,NULL,NULL,(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
        connection.execute('INSERT INTO eppm.employee_function(employee_id,function_id) '
                           'SELECT employee_id,function_id FROM eppm.employee WHERE function_id IS NOT NULL ON CONFLICT DO NOTHING')
        refresh_staffing(connection)
    return authorized


def reference_inputs(authorized, pool_ids):
    """Use synthetic setup records as an independent pure-domain parity oracle."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        org, pools = PostgresOrganizationStore(connection), PostgresResourcePoolStore(connection)
        functions, teams, employees = org.get_all_functions(), org.get_all_teams(), org.get_all_employees()
        exceptions = [EmployeeCalendarException(row.employee_id, date.fromisoformat(row.start_date),
                      date.fromisoformat(row.end_date), row.occupation_percentage) for row in org.get_employee_calendar_exceptions()]
        members = {}
        for team_id, function_id in connection.execute('SELECT team_id,function_id FROM eppm.team_function'):
            members.setdefault(team_id, []).append(function_id)
        bounds = {identity: (start.isoformat(), end.isoformat()) for identity, start, end in connection.execute(
            'SELECT project_id,min(start_date),max(end_date) FROM eppm.project_task GROUP BY project_id')}
        mappings, assignments = pools.get_all_mappings(), pools.get_assignments(pool_ids=pool_ids)
        totals = {}
        for mapping in mappings:
            if mapping.target_type == 'employee':
                totals[mapping.target_id] = totals.get(mapping.target_id, 0) + mapping.allocation_pct
        return {pool_id: CapacityInputs(pool_id, pools.get_pool_by_id(pool_id), functions, teams, employees, exceptions,
                [mapping for mapping in mappings if mapping.pool_id == pool_id], members,
                [assignment for assignment in assignments if assignment['pool_id'] == pool_id], bounds,
                capacity_exceptions=pools.capacity_exceptions([pool_id]), direct_employee_totals=totals)
                for pool_id in pool_ids}


def test_native_staffing_matches_pure_domain_deduplication_overrides_calendars_and_rounding(staffing):
    pool_ids = [1, 2, 3, 4, 5, 6, 999]
    reference = reference_inputs(staffing, pool_ids)
    native = reader(staffing).read(pool_ids)
    for pool_id in pool_ids:
        assert calculate_capacity(native[pool_id], DAY) == calculate_capacity(reference[pool_id], DAY)
        assert native[pool_id].employees == native[pool_id].exceptions == native[pool_id].functions == []
    assert native[4].staffing.assigned_capacity_fte == 0.003
    zero = calculate_capacity(native[3], DAY)
    assert zero.has_assigned_resources and zero.effective_capacity_fte == 0 and zero.is_overassigned
    assert {person.resource_type for person in native[1].staffing.contributing_resources} == {'employee'}


def test_team_capacity_excludes_managers_reports_and_child_teams_without_explicit_membership(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level,manager_function_id) VALUES (1,'Manager',1,NULL),(2,'Report',2,1),(3,'Explicit',2,NULL),(4,'Child member',2,NULL)")
        connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code,function_id) SELECT function_id,name,'Employee',function_id || '@example.test',function_id::text,function_id FROM eppm.function")
        connection.execute("INSERT INTO eppm.team(team_id,team_name,manager_function_id,parent_team_id) VALUES (1,'Root',1,NULL),(2,'Child',NULL,1)")
        connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (1,3),(2,4)')
        connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES (1,'Team pool')")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES (1,'team',1,100)")
        connection.execute('INSERT INTO eppm.employee_function(employee_id,function_id) '
                           'SELECT employee_id,function_id FROM eppm.employee WHERE function_id IS NOT NULL ON CONFLICT DO NOTHING')
        refresh_staffing(connection)
    native = reader(authorized).read([1])[1]
    expected = calculate_capacity(reference_inputs(authorized, [1])[1], DAY)
    assert calculate_capacity(native, DAY) == expected
    assert [person.employee_id for person in native.staffing.contributing_resources] == [3]
    assert native.staffing.assigned_capacity_fte == 1
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (1,1)')
        refresh_staffing(connection)
    assert {person.employee_id for person in reader(authorized).read([1])[1].staffing.contributing_resources} == {1, 3}


def test_vacant_team_functions_contribute_zero_without_nominal_pool_fallback(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level,fte_percentage) VALUES (1,'Vacant',1,200)")
        connection.execute("INSERT INTO eppm.team(team_id,team_name) VALUES (1,'Explicit team')")
        connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (1,1)')
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (1,'Team pool',7)")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) VALUES (1,'team',1)")
        refresh_staffing(connection)

    def capacity():
        native = calculate_capacity(reader(authorized).read([1])[1], DAY)
        assert native == calculate_capacity(reference_inputs(authorized, [1])[1], DAY)
        assert native.has_assigned_resources
        return native

    assert capacity().effective_capacity_fte == 0
    assert capacity().contributing_resources == []
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code,function_id,occupation_percentage) VALUES (1,'First','Member','one@example.test','1',1,40),(2,'Second','Member','two@example.test','2',1,60)")
        connection.execute('INSERT INTO eppm.employee_function(employee_id,function_id) '
                           'SELECT employee_id,function_id FROM eppm.employee WHERE function_id IS NOT NULL ON CONFLICT DO NOTHING')
        refresh_staffing(connection)
    assert capacity().effective_capacity_fte == 1
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) VALUES (1,'2026-01-03','2026-01-03',0)")
        refresh_staffing(connection)
    assert capacity().daily_effective_capacity['2026-01-03'] == 0.6
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.employee_function')
        refresh_staffing(connection)
    assert capacity().effective_capacity_fte == 0


def test_project_readers_receive_aggregate_capacity_and_only_visible_demand(staffing):
    reference = reference_inputs(staffing, [1, 2, 3, 6])
    native = reader(staffing, 1).read([1, 2, 3, 6])
    for pool_id, values in native.items():
        reference[pool_id].assignments = [row for row in reference[pool_id].assignments if row['project_id'] in (1, 2)]
        expected = replace(calculate_capacity(reference[pool_id], DAY), contributing_resources=[])
        assert calculate_capacity(values, DAY) == expected
        assert not values.staffing.contributing_resources and not values.employees and not values.exceptions
    assert set(native[1].project_bounds) == {1, 2}
    assert reader(staffing, 1).read([6])[6].project_bounds == {}
    assert reader(staffing, 1).read([]) == {}
    assert staffing.query('SELECT employee_id FROM eppm.employee') == []
    assert staffing.query('SELECT exception_id FROM eppm.employee_calendar_exception') == []
    rows = staffing.query('SELECT * FROM eppm.pool_staffing(ARRAY[1,3]::bigint[])')
    payload = repr(rows)
    assert 'Ada' not in payload and 'Private leave reason' not in payload and 'employee_id' not in payload
    assert all(row[-1] == [] for row in rows)
    with pytest.raises(AccessDenied):
        reader(staffing, 3).read([1])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        staffing.query('SELECT * FROM eppm.pool_staffing(ARRAY[1]::bigint[])', user_id=3)
    for source in ('SELECT * FROM eppm.capacity_contributions(ARRAY[1]::bigint[])', 'SELECT eppm.capacity_round3(0.0035)'):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            staffing.query(source, user_id=4)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        staffing.database.run(lambda connection: connection.execute('SELECT * FROM eppm.pool_staffing(ARRAY[1]::bigint[])').fetchall())


def test_sql_capacity_rounding_matches_binary64_rounding_at_midpoints_and_adjacent_values(pg_database):
    rng = random.Random(42)
    values = [0.0, 5e-324, -5e-324, 1e-300, -1e-300, float(2**52), float(-2**52), 1e100, -1e100]
    for index in range(1, 1000):
        midpoint = index / 1000 + 0.0005
        values.extend([midpoint, math.nextafter(midpoint, 0), math.nextafter(midpoint, math.inf), -midpoint])
        nominal, allocation = rng.random(), rng.random()
        values.append(nominal * allocation)
    with psycopg.connect(pg_database.operator_url) as connection:
        actual = [row[0] for row in connection.execute('SELECT eppm.capacity_round3(value) FROM unnest(%s::float8[]) value', (values,))]
    assert actual == [round(value, 3) for value in values]


def test_randomized_allocations_and_membership_changes_keep_native_staffing_parity(staffing):
    rng = random.Random(42)
    for iteration in range(15):
        with psycopg.connect(staffing.setup.operator_url) as connection:
            for employee_id in (1, 2, 3, 4):
                connection.execute('UPDATE eppm.employee SET occupation_percentage=%s WHERE employee_id=%s',
                                   (rng.uniform(0, 100), employee_id))
                connection.execute('UPDATE eppm.employee_calendar_exception SET occupation_percentage=%s WHERE employee_id=%s',
                                   (rng.uniform(0, 100), employee_id))
            for identity, in connection.execute('SELECT id FROM eppm.resource_pool_mapping ORDER BY id').fetchall():
                connection.execute('UPDATE eppm.resource_pool_mapping SET allocation_pct=%s WHERE id=%s',
                                   (rng.uniform(0, 100), identity))
            if iteration % 2:
                connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (3,1) ON CONFLICT DO NOTHING')
            else:
                connection.execute('DELETE FROM eppm.team_function WHERE team_id=3')
            refresh_staffing(connection)
        native, reference = reader(staffing).read([1, 3, 4, 6]), reference_inputs(staffing, [1, 3, 4, 6])
        assert {key: calculate_capacity(values, DAY) for key, values in native.items()} == {
            key: calculate_capacity(values, DAY) for key, values in reference.items()}


def test_calendar_expansion_is_inclusive_and_retains_the_existing_25_year_cap(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("""UPDATE eppm.employee_calendar_exception SET start_date='2000-01-01',end_date='2099-01-01'
            WHERE employee_id=1""")
        refresh_staffing(connection)
    native = reader(staffing, 1).read([3])[3]
    assert len(native.staffing.daily_assigned_capacity) == 365 * 25
    assert native.staffing.daily_assigned_capacity['2000-01-01'] == 0
    expected = calculate_capacity(reference_inputs(staffing, [3])[3], DAY)
    assert calculate_capacity(native, DAY) == replace(expected, contributing_resources=[])


def test_explicit_service_calculation_uses_the_requested_day_without_a_cache(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.resource_pool_assignment WHERE pool_id=2')
        connection.execute('DELETE FROM eppm.project_task WHERE project_id=2')
        connection.execute('INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,project_plan_id) VALUES (2,2,0.75,(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current))')
    class UnusedCache:
        def load(self, *args, **kwargs):
            raise AssertionError('An explicit calculation must not request cached results')
    capacity = PoolCapacityService(reader(staffing, 1), UnusedCache(), lambda: DAY)
    default, = capacity.calculate_many([2])
    future, = capacity.calculate_many([2], date(2026, 2, 5))
    assert default.daily_usage == {DAY.isoformat(): 0.75}
    assert future.daily_usage == {'2026-02-05': 0.75}
    assert not default.contributing_resources


def test_staffing_and_assignments_share_one_snapshot_during_concurrent_changes(staffing):
    ready, changed = Event(), Event()
    def read():
        def operation(store):
            before = store.connection.execute('SELECT capacity_fte FROM eppm.resource_pool WHERE id=1').fetchone()[0]
            ready.set()
            assert changed.wait(timeout=10)
            return before, read_capacity_inputs(store, [1])
        return gateway(staffing).run(operation)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(read)
        assert ready.wait(timeout=10)
        try:
            with psycopg.connect(staffing.setup.operator_url) as connection:
                connection.execute('UPDATE eppm.resource_pool SET capacity_fte=1 WHERE id=1')
                connection.execute('DELETE FROM eppm.resource_pool_mapping WHERE pool_id=1')
                connection.execute('DELETE FROM eppm.resource_pool_assignment WHERE pool_id=1')
                refresh_staffing(connection)
        finally:
            changed.set()
        before, inputs = future.result()
    assert before == inputs[1].pool.capacity_fte == 10
    assert inputs[1].staffing.has_assigned_resources and len(inputs[1].assignments) == 4
    current = reader(staffing).read([1])[1]
    assert current.pool.capacity_fte == 1 and not current.staffing.has_assigned_resources and not current.assignments


def test_current_permission_recheck_removes_staffing_details_after_revocation(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        identity = connection.execute("""INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES (1,'business_admin','{"kind":"all"}',900,'test setup') RETURNING id""").fetchone()[0]
    current = reader(staffing, 1)
    details = [calculate_capacity(current.read([1])[1], DAY)]
    assert current.visible_details(details)[0].contributing_resources
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.app_role_assignment WHERE id=%s', (identity,))
    assert not current.visible_details(details)[0].contributing_resources
    assert details[0].contributing_resources


def test_capacity_outages_use_safe_resource_errors(staffing, caplog):
    staffing.database.close()
    with pytest.raises(ResourcePoolStorageError):
        reader(staffing).read([1])
    assert 'postgresql://' not in caplog.text
