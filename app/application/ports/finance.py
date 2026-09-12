"""Transaction and snapshot contracts for the shared finance plan."""

from collections.abc import Callable
from typing import Protocol

from app.domain.finance import BudgetRow, BudgetSnapshot, BudgetVersion


class FinanceStore(Protocol):
    """An already authorized, transaction-bound finance data source."""

    def versions(self) -> tuple[BudgetVersion, ...]: ...
    def snapshot(self, snapshot_id: int) -> BudgetSnapshot: ...
    def catalog(self) -> dict[str, str]: ...
    def can_edit(self) -> bool: ...
    def latest(self) -> BudgetVersion | None: ...
    def cancel(self, snapshot_id: int) -> None: ...
    def insert(self, rows: tuple[BudgetRow, ...], *, number: int,
               name: str, status: str, base_id: int | None) -> int: ...


class FinanceGateway(Protocol):
    """Authorize reads/writes and provide atomic storage operations."""

    def run[Result](self, operation: Callable[[FinanceStore], Result], *, write: bool = False) -> Result:
        """Authorize and replay complete finance use cases after a definite rollback."""
        ...
