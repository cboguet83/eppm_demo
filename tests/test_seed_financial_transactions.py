"""Demo spending percentages preserve WBS distribution and exact euro cents."""

from decimal import Decimal, localcontext

from app.domain.projects.seed_financial_transactions import ApprovedProjectAmount, spending_targets


def test_past_current_and_future_ranges_and_consistent_wbs_distribution():
    budgets = tuple(ApprovedProjectAmount(project, code, year, Decimal(amount))
                    for project in range(1, 15) for year in range(2024, 2030)
                    for code, amount in [('A', '100000'), ('B', '300000')])
    with localcontext(prec=5):
        values = spending_targets(budgets, year=2026, seed=20260918)
    lookup = {(value.budget.project_id, value.budget.wbs, value.budget.year): value for value in values}
    for target in values:
        amount, year = target.budget.amount, target.budget.year
        if year < 2026:
            assert amount * Decimal('.95') <= target.actual <= amount * Decimal('1.05')
            assert target.commitment == 0
        elif year == 2026:
            total = target.actual + target.commitment
            assert amount * Decimal('.8') <= total <= amount
            assert Decimal('.2') <= target.actual / total <= Decimal('.8')
        else:
            assert target.actual == 0
            assert 0 <= target.commitment <= amount * Decimal('.75')
        assert target.actual.as_tuple().exponent == target.commitment.as_tuple().exponent == -2
        if target.budget.wbs == 'B':
            first = lookup[target.budget.project_id, 'A', year]
            assert abs(target.actual - first.actual * 3) <= Decimal('.02')
            assert abs(target.commitment - first.commitment * 3) <= Decimal('.02')
    assert values == spending_targets(tuple(reversed(budgets)), year=2026, seed=20260918)
    for project in range(1, 15):
        assert lookup[project, 'A', 2024].actual == lookup[project, 'A', 2025].actual


def test_empty_and_zero_budgets_create_no_spending():
    assert spending_targets((), year=2026, seed=1) == ()
    targets = spending_targets(tuple(ApprovedProjectAmount(1, 'A', year, Decimal(0))
                                     for year in range(2025, 2028)), year=2026, seed=1)
    assert all(target.actual == target.commitment == 0 for target in targets)
