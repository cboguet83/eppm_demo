"""Project-budget arithmetic preserves stored precision independently of callers."""

from decimal import Decimal, localcontext

import pytest

from app.domain.projects.budgets import BudgetAmounts, analyze_budget, decimal_mean, monetary_statistics, summarize_budgets


@pytest.mark.parametrize('precision', [4, 28])
def test_high_precision_budget_totals_and_variances_do_not_round_stored_values(precision):
    planned = Decimal('9007199254740993.1234567890123456789')
    actual = Decimal('0.0000000000000000001')
    with localcontext() as context:
        context.prec = precision
        analysis = analyze_budget(BudgetAmounts(planned, actual))
        metrics = summarize_budgets(iter([BudgetAmounts(planned, actual), BudgetAmounts(Decimal('0.0000000000000000001'))]))
    assert analysis.variance == Decimal('9007199254740993.1234567890123456788')
    assert metrics.total_planned == Decimal('9007199254740993.1234567890123456790')
    assert metrics.total_actual == actual
    assert metrics.variance == planned


@pytest.mark.parametrize('precision', [4, 28])
def test_budget_health_compares_exact_amounts_at_the_capacity_threshold(precision):
    with localcontext() as context:
        context.prec = precision
        below = analyze_budget(BudgetAmounts(Decimal('100'), Decimal('84.9999999999999999999999999999')))
        equal = analyze_budget(BudgetAmounts(Decimal('100'), Decimal('85')))
    assert below.health == 'on_track' and equal.health == 'near_capacity'


def test_statistics_keep_small_amounts_after_large_cancellation_and_do_not_round_terminating_means():
    values = [Decimal('9007199254740993.1234567890123456789'),
              Decimal('0.0000000000000000003'), Decimal('-9007199254740993.1234567890123456789')]
    with localcontext() as context:
        context.prec = 4
        result = monetary_statistics(iter(values))
    assert result == (values[2], Decimal('0.0000000000000000001'), values[0])


def test_a_terminating_mean_keeps_digits_added_by_dividing_a_precise_total():
    amount = Decimal('12345678901234567890123456789012345')
    with localcontext() as context:
        context.prec = 100
        expected = amount / 64
    with localcontext() as context:
        context.prec = 4
        result = monetary_statistics(iter([amount, *[Decimal(0)] * 63]))
    assert result == (Decimal(0), expected, amount)


@pytest.mark.parametrize('count', [0, -1, True, 1.5])
def test_decimal_mean_requires_an_actual_positive_item_count(count):
    with pytest.raises(ValueError, match='positive item count'):
        decimal_mean(Decimal(1), count)


@pytest.mark.parametrize('planned,actual,health,rate', [
    ('0', '0', 'on_track', Decimal(0)), ('0', '1', 'over_budget', None),
    ('-10', '-20', 'near_capacity', Decimal(200)), ('-10', '-5', 'over_budget', Decimal(50)),
])
def test_zero_and_negative_budget_health_keep_existing_conventions(planned, actual, health, rate):
    result = analyze_budget(BudgetAmounts(Decimal(planned), Decimal(actual)))
    assert result.health == health and result.burn_rate == rate
