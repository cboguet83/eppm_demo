"""Authorized, atomic version creation and calendar-aware finance exchange."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import date

from app.application.ports.finance import FinanceGateway, FinanceStore
from app.domain.finance import (
    BudgetRow, BudgetSnapshot, BudgetVersion, FinanceError, export_csv, normalize_rows,
    parse_csv, preserve_history, version_name,
)


@dataclass(frozen=True)
class FinanceView:
    """A consistent metadata/catalog/snapshot projection for one page render."""

    versions: tuple[BudgetVersion, ...]
    selected: BudgetSnapshot | None
    catalog: dict[str, str]
    can_edit: bool
    year: int


class FinanceService:
    """Maintain one shared plan without changing existing snapshots or projects."""

    def __init__(self, gateway: FinanceGateway, today: Callable[[], date] = date.today) -> None:
        self.gateway, self.today = gateway, today

    def view(self, snapshot_id: int | None = None) -> FinanceView:
        """Read all visible metadata and one selected snapshot under current access."""
        def operation(store: FinanceStore) -> FinanceView:
            versions = store.versions()
            selected_id = snapshot_id if snapshot_id is not None else versions[0].id if versions else None
            selected = store.snapshot(selected_id) if selected_id is not None else None
            return FinanceView(versions, selected, store.catalog(), store.can_edit(), self.today().year)
        return self.gateway.run(operation)

    def validate_import(self, content: object, year: int) -> tuple[BudgetRow, ...]:
        """Validate a complete upload without changing the draft or database."""
        def operation(store: FinanceStore) -> tuple[BudgetRow, ...]:
            self._year(year)
            return parse_csv(content, year)
        return self.gateway.run(operation, write=True)

    def save(self, raw_rows: object, *, base_id: int | None, name: str,
             status: str, year: int) -> int:
        """Append a numbered snapshot with explicit status, preserving source history."""
        submitted = deepcopy(raw_rows)
        def operation(store: FinanceStore) -> int:
            self._year(year)
            edited = normalize_rows(submitted, year)
            base = store.snapshot(base_id) if base_id is not None else None
            label = version_name(name)
            if not isinstance(status, str) or status not in {"Draft", "Proposed", "Approved", "Canceled"}:
                raise FinanceError("status")
            latest = store.latest()
            number = latest.number + 1 if latest else 1
            rows = preserve_history(base.rows if base else (), edited, year)
            return store.insert(rows, number=number, name=label, status=status, base_id=base_id)
        return self.gateway.run(operation, write=True)

    def cancel(self, snapshot_id: int) -> None:
        """Cancel any saved version without changing its number or budget contents."""
        def operation(store: FinanceStore) -> None:
            base = store.snapshot(snapshot_id)
            if base.version.status == "Canceled":
                raise FinanceError("canceled")
            store.cancel(snapshot_id)
        self.gateway.run(operation, write=True)

    def export(self, snapshot_id: int) -> str:
        """Generate an export after current active-user authorization on every call."""
        return self.gateway.run(lambda store: export_csv(store.snapshot(snapshot_id).rows, store.catalog(), self.today().year))

    def _year(self, year: int) -> None:
        if type(year) is not int or year != self.today().year:
            raise FinanceError("year_changed")
