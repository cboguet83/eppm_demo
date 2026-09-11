"""Exact allocated budgets, organizational facets, and concurrent pool shortages."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
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
    """Calculated cents by project/WBS/year and matching aggregate totals."""

    rows: tuple[tuple[WbsShare, dict[int, int]], ...]
    totals: dict[int, int]
    unmatched: tuple[str, ...]


def allocated_budget(shares: list[WbsShare], snapshot: BudgetSnapshot | None, year: int) -> AllocatedBudget:
    """Round each project/WBS/year share once, then sum those exact cents."""
    amounts = {row.code: row.amounts for row in snapshot.rows} if snapshot else {}
    totals: dict[int, int] = {}
    result, missing, seen = [], set(), set()
    for share in shares:
        key = share.project_id, share.code
        if key in seen:
            continue
        seen.add(key)
        if share.code not in amounts:
            missing.add(share.code)
        values = {y: int((Decimal(cents) * share.percentage / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
                  for y, cents in amounts.get(share.code, {}).items() if year - 5 <= y <= year + 14}
        for y, cents in values.items():
            totals[y] = totals.get(y, 0) + cents
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
        if match_all and key not in {'manager', 'level3', 'level4', 'team'}:
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
