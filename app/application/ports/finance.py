"""Transaction and snapshot contracts for the shared finance plan."""

from contextlib import AbstractContextManager
from typing import Protocol

from app.domain.finance import BudgetRow, BudgetSnapshot, BudgetVersion


class FinanceStore(Protocol):
    """An already authorized, transaction-bound finance data source."""

    def versions(self) -> tuple[BudgetVersion, ...]: ...
    def snapshot(self, snapshot_id: int) -> BudgetSnapshot: ...
    def catalog(self) -> dict[str, str]: ...
    def can_edit(self) -> bool: ...
    def latest(self, major: int | None = None) -> BudgetVersion | None: ...
    def insert(self, rows: tuple[BudgetRow, ...], *, major: int, minor: int,
               name: str, status: str, base_id: int | None) -> int: ...


class FinanceGateway(Protocol):
    """Authorize reads/writes and provide atomic storage operations."""

    def transaction(self, *, write: bool = False) -> AbstractContextManager[FinanceStore]: ...
