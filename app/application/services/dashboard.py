"""Compose filtered project pages, exact approved budgets, and quarterly shortages."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.application.ports.dashboard import DashboardCatalog, DashboardReader, ResourceBreakdown
from app.domain.dashboard import AllocatedBudget, DashboardProject, allocated_budget, matches
from app.domain.finance import BudgetVersion
from app.domain.projects.project import PROJECT_STATUSES


def _resource_statuses(statuses: list[str] | None) -> list[str] | None:
    """Normalize an empty status selection to all statuses, as in planning."""
    if statuses and set(statuses) - set(PROJECT_STATUSES):
        raise ValueError('Select valid project statuses.')
    return sorted(set(statuses)) if statuses else None


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

    def report(self, project_ids: list[int], status: str = 'Approved') -> DashboardReport:
        """Calculate WBS shares from the latest snapshot with the requested status."""
        data = self.reader.data(project_ids, status)
        return DashboardReport(allocated_budget(data.shares, data.approved, self.today().year),
                               data.approved.version if data.approved else None, data.issue_count)

    def shortages(self, project_ids: list[int]) -> dict[str, float]:
        """Return only aggregate quarterly shortfalls for currently readable projects."""
        return self.reader.shortages(project_ids, self.today())

    def issues(self, project_ids: list[int], locale: str) -> list[dict]:
        """Read current active blockers after checking project scope again."""
        return self.reader.issues(project_ids, locale)

    def resources(self, project_ids: list[int]) -> dict[str, dict[str, float]]:
        """Read both quarterly resource series in one authorized snapshot."""
        return self.reader.resources(project_ids, self.today())

    def resource_breakdown(self, project_ids: list[int], pool_id: int | None = None,
                           *, statuses: list[str] | None = None, pool_ids: list[int] | None = None) -> ResourceBreakdown:
        """Read per-pool chart stacks on the same authorized snapshot as totals."""
        if pool_id is not None and (type(pool_id) is not int or pool_id <= 0):
            raise ValueError('Select a valid resource pool.')
        if pool_ids is not None and any(type(value) is not int or value <= 0 for value in pool_ids):
            raise ValueError('Select valid resource pools.')
        return self.reader.resource_breakdown(project_ids, self.today(), pool_id,
                                              statuses=_resource_statuses(statuses), pool_ids=pool_ids)

    def consuming_projects(self, project_ids: list[int], quarter: str,
                           pool_id: int | None = None, metric: str = 'overallocation',
                           *, statuses: list[str] | None = None) -> list[int]:
        """Reauthorize a chart drill-through before returning planning project IDs."""
        return self.reader.consuming_projects(project_ids, quarter, self.today(), pool_id, metric,
                                              statuses=_resource_statuses(statuses))
