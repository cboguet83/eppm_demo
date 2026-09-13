"""Native allocation previews, daily capacity parity and atomic backed-up writes."""

from dataclasses import replace
from datetime import date

import psycopg
from psycopg import sql
import pytest

from app.application.exceptions import DatabaseMaintenanceError
from app.application.services.maintenance import MaintenanceService
from app.domain.resources.allocation_generation import AllocationGenerationRequest
from app.domain.resources.capacity import calculate_capacity
from app.domain.resources.models import PoolCapacityDetail
from app.infrastructure.postgresql import maintenance
from app.infrastructure.postgresql.allocation_seed import apply_allocation_plan, capacity_periods, prepare_allocation_plan
from app.infrastructure.postgresql.backup import restore_database
from app.infrastructure.postgresql.maintenance_gateway import PostgresMaintenanceGateway
from app.infrastructure.postgresql.operator_capacity import read_operator_capacity_inputs
from app.infrastructure.postgresql.pool_capacity import PostgresCapacityReader
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.infrastructure.postgresql.seed_plan import source_fingerprint
from tests.postgresql.test_pool_capacity import staffing


DAY = date(2026, 6, 1)
MIX = AllocationGenerationRequest(80, 80, 25, 50, 50, 20)
FULL = AllocationGenerationRequest(100, 100, 0, 0, 0, 0)


def install(connection, *, project=True):
    """Install the same small synthetic calendar scenario as the legacy baseline."""
    if project:
        ensure_reference_catalog(connection)
        connection.execute("INSERT INTO eppm.project(id,name) VALUES (1,'Existing project')")
    connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date) "
                       "VALUES (1,1,'Task','2026-06-01','2026-06-05')")
    connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code) "
                       "VALUES (1,'Test','Employee','test@example.invalid','E1')")
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (%s,%s,4)',
                           [(identity, f'Pool {identity}') for identity in range(1, 11)])
        cursor.executemany("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) "
                           "VALUES (%s,'employee',1,100)", [(identity,) for identity in range(1, 11)])
    connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date) "
                       "VALUES (1,1,0.5,'2026-06-01','2026-06-05')")
    connection.execute("INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) "
                       "VALUES (1,'2026-06-03','2026-06-03',0)")


def snapshot(connection):
    """Include sequence state, which an operator fingerprint deliberately excludes."""
    sequences = connection.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='eppm' ORDER BY sequencename").fetchall()
    return source_fingerprint(connection), [
        (name, *connection.execute(sql.SQL('SELECT last_value,is_called FROM eppm.{}').format(sql.Identifier(name))).fetchone())
        for name, in sequences
    ]


@pytest.fixture
def allocations(pg_database, clients, tmp_path):
    gateway = PostgresMaintenanceGateway(pg_database.operator_url, tmp_path, archive_tools=clients)
    gateway.database.run(install, write=True)
    return gateway


def test_preview_keeps_rows_sequences_and_archives_unchanged_then_apply_matches_daily_capacity(allocations, tmp_path, restore_target, clients):
    service = MaintenanceService(allocations)
    before = allocations.database.run(snapshot)

    preview = service.generate_pool_allocations(MIX)

    assert allocations.database.run(snapshot) == before
    assert list(tmp_path.iterdir()) == []
    assert not preview['applied']
    assert [preview[key] for key in ('allocated_pools', 'overallocated_pools', 'underallocated_pools',
                                    'fully_allocated_pools', 'unstaffed_pools')] == [8, 2, 4, 2, 2]
    assert preview['average_allocation_pct'] == pytest.approx(80, abs=0.1)
    result = service.generate_pool_allocations(MIX, apply=True, expected_fingerprint=preview['fingerprint'])
    assert result == preview | {'applied': True}
    inputs = allocations.database.run(lambda c: read_operator_capacity_inputs(c, list(range(1, 11))))
    details = [calculate_capacity(value, DAY) for value in inputs.values()]
    assert sum(detail.is_overassigned for detail in details) == 2
    rows = {row['pool_id']: row for row in result['rows']}
    for detail in details:
        assert detail.has_assigned_resources is not rows[detail.pool_id]['unstaffed']
        for day, demand in detail.daily_usage.items():
            capacity = detail.daily_assigned_capacity.get(day, detail.effective_capacity_fte)
            assert demand <= capacity * 1.5 + 1e-9
        if detail.has_assigned_resources:
            assert detail.daily_usage.get('2026-06-03', 0) == 0
    assert allocations.database.run(lambda c: c.execute('SELECT name FROM eppm.project').fetchall()) == [('Existing project',)]
    archives = list(tmp_path.glob('*.dump'))
    assert len(archives) == 1
    restore_database(archives[0], restore_target.operator_url, tools=clients)
    with psycopg.connect(restore_target.operator_url) as connection:
        assert connection.execute('SELECT count(*),sum(fte_assigned) FROM eppm.resource_pool_assignment').fetchone() == (1, 0.5)
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_mapping').fetchone() == (10,)


