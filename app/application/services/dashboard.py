"""Compose filtered project pages, exact approved budgets, and quarterly shortages."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.application.ports.dashboard import DashboardCatalog, DashboardReader
from app.domain.dashboard import AllocatedBudget, DashboardProject, allocated_budget, matches
from app.domain.finance import BudgetVersion


@dataclass(frozen=True)
class DashboardReport:
    """Safe report projection shared by dashboard charts and project details."""

    budget: AllocatedBudget
    approved: BudgetVersion | None
    issue_count: int


class DashboardService:
    """Keep filtering and budget rules separate from rendering and SQL."""

    def __init__(self, reader: DashboardReader, today: Callable[[], date] = date.today) -> None:
        self.reader, self.today = reader, today

    def revision(self) -> tuple:
        """Reauthorize and supply compact business, finance and identity revisions."""
        return (*self.reader.revision(), self.today().isoformat())

    def catalog(self) -> DashboardCatalog:
        """Return only readable project values and their reference labels."""
        return self.reader.catalog()

    def filtered(self, catalog: DashboardCatalog, filters: dict[str, list[str]],
                 match_all: bool = False) -> list[DashboardProject]:
        """Apply the same filter set to the table and every metric."""
        return [project for project in catalog.projects if matches(project, filters, match_all)]

    def choices(self, catalog: DashboardCatalog, filters: dict[str, list[str]], key: str,
                match_all: bool = False) -> list[str]:
        """Facet against other filters, retaining selections only within current access."""
        authorized = {value for project in catalog.projects for value in project['fields'].get(key, [])}
        options = {value for project in catalog.projects if matches(project, filters, match_all, exclude=key)
                   for value in project['fields'].get(key, [])}
        return sorted(options | (set(filters.get(key, [])) & authorized), key=str.casefold)

    def report(self, project_ids: list[int]) -> DashboardReport:
        """Calculate current WBS shares from one consistent approved snapshot."""
        data = self.reader.data(project_ids)
        return DashboardReport(allocated_budget(data.shares, data.approved, self.today().year),
                               data.approved.version if data.approved else None, data.issue_count)

    def shortages(self, project_ids: list[int]) -> dict[str, float]:
        """Return only aggregate quarterly shortfalls for currently readable projects."""
        return self.reader.shortages(project_ids, self.today())

    def issues(self, project_ids: list[int], locale: str) -> list[dict]:
        """Read current active blockers after checking project scope again."""
        return self.reader.issues(project_ids, locale)
