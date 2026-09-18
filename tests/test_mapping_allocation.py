"""Allocation percentages across live pools and deduplicated team occupants."""

from dataclasses import replace

import pytest

from app.domain.organization.models import Employee, EmployeeFunction, OrgFunction, Team
from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.mapping_allocation import MappingCatalog
from app.domain.resources.models import PoolMapping, ResourcePool


def catalog(rows):
    return MappingCatalog([ResourcePool('Alpha', id=1), ResourcePool('Beta', id=2)], CapacityInputs(0,
        employees=[Employee('Ada', 'One', 'ada@example.test', employee_id=1, function_id=1,
                            occupation_percentage=50)],
        functions=[OrgFunction('Engineer', 1, function_id=1)],
        teams=[Team('Team', team_id=1), Team('Other', team_id=2)],
        team_functions={1: [1, 1], 2: [1]}, mappings=rows))


def test_remaining_counts_team_members_and_deduplicates_within_each_pool():
    source = catalog([PoolMapping(1, 'team', 1, 60), PoolMapping(1, 'team', 2, 40)])
    assert source.allocations().total(('employee', 1)) == 60
    assert source.remaining(2, 'employee', 1) == 100
    assert source.remaining(2, 'team', 1) == 40
    assert source.remaining(2, 'team', 2) == 40
    assert source.remaining(1, 'team', 1) == 100


def test_direct_priority_uses_remaining_capacity_and_prevents_duplicate_team_shares():
    source = catalog([PoolMapping(1, 'team', 1, 100), PoolMapping(1, 'employee', 1, 20)])
    assert source.remaining(2, 'employee', 1) == 80
    assert source.remaining(2, 'team', 2) == 0
    source.validate(source.sources.mappings + [PoolMapping(2, 'employee', 1, 80)])
    with pytest.raises(ValueError, match='cannot exceed 100%'):
        source.validate(source.sources.mappings + [PoolMapping(2, 'employee', 1, 81)])


def test_deleted_pools_resources_and_functions_do_not_consume_allocation():
    source = catalog([PoolMapping(1, 'team', 1, 100)])
    source.pools[0].deleted_flag = True
    assert source.remaining(2, 'team', 1) == source.remaining(2, 'employee', 1) == 100
    source.pools[0].deleted_flag = False
    source.sources.functions[0].deleted_flag = True
    assert source.remaining(2, 'employee', 1) == 100
    source.sources.functions[0].deleted_flag = False
    source.sources.employees[0].deleted_flag = True
    assert ('employee', 1) not in source.allocations().usage


def test_restored_overallocation_counts_unique_resources_and_lists_every_pool():
    rows = [PoolMapping(1, 'team', 1, 80), PoolMapping(2, 'team', 1, 60)]
    source = catalog(rows)
    result = source.allocations()
    assert result.overallocated == {('team', 1), ('employee', 1)}
    assert 'Alpha: 80%' in result.warning(('employee', 1))
    assert 'Beta: 60%' in result.warning(('employee', 1))
    assert set(result.pool_warnings()) == {1, 2}
    source.validate([rows[0], replace(rows[1], allocation_pct=50)])
    with pytest.raises(ValueError):
        source.validate([rows[0], replace(rows[1], allocation_pct=70)])


def test_fractional_remaining_does_not_round_up_or_depend_on_employee_fte():
    source = catalog([PoolMapping(1, 'employee', 1, 66.667)])
    assert source.remaining(2, 'employee', 1) == 33.333
    source.validate(source.sources.mappings + [PoolMapping(2, 'employee', 1, 33.333)])


def test_empty_team_still_has_its_own_allocation_limit():
    source = catalog([PoolMapping(1, 'team', 1, 100)])
    source.sources.team_functions = {}
    assert source.remaining(2, 'team', 1) == 0
    assert source.remaining(2, 'employee', 1) == 100


def test_remaining_team_percentage_accounts_for_partial_employee_function_share():
    source = catalog([PoolMapping(1, 'employee', 1, 60)])
    source.sources.employees[0].function_assignments = [EmployeeFunction(1, 60)]
    assert source.remaining(2, 'team', 2) == 100
    rows = source.sources.mappings + [PoolMapping(2, 'team', 2, 100)]
    source.validate(rows)
    assert source.allocations(rows).total(('employee', 1)) == 84
