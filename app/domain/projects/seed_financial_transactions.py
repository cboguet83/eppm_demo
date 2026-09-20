"""Reproducible demo spending targets with consistent project/WBS percentages."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
from random import Random


@dataclass(frozen=True)
class ApprovedProjectAmount:
    """One project's allocated approved WBS amount in a fiscal year."""

    project_id: int
    wbs: str
    year: int
    amount: Decimal


@dataclass(frozen=True)
class ProjectSpendingTarget:
    """Desired total actuals and commitments, rather than additional spending."""

    budget: ApprovedProjectAmount
    actual: Decimal
    commitment: Decimal


def spending_targets(budgets: tuple[ApprovedProjectAmount, ...], *, year: int,
                     seed: int) -> tuple[ProjectSpendingTarget, ...]:
    """Use project-specific ratios, shared by all WBS codes, rounded to cents.

    Past years share one 95–105% actual multiplier per project. Current-year
    spending is 80–100% of approved, with actuals representing 30–80% of that
    combined spending. Future commitments use a 60–95% multiplier per project/year.

    Security review: Random generates synthetic demo amounts only, never secrets,
    identifiers or authorization decisions. Predictability is intentional: the
    same seed must reproduce preview/apply targets and make reruns idempotent.
    """
    result = []
    with localcontext(prec=60):
        for budget in sorted(budgets, key=lambda cell: (cell.project_id, cell.year, cell.wbs)):
            rng = Random(f'{seed}:{budget.project_id}')
            past = Decimal(rng.randint(9500, 10500)) / 10000
            current = Decimal(rng.randint(8000, 10000)) / 10000
            actual_share = Decimal(rng.randint(3000, 8000)) / 10000
            actual = commitment = Decimal('0.00')
            if budget.year < year:
                actual = (budget.amount * past).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            elif budget.year == year:
                total = (budget.amount * current).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                actual = (total * actual_share).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                commitment = total - actual
            else:
                future_rng = Random(f'{seed}:{budget.project_id}:{budget.year}:future')
                future = Decimal(future_rng.randint(6000, 9500)) / 10000
                commitment = (budget.amount * future).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            result.append(ProjectSpendingTarget(budget, actual, commitment))
    return tuple(result)
