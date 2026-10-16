"""Effective exceptions follow explicit mappings and preserve historical periods."""

import psycopg
import pytest

from app.application.services.organization import OrganizationService
from app.application.services.pool_capacity_exceptions import capacity_exception_breakdown
from app.domain.resources.models import PoolCapacityException, PoolMapping
from app.infrastructure.postgresql.organization import PostgresOrganizationGateway
from app.infrastructure.postgresql.staffing_projection import refresh_staffing
from tests.postgresql.test_resource_soft_deletion import mapped_team
from tests.postgresql.test_pool_hierarchy import capacity_service
from tests.postgresql.test_resource_pools import service
from tests.postgresql.test_dashboard import service as dashboard_service


def test_team_employee_exceptions_override_pool_exceptions_and_deduplicate(mapped_team):
    setup = mapped_team
    pools, capacity = service(setup), capacity_service(setup)
    organization = OrganizationService(PostgresOrganizationGateway(setup.database, setup.key, access=setup.binding(4).access))
    pools.save_capacity_exception(PoolCapacityException(1, '2026-01-01', '2026-01-03', 100, 'Ignored pool reduction'))
    # The employee is reachable through both an explicit team/function link and
    # a direct mapping. Direct and remaining indirect shares add in the same
    # pool (ADR 0034); the employee exception still appears only once.
    pools.create_mapping(PoolMapping(1, 'employee', 1, 50))
    details = capacity.get_details([1])
    assert details[0].capacity_calendar['2026-01-01'] == .5
    rows = capacity_exception_breakdown(details, pools.capacity_exceptions_many([1]), organization.get_employee_calendar_exceptions())
    assert len(rows) == 1
    assert (rows[0].source, rows[0].resource_name, rows[0].reduction_fte) == ('Employee', 'Toto One', .5)
    assert capacity.future_exception_pool_ids(rows) == {1}
    pools.delete_mapping(next(mapping.id for mapping in pools.get_mappings_by_pool(1) if mapping.target_type == 'employee'))
    rows = capacity_exception_breakdown(capacity.get_details([1]), pools.capacity_exceptions_many([1]), organization.get_employee_calendar_exceptions())
    assert len(rows) == 1 and rows[0].mapping_source == 'Team 1'
    assert rows[0].reduction_fte == .5
    organization.delete_employee(1)
    assert capacity_exception_breakdown(capacity.get_details([1]), pools.capacity_exceptions_many([1]), organization.get_employee_calendar_exceptions()) == []


def test_unmapped_pool_lists_all_periods_but_future_flag_is_inclusive(mapped_team):
    setup = mapped_team
    pools, capacity = service(setup), capacity_service(setup)
    pools.delete_mapping(pools.get_mappings_by_pool(1)[0].id)
    periods = [('2025-01-01', '2025-12-31'), ('2025-12-01', '2026-01-01'), ('2027-01-01', '2027-02-01')]
    for first, last in periods:
        pools.save_capacity_exception(PoolCapacityException(1, first, last, .25))
    rows = capacity_exception_breakdown(capacity.get_details([1]), pools.capacity_exceptions_many([1]), [])
    assert len(rows) == 3 and all(row.source == 'Pool' for row in rows)
    assert capacity.future_exception_pool_ids(rows[:1]) == set()
    assert capacity.future_exception_pool_ids(rows[1:2]) == {1}
    assert capacity.future_exception_pool_ids(rows[2:]) == {1}


def test_import_soft_deletes_omitted_active_pools_and_keeps_history(mapped_team):
    pools = service(mapped_team)
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute("SELECT setval(pg_get_serial_sequence('eppm.resource_pool','id'),1)")
    result = pools.import_csv(b'name,capacity_fte\nReplacement,2\n', delete_missing=True)
    assert result.deactivated == 1
    assert [pool.name for pool in pools.get_all_pools()] == ['Replacement']
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        assert connection.execute('SELECT deleted_flag FROM eppm.resource_pool WHERE id=1').fetchone()[0]
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_mapping WHERE pool_id=1').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_assignment WHERE pool_id=1').fetchone()[0] == 1


def test_import_keeps_omitted_pools_by_default(mapped_team):
    pools = service(mapped_team)
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute("SELECT setval(pg_get_serial_sequence('eppm.resource_pool','id'),1)")
    result = pools.import_csv(b'name\nAdditional\n')
    assert result.deactivated == 0
    assert {pool.name for pool in pools.get_all_pools()} == {'Mapped', 'Additional'}


