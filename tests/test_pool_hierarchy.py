"""Pure pool ancestry and date-aligned container capacity contracts."""

from dataclasses import replace

import pytest

from app.domain.resources.container_capacity import aggregate_capacity
from app.domain.resources.hierarchy import PoolHierarchy
from app.domain.resources.models import PoolCapacityDetail, ResourcePool


def test_deep_pool_tree_is_iterative_and_resolves_only_leaf_pools() -> None:
    pools = [ResourcePool(str(identity), id=identity, parent_pool_id=identity - 1 or None)
             for identity in range(1, 1501)]
    tree = PoolHierarchy(pools)
    assert tree.descendants(1, leaves_only=True) == [1500]
    assert len(tree.descendants(1)) == 1500
    tree.require_leaf(1500)
    with pytest.raises(ValueError, match="contains child"):
        tree.require_leaf(1)


@pytest.mark.parametrize("pools, message", [
    ([ResourcePool('Bad')], 'identities'),
    ([ResourcePool('Bad', id=1, parent_pool_id=True)], 'parent pool'),
    ([ResourcePool('Bad', id=1, parent_pool_id=99)], 'parent pool'),
    ([ResourcePool('Bad', id=1, parent_pool_id=1)], 'circular'),
    ([ResourcePool('A', id=1, parent_pool_id=2), ResourcePool('B', id=2, parent_pool_id=1)], 'circular'),
])
def test_invalid_forests_are_rejected(pools, message) -> None:
    with pytest.raises(ValueError, match=message):
        PoolHierarchy(pools)


def test_missing_pool_traversal_and_assignment_are_rejected() -> None:
    tree = PoolHierarchy([])
    with pytest.raises(ValueError, match="no longer exists"):
        tree.descendants(1)
    with pytest.raises(ValueError, match="no longer exists"):
        tree.require_leaf(1)


def test_container_sums_same_day_capacity_and_usage_instead_of_independent_peaks() -> None:
    first = PoolCapacityDetail(1, 'First', 5, 7, 7, True, 2,
        effective_capacity_fte=5, assigned_capacity_fte=5, has_assigned_resources=True,
        daily_usage={'2026-01-01': 7}, daily_effective_capacity={'2026-01-01': 3},
        daily_assigned_capacity={'2026-01-01': 4})
    second = replace(first, pool_id=2, pool_name='Second', total_capacity_fte=4,
                     effective_capacity_fte=4, assigned_capacity_fte=4,
                     daily_usage={'2026-01-02': 7}, daily_effective_capacity={}, daily_assigned_capacity={})
    result = aggregate_capacity(ResourcePool('Container', id=3, capacity_fte=999), [first, second])
    assert result.total_capacity_fte == result.effective_capacity_fte == 9
    assert result.assigned_capacity_fte == 9
    assert result.defined_capacity_fte is None
    assert result.peak_assigned_fte == 7
    assert result.daily_usage == {'2026-01-01': 7, '2026-01-02': 7}
    assert result.daily_effective_capacity == {'2026-01-01': 7}
    assert result.daily_assigned_capacity == {'2026-01-01': 8}
    assert not result.is_overassigned
    overloaded = aggregate_capacity(ResourcePool('Container', id=3), [replace(first, effective_capacity_fte=1),
        replace(second, effective_capacity_fte=1)])
    assert overloaded.is_overassigned and overloaded.peak_excess_fte == 5
