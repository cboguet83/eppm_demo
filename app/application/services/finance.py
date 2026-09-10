"""Authorized, atomic version creation and calendar-aware finance exchange."""

from collections.abc import Callable
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
        with self.gateway.transaction() as store:
            versions = store.versions()
            selected_id = snapshot_id if snapshot_id is not None else versions[0].id if versions else None
            selected = store.snapshot(selected_id) if selected_id is not None else None
            return FinanceView(versions, selected, store.catalog(), store.can_edit(), self.today().year)

    def validate_import(self, content: object, year: int) -> tuple[BudgetRow, ...]:
        """Validate a complete upload without changing the draft or database."""
        with self.gateway.transaction(write=True):
            self._year(year)
            return parse_csv(content, year)

    def save(self, raw_rows: object, *, base_id: int | None, mode: str,
             name: str = "", year: int) -> int:
        """Create a Draft snapshot, numbering and preserving history atomically."""
        with self.gateway.transaction(write=True) as store:
            self._year(year)
            edited = normalize_rows(raw_rows, year)
            base = store.snapshot(base_id) if base_id is not None else None
            if mode == "revision" and base is not None:
                self._latest(store, base)
                major, minor, label = base.version.major, base.version.minor + 1, base.version.name
            elif mode == "major":
                label = version_name(name)
                latest = store.latest()
                if base is None and latest is not None:
                    raise FinanceError("stale")
                major, minor = (latest.major + 1 if latest else 1), 0
            else:
                raise FinanceError("mode")
            rows = preserve_history(base.rows if base else (), edited, year)
            return store.insert(rows, major=major, minor=minor, name=label, status="Draft", base_id=base_id)

    def change_status(self, snapshot_id: int, status: str) -> int:
        """Append a Proposed/Approved revision while preserving the original status."""
        with self.gateway.transaction(write=True) as store:
            base = store.snapshot(snapshot_id)
            self._latest(store, base)
            if not isinstance(status, str) or status not in {"Proposed", "Approved"} or status == base.version.status:
                raise FinanceError("status")
            return store.insert(base.rows, major=base.version.major, minor=base.version.minor + 1,
                                name=base.version.name, status=status, base_id=base.version.id)

    def export(self, snapshot_id: int) -> str:
        """Generate an export after current active-user authorization on every call."""
        with self.gateway.transaction() as store:
            return export_csv(store.snapshot(snapshot_id).rows, store.catalog(), self.today().year)

    def _year(self, year: int) -> None:
        if type(year) is not int or year != self.today().year:
            raise FinanceError("year_changed")

    @staticmethod
    def _latest(store: FinanceStore, base: BudgetSnapshot) -> None:
        latest = store.latest(base.version.major)
        if latest is None or latest.id != base.version.id:
            raise FinanceError("stale")
