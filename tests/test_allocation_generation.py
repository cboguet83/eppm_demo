"""Pure allocation rounding, request validation and native capacity periods."""

from dataclasses import replace

import pytest

from app.domain.resources.allocation_generation import (
    AllocationGenerationRequest, allocation_fte, allocation_rates, percentage_count,
)
from app.domain.resources.models import PoolCapacityDetail
from app.infrastructure.postgresql.allocation_seed import capacity_periods


def test_fte_rounding_never_exceeds_target_or_changes_category() -> None:
    assert allocation_fte(1, 124.049) == 1.24
    assert allocation_fte(1, 100) == 1
    assert allocation_fte(1, 100.1) == 1.001
    for capacity, percentage in [(1, 0.01), (0.1, 100.1), (0.0001, 100), (1.0005, 100)]:
        with pytest.raises(ValueError, match="precision"):
            allocation_fte(capacity, percentage)



def request() -> AllocationGenerationRequest:
    return AllocationGenerationRequest(80, 80, 25, 50, 50, 20)



def test_allocation_capacity_periods_merge_equal_capacity_but_do_not_bridge_absence() -> None:
    detail = PoolCapacityDetail(pool_id=1, pool_name="Pool", total_capacity_fte=1,
                               peak_assigned_fte=0, total_assigned_fte_scalar=0,
                               is_overassigned=False, peak_excess_fte=0,
                               effective_capacity_fte=1, daily_assigned_capacity={
        "2026-06-02": 1, "2026-06-03": 0, "2026-06-04": 1,
    })
    assert capacity_periods(detail, "2026-06-01", "2026-06-05") == [
        ("2026-06-01", "2026-06-02", 1), ("2026-06-04", "2026-06-05", 1),
    ]
    for start, end in [("2026-06-05", "2026-06-01"), ("9999-12-31", "9999-12-31")]:
        with pytest.raises(ValueError, match="invalid schedule period"):
            capacity_periods(detail, start, end)



@pytest.mark.parametrize("field,value", [
    ("allocated_pools_pct", -1), ("allocated_pools_pct", 101), ("average_allocation_pct", float("nan")),
    ("max_overallocation_pct", float("inf")), ("max_overallocation_pct", -1),
    ("overallocated_pools_pct", 99), ("underallocated_pools_pct", 101),
    ("unstaffed_pools_pct", True), ("average_allocation_pct", 1001), ("random_seed", 1.5),
])
def test_invalid_generation_inputs_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        allocation_rates(list(range(10)), replace(request(), **{field: value}))



def test_rounding_feasibility_and_empty_allocation_requests() -> None:
    assert percentage_count(3, 50) == 2
    assert allocation_rates([1, 2], replace(request(), allocated_pools_pct=0)) == {}
    assert allocation_rates([], request()) == {}
    all_full = AllocationGenerationRequest(100, 100, 0, 0, 0, 0)
    assert allocation_rates([1, 2, 3], all_full) == {1: 100, 3: 100, 2: 100}
    with pytest.raises(ValueError, match="0.1%"):
        allocation_rates([1, 2, 3], replace(request(), max_overallocation_pct=0))
    mixed = AllocationGenerationRequest(100, 90, 50, 50, 50, 0)
    rates = allocation_rates([1, 2, 3], mixed)
    assert len(rates) == 3 and sum(rates.values()) / 3 == pytest.approx(90)
