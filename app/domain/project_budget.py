"""Unified project budget cells and exact user-entered euro corrections."""

from dataclasses import dataclass
from decimal import Decimal
import re

from app.domain.finance import MAX_AMOUNT

ROW_LABELS = {'Approved': 'Budget - Approved', 'Proposed': 'Budget-Proposed',
              'LIVE_BUDGET': 'Budget-Live', 'ACTUAL': 'Actual', 'COMMITMENT': 'Commitment'}
EDITABLE_KINDS = frozenset({'LIVE_BUDGET', 'ACTUAL', 'COMMITMENT'})


@dataclass(frozen=True)
class ProjectBudgetRow:
    """One WBS/nature row with exact yearly amounts and its source version."""

    wbs: str
    kind: str
    version: str
    amounts: dict[int, Decimal]


@dataclass(frozen=True)
class ProjectBudgetView:
    """Consistent table snapshot and optimistic concurrency token."""

    project_id: int
    rows: tuple[ProjectBudgetRow, ...]
    revision: str
    can_edit: bool


@dataclass(frozen=True)
class ProjectBudgetEdit:
    """A target cell amount; null clears a live budget or zeroes an accounting total."""

    wbs: str
    kind: str
    year: int
    amount: Decimal | None


def parse_budget_edits(payload: object, view: ProjectBudgetView, years: range) -> tuple[ProjectBudgetEdit, ...]:
    """Validate browser cells against authoritative editable rows and fiscal years."""
    if not isinstance(payload, list) or not 1 <= len(payload) <= 10000:
        raise ValueError('Provide between 1 and 10,000 changed budget cells.')
    available = {(row.wbs, row.kind) for row in view.rows if row.kind in EDITABLE_KINDS}
    result, seen = [], set()
    for cell in payload:
        if not isinstance(cell, dict) or set(cell) != {'wbs', 'kind', 'year', 'amount'}:
            raise ValueError('Invalid budget cell.')
        wbs, kind, year, raw = (cell[key] for key in ('wbs', 'kind', 'year', 'amount'))
        if not isinstance(wbs, str) or not isinstance(kind, str) or (wbs, kind) not in available:
            raise ValueError('Only Budget-Live, Actual and Commitment cells for this project can be changed.')
        if type(year) is not int or year not in years:
            raise ValueError('Select a fiscal year displayed in the budget table.')
        key = (wbs, kind, year)
        if key in seen:
            raise ValueError('The same budget cell was submitted more than once.')
        seen.add(key)
        if not isinstance(raw, str) or len(raw) > 24:
            raise ValueError('Enter an amount with at most two decimal places.')
        text = raw.strip().replace(',', '.')
        if text and not re.fullmatch(r'-?\d+(?:\.\d{1,2})?', text):
            raise ValueError('Enter an amount with at most two decimal places.')
        amount = Decimal(text) if text else None
        if amount is not None and (amount.copy_abs() > MAX_AMOUNT or (kind == 'LIVE_BUDGET' and amount < 0)):
            raise ValueError('Live budget amounts must be nonnegative; all amounts must fit the supported monetary range.')
        result.append(ProjectBudgetEdit(wbs, kind, year, amount))
    return tuple(result)
