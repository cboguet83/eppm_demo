"""Effective exceptions follow explicit mappings and preserve historical periods."""

import psycopg

from app.application.services.organization import OrganizationService
from app.application.services.pool_capacity_exceptions import capacity_exception_breakdown
from app.domain.resources.models import PoolCapacityException, PoolMapping
from app.infrastructure.postgresql.organization import PostgresOrganizationGateway
from tests.postgresql.test_resource_soft_deletion import mapped_team
from tests.postgresql.test_pool_hierarchy import capacity_service
from tests.postgresql.test_resource_pools import service


def test_team_employee_exceptions_override_pool_exceptions_and_deduplicate(mapped_team):
    setup = mapped_team
    pools, capacity = service(setup), capacity_service(setup)
    organization = OrganizationService(PostgresOrganizationGateway(setup.database, setup.key, access=setup.binding(4).access))
    pools.save_capacity_exception(PoolCapacityException(1, '2026-01-01', '2026-01-03', 100, 'Ignored pool reduction'))
    # The employee is reachable through both an explicit team/function link and
    # a direct mapping. The direct 50% takes precedence; the exception appears once.
    pools.create_mapping(PoolMapping(1, 'employee', 1, 50))
    details = capacity.get_details([1])
    assert details[0].capacity_calendar['2026-01-01'] == .25
    rows = capacity_exception_breakdown(details, pools.capacity_exceptions_many([1]), organization.get_employee_calendar_exceptions())
    assert len(rows) == 1
    assert (rows[0].source, rows[0].resource_name, rows[0].reduction_fte) == ('Employee', 'Toto One', .25)
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
    result = pools.import_csv(b'name,capacity_fte\nReplacement,2\n')
    assert result.deactivated == 1
    assert [pool.name for pool in pools.get_all_pools()] == ['Replacement']
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        assert connection.execute('SELECT deleted_flag FROM eppm.resource_pool WHERE id=1').fetchone()[0]
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_mapping WHERE pool_id=1').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_assignment WHERE pool_id=1').fetchone()[0] == 1
