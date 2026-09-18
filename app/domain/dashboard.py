"""Exact allocated budgets, organizational facets, and concurrent pool shortages."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import TypedDict

from app.domain.finance import BudgetSnapshot
from app.domain.financial_transactions import YearlyProjectFinancials
from app.domain.resources.models import PoolCapacityDetail


class DashboardProject(TypedDict):
    """Authorized project fields; dynamic values are text lists at this boundary."""

    id: int
    name: str
    fields: dict[str, list[str]]


@dataclass(frozen=True)
class WbsShare:
    """Current authorized project share of a catalog WBS code."""

    project_id: int
    code: str
    percentage: int


@dataclass(frozen=True)
class AllocatedBudget:
    """Calculated Decimal euros by project/WBS/year and matching aggregate totals."""

    rows: tuple[tuple[WbsShare, dict[int, Decimal]], ...]
    totals: dict[int, Decimal]
    unmatched: tuple[str, ...]


@dataclass(frozen=True)
class FinancialUtilization:
    """Exact totals and ratios over the same years as the financial chart."""

    actual: Decimal
    commitment: Decimal
    approved: Decimal

    @property
    def actual_percentage(self) -> Decimal | None:
        """Return no percentage when an approved denominator is unavailable."""
        with localcontext(prec=60):
            return self.actual * 100 / self.approved if self.approved > 0 else None

    @property
    def committed_percentage(self) -> Decimal | None:
        """Include actuals and commitments without subtracting linked actuals."""
        with localcontext(prec=60):
            return (self.actual + self.commitment) * 100 / self.approved if self.approved > 0 else None


def yearly_financial_amounts(records: tuple[YearlyProjectFinancials, ...],
                             years: range) -> dict[int, tuple[Decimal, Decimal]]:
    """Sum stored euro totals across filtered projects without binary floats."""
    totals = {year: (Decimal(0), Decimal(0)) for year in years}
    with localcontext(prec=60):
        for record in records:
            if record.fiscal_year in totals:
                actual, commitment = totals[record.fiscal_year]
                totals[record.fiscal_year] = (actual + record.total_actual_spending,
                                              commitment + record.total_commitment)
    return totals


def financial_utilization(budget: AllocatedBudget, records: tuple[YearlyProjectFinancials, ...],
                          years: range) -> FinancialUtilization:
    """Use the chart period for numerator and allocated approved denominator."""
    yearly = yearly_financial_amounts(records, years)
    with localcontext(prec=60):
        return FinancialUtilization(
            sum((value[0] for value in yearly.values()), Decimal(0)),
            sum((value[1] for value in yearly.values()), Decimal(0)),
            sum((budget.totals.get(year, Decimal(0)) for year in years), Decimal(0)),
        )


def allocated_budget(shares: list[WbsShare], snapshot: BudgetSnapshot | None, year: int) -> AllocatedBudget:
    """Preserve per-share cent rounding and sum exact euros at sufficient precision."""
    with localcontext() as context:
        # Finance amounts have at most 19 digits; percentages and the number of
        # contributions determine sufficient working precision for exact totals.
        context.prec = max(28, 22 + len(str(len(shares))))
        return _allocated_budget(shares, snapshot, year)


def _allocated_budget(shares: list[WbsShare], snapshot: BudgetSnapshot | None, year: int) -> AllocatedBudget:
    """Calculate under the caller's deliberately sized decimal context."""
    amounts = {row.code: row.amounts for row in snapshot.rows} if snapshot else {}
    totals: dict[int, Decimal] = {}
    result, missing, seen = [], set(), set()
    for share in shares:
        key = share.project_id, share.code
        if key in seen:
            continue
        seen.add(key)
        if share.code not in amounts:
            missing.add(share.code)
        values = {y: (amount * share.percentage / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                  for y, amount in amounts.get(share.code, {}).items() if year - 5 <= y <= year + 14}
        for y, amount in values.items():
            totals[y] = totals.get(y, Decimal(0)) + amount
        result.append((share, values))
    return AllocatedBudget(tuple(result), totals, tuple(sorted(missing)))


def matches(project: DashboardProject, filters: dict[str, list[str]], match_all: bool = False,
            exclude: str | None = None) -> bool:
    """AND fields, OR fixed facets, and retain the Gantt flexible Any/All rule."""
    for key, selected in filters.items():
        if key == exclude or not selected:
            continue
        actual = {value.casefold() for value in project['fields'].get(key, [])}
        wanted = {value.casefold() for value in selected}
        if match_all and key not in {'status', 'manager', 'org_manager', 'team', 'service', 'division', 'org_team', 'pool'}:
            if not wanted <= actual:
                return False
        elif not wanted & actual:
            return False
    return True


def quarterly_shortfall(pools: list[PoolCapacityDetail], project_ids: set[int], year: int) -> dict[str, float]:
    """Peak concurrent positive pool shortages on selected-project consuming days."""
    daily: dict[str, Decimal] = defaultdict(Decimal)
    first, last = f'{year-5}-01-01', f'{year+14}-12-31'
    for pool in pools:
        periods = [(row['start_date'], row['end_date']) for row in pool.assignments
                   if row['project_id'] in project_ids and row['fte_assigned'] > 0
                   and row['start_date'] and row['end_date']]
        for day in pool.daily_overassignments:
            if first <= day.date <= last and any(start <= day.date <= end for start, end in periods):
                daily[day.date] += max(Decimal(str(day.excess_fte)), Decimal(0))
    result = {f'{y}-Q{q}': 0.0 for y in range(year-5, year+15) for q in range(1, 5)}
    for day, excess in daily.items():
        value = date.fromisoformat(day)
        quarter = f'{value.year}-Q{(value.month-1)//3+1}'
        result[quarter] = max(result[quarter], float(excess))
    return result


def quarter_bounds(quarter: str, year: int) -> tuple[date, date]:
    """Validate a displayed calendar quarter and return inclusive date bounds."""
    valid = {f'{y}-Q{q}' for y in range(year - 5, year + 15) for q in range(1, 5)}
    if quarter not in valid:
        raise ValueError('Select a quarter in the displayed date range.')
    y, q = int(quarter[:4]), int(quarter[-1])
    start = date(y, 3 * q - 2, 1)
    end = date(y + 1, 1, 1) if q == 4 else date(y, 3 * q + 1, 1)
    return start, end - timedelta(days=1)


def responsible_pools(pools: list[PoolCapacityDetail], project_ids: set[int],
                      start: date, end: date) -> set[int]:
    """Identify relevant pools with a positive shortfall anywhere in the interval."""
    result = set()
    for pool in pools:
        periods = [(row['start_date'], row['end_date']) for row in pool.assignments
                   if row['project_id'] in project_ids and row['fte_assigned'] > 0]
        if any(start.isoformat() <= day.date <= end.isoformat() and day.excess_fte > 0
               and any(first <= day.date <= last for first, last in periods)
               for day in pool.daily_overassignments):
            result.add(pool.pool_id)
    return result


def minimum_quarterly_capacity(base: float | Decimal, calendar: Mapping[str, float | Decimal],
                               quarters: Iterable[str], year: int) -> dict[str, float]:
    """Bucket daily overrides once, preserving baseline days and inclusive quarters."""
    requested = set(quarters)
    counts: dict[str, int] = defaultdict(int)
    minima: dict[str, Decimal] = {}
    for day, value in calendar.items():
        quarter = f'{day[:4]}-Q{(int(day[5:7]) - 1) // 3 + 1}'
        if quarter not in requested:
            continue
        amount = Decimal(str(value))
        counts[quarter] += 1
        minima[quarter] = min(minima.get(quarter, amount), amount)
    result = {}
    normal = Decimal(str(base))
    for quarter in sorted(requested):
        first, last = quarter_bounds(quarter, year)
        minimum = minima.get(quarter, normal)
        if counts[quarter] < (last - first).days + 1:
            minimum = min(minimum, normal)
        result[quarter] = float(minimum)
    return result


def quarterly_capacity(pools: list[PoolCapacityDetail], year: int) -> dict[str, float]:
    """Minimum daily total effective capacity of distinct relevant pools per quarter."""
    unique = {pool.pool_id: pool for pool in pools}.values()
    base = sum(Decimal(str(pool.effective_capacity_fte)) for pool in unique)
    deltas: dict[str, Decimal] = defaultdict(Decimal)
    for pool in unique:
        for day, capacity in pool.capacity_calendar.items():
            deltas[day] += Decimal(str(capacity)) - Decimal(str(pool.effective_capacity_fte))
    quarters = (f'{y}-Q{q}' for y in range(year - 5, year + 15) for q in range(1, 5))
    return minimum_quarterly_capacity(base, {day: base + delta for day, delta in deltas.items()}, quarters, year)
