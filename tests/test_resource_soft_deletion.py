"""Pure capacity snapshots must ignore deleted resource records."""

from dataclasses import replace
from datetime import date

import pytest

from app.domain.organization.models import Employee, OrgFunction, Team
from app.domain.resources.capacity import calculate_capacity
from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.models import PoolMapping, ResourcePool


@pytest.mark.parametrize('kind', ['employees', 'functions', 'teams', 'pool'])
def test_deleted_record_breaks_team_capacity_chain(kind):
    inputs = CapacityInputs(
        pool_id=1, pool=ResourcePool('Pool', id=1, capacity_fte=0),
        employees=[Employee('Toto', 'One', 'toto@example.test', employee_id=1, function_id=1)],
        functions=[OrgFunction('A', 1, function_id=1)],
        teams=[Team('Team 1', team_id=1)], team_functions={1: [1]},
        mappings=[PoolMapping(pool_id=1, target_type='team', target_id=1)],
    )
    assert calculate_capacity(inputs, date(2026, 1, 1)).assigned_capacity_fte == 1
    if kind == 'pool':
        inputs.pool = replace(inputs.pool, deleted_flag=True)
    else:
        setattr(inputs, kind, [replace(getattr(inputs, kind)[0], deleted_flag=True)])
    result = calculate_capacity(inputs, date(2026, 1, 1))
    assert result.assigned_capacity_fte == result.effective_capacity_fte == 0
    assert result.contributing_resources == []
