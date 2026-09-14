"""Exact aggregate demand, inclusive boundaries and representability checks."""

from collections import Counter, defaultdict
from datetime import date, timedelta

import pytest

from app.domain.resources.pool_seed import POOLS, ProjectPeriod, TaskPeriod, SeedDemand, _CapacityLedger, plan_demand, plan_capacity_exceptions


@pytest.mark.parametrize('year', [2024, 2026, 9999])
def test_capacity_reductions_have_exact_calendar_durations_and_capacity_threshold(year):
    """Each pool receives bounded six-month and additional full-year periods."""
    rows = plan_capacity_exceptions(year, 42)
    assert rows == plan_capacity_exceptions(year, 42)
    assert rows != plan_capacity_exceptions(year, 43)
    counts = Counter()
    for name, start, end in rows:
        months = (end.year-start.year)*12 + end.month-start.month + 1
        assert start.day == 1
        assert end == date.max or (end + timedelta(days=1)).day == 1
        assert min(year, 9995) <= start.year <= end.year <= min(year, 9995)+4
        assert months in (6, 12)
        counts[name, months] += 1
    for pool in POOLS:
        assert 1 <= counts[pool.name, 6] <= 3
        assert counts[pool.name, 12] == (2 if pool.capacity > 6 else 0)


def period(identity, start=1, end=30):
    return ProjectPeriod(identity, date(2026, 1, start), date(2026, 1, end))


def test_thousand_projects_cover_all_pools_with_exact_aggregate_categories():
    projects = [period(identity, 1 + identity % 10, 20 + identity % 10) for identity in range(1000)]
    tasks = [TaskPeriod(p.project_id, p.project_id, p.start, p.end) for p in projects]
    demand, rates, omitted = plan_demand(projects, 42, tasks=tasks)
    assert omitted == 1000 - len({row.project_id for row in demand})
    assert omitted > 0
    assert len({row.pool_name for row in demand}) == 33
    assert rates['pool E1'] == rates['pool E2'] == 80
    daily = defaultdict(int)
    for row in demand:
        assert 100 <= row.milli_fte <= 5000
        assert (row.task_id is None) == (row.project_id < 250)
        for day in range(row.start.toordinal(), row.end.toordinal() + 1):
            daily[row.pool_name, day] += row.milli_fte
    for pool in POOLS:
        observed = {value * 100 // (pool.capacity * 1000) for (name, _), value in daily.items() if name == pool.name}
        assert max(observed) <= (180 if rates[pool.name] > 100 else rates[pool.name])
    assert sum(rate > 100 for rate in rates.values()) == 7
    assert sum(rate == 75 for rate in rates.values()) == 4
    assert plan_demand(list(reversed(projects)), 42, tasks=list(reversed(tasks))) == (demand, rates, omitted)
    assert plan_demand(projects, 43, tasks=tasks) != (demand, rates, omitted)


@pytest.mark.parametrize('count', [0, 4, 5, 15, 1000])
def test_undated_projects_remain_unallocated(count):
    demand, rates, actual = plan_demand([period(i) for i in range(count)], 7)
    assert actual == count
    assert demand == () and rates == {}


def test_membership_intervals_are_inclusive_and_exclude_idle_gaps():
    ledger = _CapacityLedger()
    for p in [period(1, 1, 3), period(2, 3, 4), period(3, 7, 7)]:
        ledger.reserve(SeedDemand('A', p.project_id, p.start, p.end, 100))
    assert ledger.remaining('A', date(2026, 1, 3), date(2026, 1, 3), 1000) == 800
    assert ledger.remaining('A', date(2026, 1, 5), date(2026, 1, 6), 1000) == 1000


def test_long_periods_are_not_split_into_monthly_custom_assignments():
    projects = [ProjectPeriod(i, date(2026, 1, 1), date(2027, 12, 31)) for i in range(1000)]
    tasks = [TaskPeriod(p.project_id, p.project_id, p.start, p.end) for p in projects]
    rows, rates, _ = plan_demand(projects, 42, tasks=tasks)
    assert rates['pool E1'] == rates['pool E2'] == 80
    assert all(row.start == projects[0].start and row.end == projects[0].end for row in rows)
    assert len(rows) == len({row.project_id for row in rows})
    totals = Counter()
    for row in rows:
        totals[row.pool_name, row.task_id is not None] += row.milli_fte
    for pool in POOLS:
        ceiling = 180 if rates[pool.name] > 100 else rates[pool.name]
        assert all(totals[pool.name, level] <= pool.capacity * 1000 * ceiling // 200 for level in (True, False))


def test_precision_failure_and_invalid_bounds_fail_before_persistence():
    with pytest.raises(ValueError, match='before'):
        plan_demand([period(1, 5, 3)], 1)
    with pytest.raises(ValueError, match='before'):
        plan_demand([period(1)], 1, tasks=[TaskPeriod(1, 1, date(2026, 2, 1), date(2026, 1, 1))])


def test_maximum_supported_date_has_no_overflow():
    rows, _, _ = plan_demand([ProjectPeriod(1, date.max, date.max)], 1, tasks=[TaskPeriod(1, 1, date.max, date.max)])
    assert rows
    assert all(row.start == row.end == date.max for row in rows)


def test_low_demand_spans_quarters_even_when_project_membership_changes_daily():
    projects = [ProjectPeriod(i, date(2026, 1, i), date(2027, 12, i)) for i in range(1, 29)]
    tasks = [TaskPeriod(p.project_id, p.project_id, p.start, p.end) for p in projects]
    rows, _, _ = plan_demand(projects, 42, tasks=tasks)
    bounds = {p.project_id: (p.start, p.end) for p in projects}
    assert all((row.start, row.end) == bounds[row.project_id] for row in rows)


def test_first_quarter_is_project_level_and_remaining_projects_are_task_level():
    projects = [ProjectPeriod(i, date(2026, 1, 1), date(2026, 12, 31)) for i in range(100)]
    tasks = [TaskPeriod(1000+i, i, date(2026, 2, 1), date(2026, 11, 30)) for i in range(0, 100, 2)]
    rows, _, omitted = plan_demand(projects, 42, tasks=tasks)
    assert len({row.project_id for row in rows}) == len(projects) - omitted
    assert all((row.task_id is None) == (row.project_id < 25) for row in rows)
    assert all(row.project_id % 2 == 0 for row in rows)
    assert all(row.start >= date(2026, 2, 1) and row.end <= date(2026, 11, 30) for row in rows if row.task_id)
