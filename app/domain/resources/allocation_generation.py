"""Deterministic allocation mixes with explicit percentage and feasibility rules."""

from dataclasses import dataclass
import math
import random


@dataclass(frozen=True)
class AllocationGenerationRequest:
    """Percentages of all pools, or selected pools for the over/under categories.

    Average allocation is the mean capacity usage across selected pools.
    Maximum overallocation is excess above 100%, not the final usage percentage.
    """

    allocated_pools_pct: float = 80.0
    average_allocation_pct: float = 80.0
    overallocated_pools_pct: float = 20.0
    max_overallocation_pct: float = 50.0
    underallocated_pools_pct: float = 50.0
    unstaffed_pools_pct: float = 10.0
    random_seed: int = 42


def validate_generation_request(request: AllocationGenerationRequest) -> None:
    """Reject nonfinite inputs and contradictory category proportions."""
    percentages = (
        request.allocated_pools_pct, request.overallocated_pools_pct,
        request.underallocated_pools_pct, request.unstaffed_pools_pct,
    )
    values = (*percentages, request.average_allocation_pct, request.max_overallocation_pct)
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError("Allocation percentages must be finite numbers.")
    if any(not 0 <= value <= 100 for value in percentages):
        raise ValueError("Pool percentages must be between 0 and 100.")
    if request.overallocated_pools_pct + request.underallocated_pools_pct > 100:
        raise ValueError("Overallocated and underallocated percentages must sum to at most 100%.")
    if not 0 <= request.max_overallocation_pct <= 1000:
        raise ValueError("Maximum overallocation must be between 0 and 1000% excess.")
    if not 0 <= request.average_allocation_pct <= 100 + request.max_overallocation_pct:
        raise ValueError("Average allocation cannot exceed the maximum allowed usage.")
    if type(request.random_seed) is not int:
        raise ValueError("The random seed must be an integer.")


def percentage_count(total: int, percentage: float) -> int:
    """Round a percentage to the nearest realizable pool count, with halves up."""
    return min(total, int(total * percentage / 100 + 0.5))


def allocation_fte(capacity: float, percentage: float) -> float:
    """Respect the timeline's 0.001-FTE precision without exceeding target usage."""
    amount = math.floor(capacity * percentage * 10 + 1e-9) / 1000
    if amount <= 0 or (percentage > 100 and amount <= capacity + 0.0001) or (
        percentage == 100 and not math.isclose(amount, capacity, abs_tol=1e-9)
    ):
        raise ValueError("The requested pool mix cannot be represented at 0.001 FTE precision. Increase capacity or adjust the allocation percentages.")
    return amount


def allocation_rates(pool_ids: list[int], request: AllocationGenerationRequest) -> dict[int, float]:
    """Choose pools and bounded usage rates with the exact requested mean.

    Category counts use largest remainders so they always sum to the selected
    count. A 0.1 percentage-point margin distinguishes over/under from full usage.
    """
    validate_generation_request(request)
    selected_count = percentage_count(len(pool_ids), request.allocated_pools_pct)
    if not selected_count:
        return {}
    proportions = [request.overallocated_pools_pct, request.underallocated_pools_pct,
                   100 - request.overallocated_pools_pct - request.underallocated_pools_pct]
    exact = [selected_count * value / 100 for value in proportions]
    counts = [math.floor(value) for value in exact]
    order = sorted(range(3), key=lambda index: (exact[index] - counts[index], -index), reverse=True)
    for index in order[:selected_count - sum(counts)]:
        counts[index] += 1
    over, under, full = counts
    if over and request.max_overallocation_pct < 0.1:
        raise ValueError("Overallocated pools require at least 0.1% maximum excess.")
    lows = [100.1] * over + [0.1] * under + [100.0] * full
    highs = [100 + request.max_overallocation_pct] * over + [99.9] * under + [100.0] * full
    lower, upper = sum(lows), sum(highs)
    target = request.average_allocation_pct * selected_count
    if target < lower - 1e-8 or target > upper + 1e-8:
        raise ValueError(
            f"This pool mix requires an average between {lower / selected_count:.2f}% "
            f"and {upper / selected_count:.2f}%. Adjust the average or category percentages."
        )
    fraction = (target - lower) / (upper - lower) if upper > lower else 0.0
    rates = [low + fraction * (high - low) for low, high in zip(lows, highs)]
    selected = random.Random(request.random_seed).sample(sorted(pool_ids), selected_count)
    return dict(zip(selected, rates))
