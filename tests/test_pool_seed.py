"""Exact aggregate demand, inclusive boundaries and representability checks."""

from collections import Counter, defaultdict
from datetime import date

import pytest

from app.domain.resources.pool_seed import POOLS, ProjectPeriod, _pool_demand, membership_intervals, monthly_utilization, plan_demand


def period(identity, start=1, end=30):
    return ProjectPeriod(identity, date(2026, 1, start), date(2026, 1, end))


def test_thousand_projects_cover_all_pools_with_exact_aggregate_categories():
    projects = [period(identity, 1 + identity % 10, 20 + identity % 10) for identity in range(1000)]
    demand, rates, omitted = plan_demand(projects, 42)
    assert (omitted, len({row.project_id for row in demand})) == (100, 900)
    assert len({row.pool_name for row in demand}) == 33
    assert rates['pool E1'] == rates['pool E2'] == 80
    daily = defaultdict(int)
    for row in demand:
        assert row.milli_fte > 0
        for day in range(row.start.toordinal(), row.end.toordinal() + 1):
            daily[row.pool_name, day] += row.milli_fte
    for pool in POOLS:
        observed = {value * 100 // (pool.capacity * 1000) for (name, _), value in daily.items() if name == pool.name}
        assert observed == {monthly_utilization(pool.name, rates[pool.name], date(2026, 1, 1))}
        assert max(observed) <= 200
    assert plan_demand(list(reversed(projects)), 42) == (demand, rates, omitted)
    assert plan_demand(projects, 43) != (demand, rates, omitted)


@pytest.mark.parametrize('count,omitted', [(0, 0), (4, 0), (5, 1), (15, 2), (1000, 100)])
def test_half_up_project_coverage(count, omitted):
    demand, rates, actual = plan_demand([period(i) for i in range(count)], 7)
    assert actual == omitted
    assert len({row.project_id for row in demand}) == count - omitted
    assert len(rates) == (33 if count else 0)


def test_membership_intervals_are_inclusive_and_exclude_idle_gaps():
    assert membership_intervals([period(1, 1, 3), period(2, 3, 4), period(3, 7, 7)]) == [
        (date(2026, 1, 1).toordinal(), date(2026, 1, 2).toordinal(), (1,)),
        (date(2026, 1, 3).toordinal(), date(2026, 1, 3).toordinal(), (1, 2)),
        (date(2026, 1, 4).toordinal(), date(2026, 1, 4).toordinal(), (2,)),
        (date(2026, 1, 7).toordinal(), date(2026, 1, 7).toordinal(), (3,)),
    ]


def test_monthly_variability_and_e1_e2_cap_are_preserved_across_years():
    for pool in POOLS:
        rate = 80 if pool.name in ('pool E1', 'pool E2') else 150
        rows = _pool_demand(pool, [ProjectPeriod(1, date(2026, 1, 1), date(2027, 12, 31))], rate)
        assert len(rows) == 24
        usage = [row.milli_fte / (pool.capacity * 1000) for row in rows]
        assert len(set(usage)) >= 5
        assert max(usage) <= (.8 if rate == 80 else 1.8)
        assert min(usage) < 1
        assert all(row.start.day == 1 and row.start.month == row.end.month for row in rows)


def test_precision_failure_and_invalid_bounds_fail_before_persistence():
    with pytest.raises(ValueError, match='precision'):
        _pool_demand(POOLS[0], [period(i) for i in range(10001)], 100)
    with pytest.raises(ValueError, match='before'):
        membership_intervals([period(1, 5, 3)])
    with pytest.raises(ValueError, match='200%'):
        _pool_demand(POOLS[0], [period(1)], 201)


def test_maximum_supported_date_has_no_overflow():
    rows, _, _ = plan_demand([ProjectPeriod(1, date.max, date.max)], 1)
    assert all(row.start == row.end == date.max for row in rows)


def test_low_demand_spans_quarters_even_when_project_membership_changes_daily():
    projects = [ProjectPeriod(i, date(2026, 1, i), date(2027, 12, i)) for i in range(1, 29)]
    rows = _pool_demand(POOLS[0], projects, 75)
    for day in (date(2026, 4, 1), date(2026, 5, 15), date(2026, 6, 30)):
        assert sum(row.milli_fte for row in rows if row.start <= day <= row.end) == 100 * monthly_utilization(POOLS[0].name, 75, day)


def test_service_p_task_pools_reassign_undated_projects_to_project_level_team_b():
    from app.domain.resources.pool_seed import TASK_POOLS, TaskPeriod
    projects = [ProjectPeriod(i, date(2026, 1, 1), date(2026, 12, 31)) for i in range(100)]
    tasks = [TaskPeriod(1000+i, i, date(2026, 2, 1), date(2026, 11, 30)) for i in range(0, 100, 2)]
    rows, _, omitted = plan_demand(projects, 42, tasks=tasks)
    assert len({row.project_id for row in rows}) == len(projects) - omitted
    assert {row.pool_name for row in rows if row.task_id} == TASK_POOLS
    assert all(row.task_id is not None for row in rows if row.pool_name in TASK_POOLS)
    assert all(row.task_id is None for row in rows if row.pool_name == 'team B')
    assert all(row.start >= date(2026, 2, 1) and row.end <= date(2026, 11, 30) for row in rows if row.task_id)