def test_applied_operator_report_matches_actor_bound_native_staffing_and_demand(authorized, clients, tmp_path):
    gateway = PostgresMaintenanceGateway(authorized.setup.operator_url, tmp_path, archive_tools=clients)
    gateway.database.run(lambda c: install(c, project=False), write=True)
    result = MaintenanceService(gateway).generate_pool_allocations(MIX, apply=True)
    reader = PostgresCapacityReader(authorized.database, authorized.key, access=authorized.binding(4).access)
    details = reader.read(list(range(1, 11)))
    for row in result['rows']:
        detail = calculate_capacity(details[row['pool_id']], DAY)
        percentages = [100 * demand / detail.daily_assigned_capacity.get(day, detail.effective_capacity_fte)
                       for day, demand in detail.daily_usage.items() if demand > 0]
        assert row['capacity_fte'] == detail.effective_capacity_fte
        assert row['allocation_pct'] == pytest.approx(sum(percentages) / len(percentages) if percentages else 0)
        assert row['maximum_allocation_pct'] == pytest.approx(max(percentages, default=0))
    restricted = PostgresCapacityReader(authorized.database, authorized.key, access=authorized.binding(1).access)
    assert all(not value.employees and not value.exceptions and not value.staffing.contributing_resources
               for value in restricted.read([1, 2]).values())


def test_operator_inputs_preserve_team_function_and_direct_mapping_precedence(staffing, tmp_path):
    gateway = PostgresMaintenanceGateway(staffing.setup.operator_url, tmp_path)
    identities = [1, 2, 3, 4, 5, 6]
    operator_inputs = gateway.database.run(lambda c: read_operator_capacity_inputs(c, identities))
    native = PostgresCapacityReader(staffing.database, staffing.key, access=staffing.binding(4).access).read(identities)
    for identity in identities:
        assert calculate_capacity(operator_inputs[identity], DAY) == calculate_capacity(native[identity], DAY)


@pytest.mark.parametrize('missing,problem', [('projects', 'Create projects'), ('staff', 'positive occupation'),
                                          ('available_days', 'no available capacity')])
def test_unfulfillable_mix_leaves_sources_and_sequences_unchanged_without_an_archive(allocations, tmp_path, missing, problem):
    def change(connection):
        if missing == 'projects':
            connection.execute('DELETE FROM eppm.resource_pool_assignment')
            connection.execute('DELETE FROM eppm.project_task')
            connection.execute('DELETE FROM eppm.project')
        elif missing == 'staff':
            connection.execute('UPDATE eppm.employee SET occupation_percentage=0')
        else:
            connection.execute("UPDATE eppm.employee_calendar_exception SET start_date='2026-06-01',end_date='2026-06-05'")
    allocations.database.run(change, write=True)
    before = allocations.database.run(snapshot)
    with pytest.raises(ValueError, match=problem):
        MaintenanceService(allocations).generate_pool_allocations(FULL, apply=True)
    assert allocations.database.run(snapshot) == before
    assert list(tmp_path.iterdir()) == []


def test_zero_percent_mappings_are_reused_with_original_ids(allocations):
    allocations.database.run(lambda c: c.execute('UPDATE eppm.resource_pool_mapping SET allocation_pct=0'), write=True)
    def mappings(connection):
        return connection.execute('SELECT id,pool_id,target_type,target_id FROM eppm.resource_pool_mapping ORDER BY id').fetchall()
    before = allocations.database.run(mappings)
    result = MaintenanceService(allocations).generate_pool_allocations(FULL, apply=True)
    assert result['mappings_created'] == 0
    assert allocations.database.run(mappings) == before
    assert allocations.database.run(lambda c: c.execute('SELECT DISTINCT allocation_pct FROM eppm.resource_pool_mapping').fetchall()) == [(100,)]


def test_empty_pools_get_staff_and_unstaffed_pools_receive_fallback_capacity(allocations):
    def change(connection):
        connection.execute('DELETE FROM eppm.resource_pool_mapping')
        connection.execute('UPDATE eppm.resource_pool SET capacity_fte=NULL')
    allocations.database.run(change, write=True)
    result = MaintenanceService(allocations).generate_pool_allocations(MIX, apply=True)
    assert result['mappings_created'] == 8
    assert result['capacity_limits_initialized'] == 2
    assert all(row['capacity_fte'] > 0 for row in result['rows'])


def test_zero_allocation_request_clears_demand_but_retains_staffing(allocations):
    result = MaintenanceService(allocations).generate_pool_allocations(replace(FULL, allocated_pools_pct=0), apply=True)
    assert result['assignments_removed'] == 1 and result['assignments_created'] == 0
    assert result['average_allocation_pct'] == 0
    assert allocations.database.run(lambda c: c.execute('SELECT count(*) FROM eppm.resource_pool_mapping').fetchone()) == (10,)


def test_no_pool_preview_is_empty_and_does_not_create_an_archive(pg_database, tmp_path):
    gateway = PostgresMaintenanceGateway(pg_database.operator_url, tmp_path)
    result = MaintenanceService(gateway).generate_pool_allocations(MIX)
    assert result['rows'] == [] and result['total_pools'] == 0
    assert list(tmp_path.iterdir()) == []


