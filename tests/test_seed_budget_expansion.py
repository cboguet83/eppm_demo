"""Budget band counts, Gaussian allocation, and status-compatible project shares."""

from collections import Counter
from decimal import Decimal, localcontext

import pytest

from app.domain.projects.seed_budget_expansion import expanded_budget_rows, expansion_project_shares, shifted_plateau_budgets, extend_budget_plateaus


def test_expanded_budgets_have_exact_bands_periods_and_normal_annual_weights():
    rows = expanded_budget_rows(Decimal('200000000'))
    assert len(rows) == len({row.code for row in rows}) == 1500
    bands = Counter()
    for row in rows:
        amounts = list(row.amounts.values())
        total = sum(amounts)
        band = next(index for index, (low, high) in enumerate([
            (100000, 200000), (150000000, 200000000), (200000, 2000000),
            (2000000, 10000000), (10000000, 30000000)]) if low < total < high)
        historical = max(row.amounts) < 2026
        bands[historical, band] += 1
        assert list(row.amounts) == list(range(2020, 2026) if historical else range(2026, 2036))
        assert all(value > 0 and value * 100 == int(value * 100) for value in amounts)
        assert amounts[:len(amounts) // 2] == sorted(amounts[:len(amounts) // 2])
        assert all(abs(left - right) <= Decimal('.01') for left, right in zip(amounts, reversed(amounts)))
        # The log ratio between adjacent Gaussian weights changes linearly.
        sigma = Decimal(len(amounts)) / 5
        expected_curvature = (-1 / sigma ** 2).exp()
        for index in range(1, len(amounts) - 1):
            curvature = amounts[index - 1] * amounts[index + 1] / amounts[index] ** 2
            assert abs(curvature - expected_curvature) < Decimal('.00001')
    assert [bands[True, band] for band in range(5)] == [50, 50, 150, 100, 150]
    assert [bands[False, band] for band in range(5)] == [100, 100, 300, 200, 300]
    assert rows == expanded_budget_rows(Decimal('200000000'))


def test_shares_are_unique_and_use_only_status_compatible_budgets():
    rows = expanded_budget_rows(Decimal('200000000'))
    projects = [(i, 'Completed' if i <= 100 else 'In Progress') for i in range(1, 989)]
    shares = expansion_project_shares(projects, rows)
    assert len(shares) == len({code for _, code in shares}) == 988
    by_code = {row.code: row for row in rows}
    for project, code in shares:
        assert (max(by_code[code].amounts) < 2026) == (project <= 100)
    with pytest.raises(ValueError, match='Not enough'):
        expansion_project_shares([(i, 'Completed') for i in range(501)], rows)


def test_shifts_have_exact_counts_and_copy_peak_without_changing_other_years():
    original = expanded_budget_rows(Decimal('200000000'))
    shifted = shifted_plateau_budgets(original)
    assert shifted[:500] == original[:500]
    counts = Counter()
    for before, after in zip(original[500:], shifted[500:]):
        offset = min(after.amounts) - min(before.amounts)
        counts[offset] += 1
        peak = min(before.amounts, key=lambda year: (-before.amounts[year], year))
        for year, amount in before.amounts.items():
            assert after.amounts[year + offset] == (before.amounts[peak] if abs(year - peak) <= 1 else amount)
        assert sum(after.amounts.values()) > sum(before.amounts.values())
    assert counts == {-4: 100, -3: 100, -2: 100, -1: 100, 0: 400, 1: 100, 2: 100}
    with pytest.raises(ValueError, match='refusing to shift again'):
        shifted_plateau_budgets(shifted)


def test_plateau_extends_two_years_earlier_and_rejects_a_repeat():
    original = shifted_plateau_budgets(expanded_budget_rows(Decimal('200000000')))
    extended = extend_budget_plateaus(original)
    assert extended[:500] == original[:500]
    for before, after in zip(original[500:], extended[500:]):
        peak = max(before.amounts.values())
        start = min(year for year, amount in before.amounts.items() if amount == peak)
        assert [year for year, amount in after.amounts.items() if amount == peak] == list(range(start - 2, start + 3))
        assert all(after.amounts[year] == amount for year, amount in before.amounts.items() if year not in (start - 2, start - 1))
    with pytest.raises(ValueError, match='refusing to extend again'):
        extend_budget_plateaus(extended)


def test_five_year_plateau_extends_one_more_year_without_moving_its_end():
    original = extend_budget_plateaus(shifted_plateau_budgets(expanded_budget_rows(Decimal('200000000'))))
    extended = extend_budget_plateaus(original, additional_years=1, expected_years=5)
    assert extended[:500] == original[:500]
    for before, after in zip(original[500:], extended[500:]):
        peak = max(before.amounts.values())
        years = sorted(year for year, amount in before.amounts.items() if amount == peak)
        assert after.amounts[years[0] - 1] == peak
        assert all(after.amounts[year] == amount for year, amount in before.amounts.items() if year != years[0] - 1)
        assert sum(amount == peak for amount in after.amounts.values()) == 6
    with pytest.raises(ValueError, match='refusing to extend again'):
        extend_budget_plateaus(extended, additional_years=1, expected_years=5)


def test_scaling_preserves_years_and_codes_with_whole_euro_half_up_rounding():
    from app.domain.finance import BudgetRow
    from app.domain.projects.seed_budget_expansion import scaled_budget_rows

    rows = (BudgetRow('A', {2025: Decimal('9.99'), 2026: Decimal('10'),
                          2027: Decimal('123456.78'), 2028: Decimal('-10')}), BudgetRow('B', {}))
    with localcontext(prec=4):
        result = scaled_budget_rows(rows)
    assert result == (BudgetRow('A', {2025: Decimal(0), 2026: Decimal(1),
                                    2027: Decimal(6173), 2028: Decimal(-1)}), BudgetRow('B', {}))
    assert rows[0].amounts[2026] == Decimal('10')
