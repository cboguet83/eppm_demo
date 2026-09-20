"""Exact demo budget bands and Gaussian annual allocations for 1,500 WBS."""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, localcontext
from hashlib import sha256

from app.domain.finance import BudgetRow


EXPANSION_PREFIX = 'demo.expansion.'


def scaled_budget_rows(rows: tuple[BudgetRow, ...]) -> tuple[BudgetRow, ...]:
    """Divide each yearly WBS amount by twenty and round half up to whole euros."""
    with localcontext(prec=60):
        return tuple(BudgetRow(row.code, {
            year: (amount / 20).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            for year, amount in row.amounts.items()
        }) for row in rows)


def expanded_budget_rows(high_budget_cap: Decimal) -> tuple[BudgetRow, ...]:
    """Build 500 historical and 1,000 future budgets with exact band counts.

    Each period cohort has 10/10/30/20/30 percent of its rows in the requested
    bands. Totals are evenly spaced inside each band. Annual weights sample a
    normal curve centered on the period midpoint, with sigma one fifth of its
    duration. Largest remainders preserve total cents. No floats are used.
    """
    if not high_budget_cap.is_finite() or high_budget_cap <= Decimal('150000000'):
        raise ValueError('The upper budget limit must exceed EUR 150 million.')
    rows = []
    with localcontext(prec=50):
        for count, first, years in ((500, 2020, 6), (1000, 2026, 10)):
            bands = ((10, Decimal('100000'), Decimal('200000')),
                     (10, Decimal('150000000'), high_budget_cap),
                     (30, Decimal('200000'), Decimal('2000000')),
                     (20, Decimal('2000000'), Decimal('10000000')),
                     (30, Decimal('10000000'), Decimal('30000000')))
            midpoint = Decimal(years - 1) / 2
            sigma = Decimal(years) / 5
            weights = [(-((Decimal(i) - midpoint) ** 2) / (2 * sigma ** 2)).exp()
                       for i in range(years)]
            weight_sum = sum(weights)
            for percentage, lower, upper in bands:
                size = count * percentage // 100
                for index in range(size):
                    total = (lower + (upper - lower) * (index + 1) / (size + 1)).quantize(Decimal('.01'))
                    cents = int(total * 100)
                    exact = [Decimal(cents) * weight / weight_sum for weight in weights]
                    parts = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
                    ranking = sorted(range(years), key=lambda i: (-(exact[i] - parts[i]), i))
                    for i in ranking[:cents - sum(parts)]:
                        parts[i] += 1
                    rows.append(BudgetRow(f'{EXPANSION_PREFIX}{len(rows) + 1:04d}',
                                          {first + i: Decimal(part) / 100 for i, part in enumerate(parts)}))
    return tuple(rows)


def expansion_project_shares(
    projects: list[tuple[int, str]], rows: tuple[BudgetRow, ...],
) -> tuple[tuple[int, str], ...]:
    """Assign distinct WBS codes by project status, with a stable mixed band order."""
    result = []
    for completed in (True, False):
        identities = sorted(identity for identity, status in projects if (status == 'Completed') == completed)
        available = sorted((row.code for row in rows if (max(row.amounts) < 2026) == completed),
                           key=lambda code: sha256(code.encode('ascii')).digest())
        if len(identities) > len(available):
            raise ValueError('Not enough distinct WBS budgets for the unmapped project statuses.')
        result.extend(zip(identities, available))
    return tuple(result)


def shifted_plateau_budgets(rows: tuple[BudgetRow, ...]) -> tuple[BudgetRow, ...]:
    """Shift the 1,000 future WBS and extend the earliest peak to its neighbors.

    A stable mixed-code order assigns 100 WBS to each nonzero shift and 400
    to zero. Peak copying intentionally increases totals without renormalizing.
    Rows outside this cohort retain their amounts, including historical WBS.
    """
    codes = {f'{EXPANSION_PREFIX}{number:04d}' for number in range(501, 1501)}
    if codes - {row.code for row in rows}:
        raise ValueError('All 1,000 future expansion budgets must exist.')
    ordered = sorted(codes, key=lambda code: sha256(code.encode('ascii')).digest())
    offsets = [-4] * 100 + [-3] * 100 + [-2] * 100 + [-1] * 100 + [0] * 400 + [1] * 100 + [2] * 100
    shifts = dict(zip(ordered, offsets))
    result = []
    for row in rows:
        if row.code not in shifts:
            result.append(row)
            continue
        if set(row.amounts) != set(range(2026, 2036)):
            raise ValueError('Expected original 2026–2035 budgets; refusing to shift again.')
        amounts = {year + shifts[row.code]: amount for year, amount in row.amounts.items()}
        peak = min(amounts, key=lambda year: (-amounts[year], year))
        amounts[peak - 1] = amounts[peak + 1] = amounts[peak]
        result.append(BudgetRow(row.code, dict(sorted(amounts.items()))))
    return tuple(result)


def extend_budget_plateaus(
    rows: tuple[BudgetRow, ...], *, additional_years: int = 2, expected_years: int = 3,
) -> tuple[BudgetRow, ...]:
    """Extend the 1,000 expansion plateaus before their current start.

    Require the expected existing plateau length to prevent accidental repeats.
    Other years, WBS, and the plateau's ending year remain unchanged.
    """
    if type(additional_years) is not int or type(expected_years) is not int or min(additional_years, expected_years) < 1:
        raise ValueError('Plateau lengths must be positive whole years.')
    codes = {f'{EXPANSION_PREFIX}{number:04d}' for number in range(501, 1501)}
    if codes - {row.code for row in rows}:
        raise ValueError('All 1,000 expansion budgets must exist.')
    result = []
    for row in rows:
        if row.code not in codes:
            result.append(row)
            continue
        peak = max(row.amounts.values())
        years = sorted(year for year, amount in row.amounts.items() if amount == peak)
        if len(years) != expected_years or years != list(range(years[0], years[0] + expected_years)):
            raise ValueError(f'Expected a {expected_years}-year plateau; refusing to extend again.')
        if years[0] - additional_years < 1:
            raise ValueError('The extended plateau would precede year 1.')
        amounts = dict(row.amounts)
        for year in range(years[0] - additional_years, years[0]):
            amounts[year] = peak
        result.append(BudgetRow(row.code, dict(sorted(amounts.items()))))
    return tuple(result)
