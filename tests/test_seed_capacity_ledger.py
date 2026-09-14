"""Concurrent capacity checks for unsplit seed assignments."""

from datetime import date

from app.domain.resources.pool_seed import ProjectPeriod, TaskPeriod, SeedDemand, _CapacityLedger, plan_demand


def test_capacity_uses_peak_concurrent_demand_and_inclusive_end_dates():
    ledger = _CapacityLedger()
    first = SeedDemand('A', 1, date(2026, 1, 1), date(2026, 1, 10), 2000, 1)
    second = SeedDemand('A', 2, date(2026, 1, 10), date(2026, 1, 20), 1500, 2)
    ledger.reserve(first)
    ledger.reserve(second)
    assert ledger.remaining('A', date(2026, 1, 5), date(2026, 1, 15), 5000) == 1500
    assert ledger.remaining('A', date(2026, 1, 11), date(2026, 1, 15), 5000) == 3500
    assert ledger.remaining('A', date(2026, 1, 21), date.max, 5000) == 5000
    ledger.reserve(second, -1)
    assert ledger.remaining('A', date(2026, 1, 10), date(2026, 1, 10), 5000) == 3000
    assert ledger.remaining('B', date.min, date.max, 5000) == 5000


def test_capacity_handles_maximum_date_and_releases_reservations():
    ledger = _CapacityLedger()
    row = SeedDemand('A', 1, date.max, date.max, 100, 1)
    ledger.reserve(row)
    assert ledger.remaining('A', date.max, date.max, 100) == 0
    ledger.reserve(row, -1)
    assert ledger.remaining('A', date.max, date.max, 100) == 100


def test_failed_project_releases_slots_for_later_projects():
    projects = [ProjectPeriod(i, date(2026, 1, 1), date(2026, 12, 31)) for i in range(1, 5)]
    tasks = [TaskPeriod(i, i, p.start, p.end) for i, p in enumerate(projects, 1)]
    tasks += [TaskPeriod(i+100, 2, projects[0].start, projects[0].end) for i in range(5000)]
    rows, _, omitted = plan_demand(projects, 42, tasks=tasks)
    assert {row.project_id for row in rows} == {1, 3, 4}
    assert omitted == 1
