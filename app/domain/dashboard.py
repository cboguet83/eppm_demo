"""Exact allocated budgets, organizational facets, and concurrent pool shortages."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import TypedDict

from app.domain.finance import BudgetSnapshot
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


def ancestor(function_id: int | None, level: int, functions: dict[int, dict]) -> int | None:
    """Resolve a primary ancestor or senior self with cycle and depth guards."""
    node = functions.get(function_id)
    if not node:
        return None
    if node['hierarchy_level'] <= level:
        return function_id
    seen = set()
    for _ in range(100):
        if function_id in seen or function_id not in functions:
            return None
        seen.add(function_id)
        node = functions[function_id]
        if node['hierarchy_level'] == level:
            return function_id
        if node['hierarchy_level'] < level:
            return None
        function_id = node['manager_function_id']
    return None


def matches(project: DashboardProject, filters: dict[str, list[str]], match_all: bool = False,
            exclude: str | None = None) -> bool:
    """AND fields, OR fixed facets, and retain the Gantt flexible Any/All rule."""
    for key, selected in filters.items():
        if key == exclude or not selected:
            continue
        actual = {value.casefold() for value in project['fields'].get(key, [])}
        wanted = {value.casefold() for value in selected}
        if match_all and key not in {'status', 'manager', 'level3', 'level4', 'team', 'pool'}:
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


def quarterly_capacity(pools: list[PoolCapacityDetail], year: int) -> dict[str, float]:
    """Peak daily total effective capacity of the selected, distinct relevant pools."""
    unique = {pool.pool_id: pool for pool in pools}.values()
    base = sum(Decimal(str(pool.effective_capacity_fte)) for pool in unique)
    deltas: dict[str, Decimal] = defaultdict(Decimal)
    for pool in unique:
        for day, capacity in pool.capacity_calendar.items():
            deltas[day] += Decimal(str(capacity)) - Decimal(str(pool.effective_capacity_fte))
    result = {}
    for y in range(year - 5, year + 15):
        for q in range(1, 5):
            quarter = f'{y}-Q{q}'
            start, end = quarter_bounds(quarter, year)
            changes = [value for day, value in deltas.items() if start.isoformat() <= day <= end.isoformat()]
            # Do not invent a baseline day when every day has a calendar override.
            if len(changes) < (end - start).days + 1:
                changes.append(Decimal(0))
            result[quarter] = float(base + max(changes, default=Decimal(0)))
    return result
