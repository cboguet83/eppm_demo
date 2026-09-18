"""Transaction-bound persistence contracts for project financial records."""

from collections.abc import Callable, Collection
from decimal import Decimal
from typing import Protocol

from app.domain.financial_transactions import (
    FinancialTransaction, FinancialTransactionInput, YearlyProjectFinancials,
)


class FinancialTransactionStore(Protocol):
    """Authorized records read and written inside one database transaction."""

    def get(self, project_id: int, transaction_id: int) -> FinancialTransaction | None: ...
    def list(self, project_id: int, fiscal_year: int | None) -> tuple[FinancialTransaction, ...]: ...
    def create(self, value: FinancialTransactionInput, amount_base_currency: Decimal) -> int: ...
    def update(self, transaction_id: int, value: FinancialTransactionInput, amount_base_currency: Decimal) -> bool: ...
    def delete(self, project_id: int, transaction_id: int) -> bool: ...
    def require_source(self, transaction_id: int) -> None: ...
    def yearly_totals(self, project_ids: Collection[int] | None) -> tuple[YearlyProjectFinancials, ...]: ...


class FinancialTransactionGateway(Protocol):
    """Provide current project authorization and atomic/replayable operations."""

    def run[Result](self, operation: Callable[[FinancialTransactionStore], Result], *,
                    write: bool = False, project_ids: Collection[int] | None = None) -> Result: ...
