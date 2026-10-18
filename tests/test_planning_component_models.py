"""Compare extracted browser period summaries with independent domain results."""

from datetime import date, timedelta
import json
from pathlib import Path
import subprocess

import pytest

from app.domain.resources.capacity_rules import (
    calculate_daily_overassignments,
    get_effective_capacity_for_date,
)


@pytest.mark.parametrize(
    ("capacity", "usage", "overrides"),
    [
        (10.0, {"2026-01-01": 6, "2026-01-02": 4}, {"2026-01-02": 2}),
        (5.0, {"2026-01-01": 1}, {"2026-01-02": 0}),
        (10.0, {}, {"2026-01-01": 1, "2026-01-02": 2, "2026-01-03": 0}),
        (0.0, {}, {}),
        (3.0, {"2026-01-01": 6, "2026-01-03": 4}, {}),
        (3.0, {"2026-01-01": 2}, {}),
        (3.0, {"2026-01-01": 4}, {}),
        (0.5, {"2026-01-01": 0.625}, {"2026-01-01": 0.25}),
    ],
)
def test_browser_resource_summary_matches_python_daily_rules(
    capacity: float,
    usage: dict[str, float],
    overrides: dict[str, float],
) -> None:
    """Check extrema, gaps, daily excess and scope data through the JS interface.

    Args:
        capacity: Normal effective capacity for dates without an override.
        usage: Demand for one total, selected, or alternative scope.
        overrides: Sparse capacity overrides, including explicit zeroes.
    """
    days = [(date(2026, 1, 1) + timedelta(days=offset)).isoformat()
            for offset in range(3)]
    effective = [get_effective_capacity_for_date(day, capacity, overrides)
                 for day in days]
    over = calculate_daily_overassignments(usage, capacity, overrides)
    payload = dict(capacity=capacity, usage=usage, assignedCapacity=overrides,
                   start=days[0], end=days[-1])
    source = """
        import {createResourceSummaries} from './packages/planning-view/src/resources/summary.js';
        let input='';
        for await (const chunk of process.stdin) input+=chunk;
        console.log(JSON.stringify(createResourceSummaries().summarize(JSON.parse(input))));
    """

    result = subprocess.run(
        ["node", "--input-type=module", "-e", source],
        input=json.dumps(payload), capture_output=True, text=True,
        cwd=Path(__file__).resolve().parents[1], timeout=10, check=True,
    )
    actual = json.loads(result.stdout)

    assert actual["maxDemand"] == pytest.approx(max(usage.values(), default=0))
    assert actual["minCapacity"] == pytest.approx(min(effective))
    assert actual["maxCapacity"] == pytest.approx(max(effective))
    assert actual["maxExcess"] == pytest.approx(max((row.excess_fte for row in over), default=0))
    assert actual["isOverallocated"] is bool(over)
    assert actual["minAvailable"] == pytest.approx(max(0, min(
        effective[index] - usage.get(day, 0) for index, day in enumerate(days)
    )))
