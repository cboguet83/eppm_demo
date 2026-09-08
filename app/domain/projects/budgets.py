"""Decimal calculations for the existing planned-budget and actual-spend fields."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

ZERO = Decimal(0)
HUNDRED = Decimal(100)
type EuroInput = Decimal | str | int | float | None
type BudgetHealth = Literal["over_budget", "near_capacity", "on_track"]


def euro_amount(value: EuroInput) -> Decimal:
    """Convert historical storage/UI numbers before any financial arithmetic.

    Float inputs are compatibility values from existing SQLite REAL columns or
    number widgets. Their decimal string is used; lost historical precision
    cannot be recovered. New calculations never use binary floating point.
    """
    if value is None:
        return ZERO
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Budget amounts must be finite numbers.") from exc
    if not amount.is_finite():
        raise ValueError("Budget amounts must be finite numbers.")
    return amount


@dataclass(frozen=True)
class BudgetAmounts:
    """The two existing monetary concepts, expressed in euros."""

    planned_budget: Decimal = ZERO
    actual_budget: Decimal = ZERO


@dataclass(frozen=True)
class PortfolioMetrics:
    """Exact decimal totals and the existing portfolio burn-rate convention."""

    total_projects: int = 0
    total_planned: Decimal = ZERO
    total_actual: Decimal = ZERO
    variance: Decimal = ZERO
    burn_rate: Decimal = ZERO


@dataclass(frozen=True)
class BudgetAnalysis:
    """Derived variance, optional burn rate, and stable display-health code."""

    variance: Decimal
    burn_rate: Decimal | None
    health: BudgetHealth


def analyze_budget(amounts: BudgetAmounts) -> BudgetAnalysis:
    """Apply the existing variance and 85-percent health threshold rules.

    An actual amount against a zero budget has no defined percentage; zero
    planned and zero actual retain the existing zero-percent display.
    """
    planned, actual = amounts.planned_budget, amounts.actual_budget
    burn_rate = actual / planned * HUNDRED if planned else (None if actual else ZERO)
    if actual > planned:
        health = "over_budget"
    elif burn_rate is not None and burn_rate >= Decimal(85):
        health = "near_capacity"
    else:
        health = "on_track"
    return BudgetAnalysis(planned - actual, burn_rate, health)


def summarize_budgets(projects: Iterable[BudgetAmounts]) -> PortfolioMetrics:
    """Aggregate a stream without retaining project rows or using float sums."""
    count, planned, actual = 0, ZERO, ZERO
    for project in projects:
        count += 1
        planned += project.planned_budget
        actual += project.actual_budget
    return PortfolioMetrics(
        count,
        planned,
        actual,
        planned - actual,
        actual / planned * HUNDRED if planned > ZERO else ZERO,
    )


def monetary_statistics(amounts: Iterable[Decimal]) -> tuple[Decimal, Decimal, Decimal] | None:
    """Calculate minimum, mean, and maximum for monetary column statistics."""
    count, total = 0, ZERO
    low = high = None
    for amount in amounts:
        count += 1
        total += amount
        low = amount if low is None else min(low, amount)
        high = amount if high is None else max(high, amount)
    if low is None or high is None:
        return None
    return low, total / count, high
