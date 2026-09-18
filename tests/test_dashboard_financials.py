"""Exact financial utilization uses the visible years and handles zero budgets."""

from decimal import Decimal, localcontext

import pytest

from app.domain.dashboard import AllocatedBudget, financial_utilization, yearly_financial_amounts
from app.domain.financial_transactions import YearlyProjectFinancials


def test_financial_totals_share_chart_period_and_preserve_decimal_precision():
    records = (
        YearlyProjectFinancials(1, 2026, Decimal('10.01'), Decimal('20.02')),
        YearlyProjectFinancials(2, 2026, Decimal('30.03'), Decimal('40.04')),
        YearlyProjectFinancials(1, 2027, Decimal('-5.04'), Decimal('10.04')),
        YearlyProjectFinancials(1, 2000, Decimal('999'), Decimal('999')),
    )
    budget = AllocatedBudget((), {2026: Decimal('50.05'), 2027: Decimal('49.95'), 2000: Decimal('999')}, ())
    with localcontext(prec=3):
        amounts = yearly_financial_amounts(records, range(2026, 2029))
        result = financial_utilization(budget, records, range(2026, 2029))
        assert amounts == {2026: (Decimal('40.04'), Decimal('60.06')),
                           2027: (Decimal('-5.04'), Decimal('10.04')), 2028: (Decimal(0), Decimal(0))}
        assert result.actual_percentage == Decimal('35')
        assert result.committed_percentage == Decimal('105.10')


@pytest.mark.parametrize('approved', [{}, {2026: Decimal(0)}])
def test_missing_or_zero_approved_budget_has_no_misleading_percentage(approved):
    result = financial_utilization(AllocatedBudget((), approved, ()),
        (YearlyProjectFinancials(1, 2026, Decimal(50), Decimal(100)),), range(2026, 2027))
    assert result.actual_percentage is None and result.committed_percentage is None
