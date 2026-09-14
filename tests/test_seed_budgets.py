"""Exact ten-year budget curves and conserved WBS allocation percentages."""

from collections import Counter
from decimal import Decimal

from app.domain.projects.seed_budgets import START_YEARS, budget_rows, wbs_shares


def test_budget_curves_use_requested_start_years_and_exact_cent_totals():
    rows = budget_rows(42)
    assert len(rows) == 10 and rows == budget_rows(42)
    assert rows != budget_rows(43)
    for number, (row, start) in enumerate(zip(rows, START_YEARS), 1):
        assert row.code == f'p.{number}.10'
        assert list(row.amounts) == list(range(start, start+10))
        values = list(row.amounts.values())
        assert Decimal(5_000_000) <= sum(values) <= Decimal(10_000_000)
        assert all(value > 0 and value*100 == (value*100).to_integral_value() for value in values)
        assert values[:5] == sorted(values[:5])
        assert values[5:] == sorted(values[5:], reverse=True)
        assert all(abs(a-b) <= Decimal('.01') for a, b in zip(values, reversed(values)))


def test_first_two_projects_have_fixed_shares_and_next_ten_consume_remaining_shares():
    ids = list(range(10, 30))
    rows = wbs_shares(list(reversed(ids)), 42)
    assert rows[:3] == ((10, 'p.1.10', 100), (11, 'p.2.10', 100), (11, 'p.3.10', 50))
    assert {identity for identity, _, _ in rows[3:]} == set(range(12, 22))
    totals = Counter()
    for _, code, percentage in rows:
        assert 25 <= percentage <= 100 and percentage % 25 == 0
        totals[code] += percentage
    assert totals == {f'p.{i}.10': 100 for i in range(1, 11)}
    assert wbs_shares([], 42) == ()
    assert wbs_shares([10], 42) == rows[:1]
    for count in range(2, 12):
        short = wbs_shares(ids[:count], 42)
        assert {identity for identity, _, _ in short} == set(ids[:count])
        assert all(sum(p for _, c, p in short if c == code) <= 100 for _, code, _ in short)
