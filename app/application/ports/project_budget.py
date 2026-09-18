"""Atomic project budget views, live amounts and accounting adjustments."""

from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from app.domain.project_budget import ProjectBudgetView
from app.domain.financial_transactions import FinancialTransactionInput


class ProjectBudgetStore(Protocol):
    """A project-scoped budget source in one authorized transaction."""

    def view(self) -> ProjectBudgetView: ...
    def set_live_budget(self, wbs: str, year: int, amount: Decimal | None) -> None: ...
    def create_adjustment(self, value: FinancialTransactionInput) -> None: ...


class ProjectBudgetGateway(Protocol):
    """Reauthorize the complete read or save under the same database snapshot."""

    def run[Result](self, project_id: int, operation: Callable[[ProjectBudgetStore], Result], *, write: bool = False) -> Result: ...