def test_exception_grid_changes_are_atomic_and_reject_mapped_pools(mapped_team):
    pools = service(mapped_team)
    with pytest.raises(ValueError, match='Mapped pools'):
        pools.replace_capacity_exceptions(1, [PoolCapacityException(1, '2026-01-01', '2026-01-02', .5)])
    pools.delete_mapping(pools.get_mappings_by_pool(1)[0].id)
    pools.replace_capacity_exceptions(1, [PoolCapacityException(1, '2026-01-01', '2026-01-02', .5),
                                          PoolCapacityException(1, '2026-02-01', '2026-02-02', .25)])
    before = pools.capacity_exceptions(1)
    with pytest.raises(ValueError):
        pools.replace_capacity_exceptions(1, [before[0], PoolCapacityException(1, '2026-03-02', '2026-03-01', .5)])
    assert pools.capacity_exceptions(1) == before
    pools.replace_capacity_exceptions(1, [before[1]])
    assert pools.capacity_exceptions(1) == [before[1]]


@pytest.mark.parametrize('user_id', [1, 4])
def test_dashboard_uses_employee_exceptions_and_ignores_mapped_pool_exceptions(mapped_team, user_id):
    """Charts, warning badges and drill-through share the grid's capacity source."""
    pools = service(mapped_team)
    pools.save_capacity_exception(PoolCapacityException(1, '2026-01-01', '2026-03-31', 100))
    dashboard = dashboard_service(mapped_team, user_id)
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.resource_pool_assignment SET fte_assigned=.75 WHERE pool_id=1')
    detail = capacity_service(mapped_team).get_details([1])[0]
    assert detail.capacity_calendar['2026-01-01'] == .5
    result = dashboard.resource_breakdown([1])
    assert result['overallocation']['2026-Q1'] == .25
    assert result['capacity']['2026-Q1'] == .5
    assert result['individual_pools'][0]['overallocation']['2026-Q1'] == .25
    assert result['peak_days']['overallocation']['2026-Q1'] == '2026-01-01'
    assert result['overallocated_pools'] == [{'pool_id': 1, 'name': 'Mapped'}]
    assert dashboard.resources([1])['overallocation']['2026-Q1'] == .25
    assert dashboard.consuming_projects([1], '2026-Q1') == [1]
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.employee_calendar_exception')
        refresh_staffing(connection)
    result = dashboard.resource_breakdown([1])
    assert result['overallocation']['2026-Q1'] == 0
    assert result['overallocated_pools'] == []
    assert dashboard.consuming_projects([1], '2026-Q1') == []


def test_dashboard_and_grid_switch_sources_when_last_live_mapping_disappears(mapped_team):
    """Deleted targets cease selecting staffing; restoring them restores staffing."""
    pools = service(mapped_team)
    pools.save_capacity_exception(PoolCapacityException(1, '2026-01-01', '2026-03-31', .5))
    dashboard = dashboard_service(mapped_team, 4)
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.resource_pool SET capacity_fte=3 WHERE id=1')
        refresh_staffing(connection)
    for deleted, expected_capacity, expected_excess in [(False, .5, 1.5), (True, 2.5, 0), (False, .5, 1.5)]:
        with psycopg.connect(mapped_team.setup.operator_url) as connection:
            connection.execute('UPDATE eppm.team SET deleted_flag=%s WHERE team_id=1', (deleted,))
            refresh_staffing(connection)
        result = dashboard.resource_breakdown([1])
        assert result['capacity']['2026-Q1'] == expected_capacity
        assert result['overallocation']['2026-Q1'] == expected_excess
        detail = capacity_service(mapped_team).get_details([1])[0]
        assert detail.capacity_calendar['2026-01-01'] == (.5 if not deleted else 2.5)


def test_deleted_direct_employee_and_removed_mapping_restore_pool_exceptions(mapped_team):
    pools = service(mapped_team)
    pools.delete_mapping(pools.get_mappings_by_pool(1)[0].id)
    mapping = pools.create_mapping(PoolMapping(1, 'employee', 1, 0))
    pools.save_capacity_exception(PoolCapacityException(1, '2026-01-01', '2026-03-31', .5))
    dashboard = dashboard_service(mapped_team, 4)
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.resource_pool SET capacity_fte=3 WHERE id=1')
        refresh_staffing(connection)
    # A live mapping with zero allocation must not fall back to nominal capacity.
    assert dashboard.resources([1])['capacity']['2026-Q1'] == 0
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.employee SET deleted_flag=true WHERE employee_id=1')
        refresh_staffing(connection)
    assert dashboard.resources([1])['capacity']['2026-Q1'] == 2.5
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.employee SET deleted_flag=false WHERE employee_id=1')
        refresh_staffing(connection)
    assert dashboard.resources([1])['capacity']['2026-Q1'] == 0
    pools.delete_mapping(mapping)
    assert dashboard.resources([1])['capacity']['2026-Q1'] == 2.5