def test_reviewed_source_change_rejects_apply_before_backup_and_preserves_new_edit(allocations, tmp_path):
    service = MaintenanceService(allocations)
    preview = service.generate_pool_allocations(MIX)
    plan = allocations.database.run(lambda c: prepare_allocation_plan(c, MIX, today=DAY))
    allocations.database.run(lambda c: c.execute("UPDATE eppm.project SET name='Concurrent edit'"), write=True)
    before = allocations.database.run(snapshot)
    with pytest.raises(ValueError, match='database changed'):
        service.generate_pool_allocations(MIX, apply=True, expected_fingerprint=preview['fingerprint'])
    with pytest.raises(ValueError, match='database changed'):
        allocations.database.run(lambda c: apply_allocation_plan(c, plan), write=True)
    assert allocations.database.run(snapshot) == before
    assert list(tmp_path.iterdir()) == []


def test_native_foreign_key_failure_rolls_back_deletion_staffing_and_inserted_demand(allocations):
    before = allocations.database.run(source_fingerprint)
    plan = allocations.database.run(lambda c: prepare_allocation_plan(c, MIX, today=DAY))
    bad = replace(plan.assignments[-1], values=(99999, *plan.assignments[-1].values[1:]))
    plan = replace(plan, assignments=(*plan.assignments[:-1], bad))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        allocations.database.run(lambda c: apply_allocation_plan(c, plan), write=True)
    assert allocations.database.run(source_fingerprint) == before
    assert allocations.database.run(lambda c: c.execute('SELECT count(*),sum(fte_assigned) FROM eppm.resource_pool_assignment').fetchone()) == (1, 0.5)
    assert allocations.database.run(lambda c: c.execute('SELECT count(*) FROM eppm.resource_pool_mapping').fetchone()) == (10,)


def test_serialization_retry_replays_same_plan_and_keeps_only_one_real_archive(allocations, tmp_path, monkeypatch):
    original = maintenance.apply_allocation_plan
    attempts = []
    def retry(connection, plan):
        attempts.append(plan)
        report = original(connection, plan)
        if len(attempts) == 1:
            connection.execute("DO $$ BEGIN RAISE EXCEPTION 'retry' USING ERRCODE='40001'; END $$")
        return report
    monkeypatch.setattr(maintenance, 'apply_allocation_plan', retry)
    result = MaintenanceService(allocations).generate_pool_allocations(MIX, apply=True)
    assert len(attempts) == 2 and attempts[0] is attempts[1]
    assert result == attempts[0].report(applied=True)
    assert len(list(tmp_path.glob('*.dump'))) == 1


def test_read_error_at_maintenance_boundary_does_not_expose_database_diagnostics(allocations, monkeypatch, caplog):
    def fail(connection, pool_ids):
        connection.execute("DO $$ BEGIN RAISE EXCEPTION 'private diagnostic'; END $$")
    monkeypatch.setattr('app.infrastructure.postgresql.allocation_seed.read_operator_capacity_inputs', fail)
    with pytest.raises(DatabaseMaintenanceError) as error:
        MaintenanceService(allocations).generate_pool_allocations(MIX)
    assert 'private diagnostic' not in str(error.value) + caplog.text


def test_periods_merge_equal_adjacent_capacity_without_bridging_absence():
    detail = PoolCapacityDetail(pool_id=1, pool_name='Pool', total_capacity_fte=1,
        peak_assigned_fte=0, total_assigned_fte_scalar=0, is_overassigned=False, peak_excess_fte=0,
        effective_capacity_fte=1, daily_assigned_capacity={'2026-06-02': 1, '2026-06-03': 0, '2026-06-04': 1})
    assert capacity_periods(detail, '2026-06-01', '2026-06-05') == [
        ('2026-06-01', '2026-06-02', 1), ('2026-06-04', '2026-06-05', 1)]
    for start, end in [('2026-06-05', '2026-06-01'), ('9999-12-31', '9999-12-31')]:
        with pytest.raises(ValueError, match='invalid schedule period'):
            capacity_periods(detail, start, end)


def test_native_allocation_cli_preview_and_reviewed_apply(allocations, pg_database, clients, tmp_path, monkeypatch):
    from scripts.postgresql_admin import main

    monkeypatch.setenv('EPPM_TEST_ALLOCATION_URL', pg_database.operator_url)
    prefix = ['postgresql_admin', '--url-variable', 'EPPM_TEST_ALLOCATION_URL', '--backup-directory', str(tmp_path),
              'generate-allocations', '--overallocated-pools', '25', '--unstaffed-pools', '20']
    before = allocations.database.run(snapshot)
    monkeypatch.setattr('sys.argv', prefix)
    main(archive_tools=clients)
    assert allocations.database.run(snapshot) == before
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr('sys.argv', prefix + ['--apply', '--expected-fingerprint', before[0]])
    main(archive_tools=clients)
    assert len(list(tmp_path.glob('*.dump'))) == 1
    monkeypatch.setattr('sys.argv', prefix + ['--apply', '--expected-fingerprint', before[0]])
    with pytest.raises(SystemExit) as error:
        main(archive_tools=clients)
    assert error.value.code == 1
    assert len(list(tmp_path.glob('*.dump'))) == 1
