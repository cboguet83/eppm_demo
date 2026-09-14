"""Exact demo WBS budgets and bounded project allocation shares."""

from decimal import Decimal, ROUND_FLOOR, localcontext
import random

from app.domain.finance import BudgetRow


START_YEARS = (2020, 2020, 2021, 2021, 2022, 2022, 2024, 2024, 2025, 2025)


def budget_rows(seed: int) -> tuple[BudgetRow, ...]:
    """Distribute €5–10 million per WBS over ten Gaussian-weighted years.

    Use a midpoint of 4.5 years and standard deviation of two years. Largest
    remainders allocate the final cents so each row sums exactly to its total.
    """
    rng = random.Random(seed)
    rows = []
    with localcontext() as context:
        context.prec = 40
        weights = [(-((Decimal(i)-Decimal('4.5')) ** 2)/8).exp() for i in range(10)]
        weight_sum = sum(weights)
        for number, start in enumerate(START_YEARS, 1):
            cents = rng.randint(500_000_000, 1_000_000_000)
            exact = [Decimal(cents) * weight / weight_sum for weight in weights]
            parts = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
            ranking = sorted(range(10), key=lambda i: (-(exact[i]-parts[i]), i))
            for i in ranking[:cents-sum(parts)]:
                parts[i] += 1
            rows.append(BudgetRow(f'p.{number}.10',
                                 {start+i: Decimal(value)/100 for i, value in enumerate(parts)}))
    return tuple(rows)


def wbs_shares(project_ids: list[int], seed: int) -> tuple[tuple[int, str, int], ...]:
    """Allocate the specified first two projects and remaining shares to ten more."""
    projects = sorted(set(project_ids))[:12]
    if not projects:
        return ()
    rows = [(projects[0], 'p.1.10', 100)]
    if len(projects) < 2:
        return tuple(rows)
    rows.extend([(projects[1], 'p.2.10', 100), (projects[1], 'p.3.10', 50)])
    # Thirty remaining 25% units, distributed across ten project slots.
    rng = random.Random(seed)
    units = [(f'p.{number}.10', 2 if number == 3 else 4) for number in range(3, 11)]
    remaining = 30
    code_index = 0
    for index, identity in enumerate(projects[2:]):
        slots_left = 9-index
        quota = rng.randint(max(1, remaining-4*slots_left), min(4, remaining-slots_left))
        remaining -= quota
        while quota:
            code, available = units[code_index]
            share = min(quota, available)
            rows.append((identity, code, share*25))
            quota -= share
            units[code_index] = (code, available-share)
            if available == share:
                code_index += 1
    return tuple(rows)
