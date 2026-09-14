"""Authorized dashboard read projections, independent of database models."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol, TypedDict

from app.domain.dashboard import DashboardProject, WbsShare
from app.domain.finance import BudgetSnapshot


@dataclass(frozen=True)
class DashboardCatalog:
    """Dynamic fields and organization labels for authorized projects only."""

    projects: list[DashboardProject]
    labels: dict[str, dict[str, str]]
    parameters: list[dict]


@dataclass(frozen=True)
class DashboardData:
    """Authorized budget shares and issue count with the latest approved plan."""

    shares: list[WbsShare]
    approved: BudgetSnapshot | None
    issue_count: int


class PoolResourceSeries(TypedDict):
    """One relevant pool's contribution on each metric's concurrent peak day."""

    pool_id: int
    name: str
    allocation: dict[str, float]
    overallocation: dict[str, float]
    available: dict[str, float]


class ResourceBreakdown(TypedDict):
    """Safe aggregate metrics and pool labels, without hidden project records."""

    allocation: dict[str, float]
    overallocation: dict[str, float]
    capacity: dict[str, float]
    pools: list[PoolResourceSeries]
    peak_days: dict[str, dict[str, str | None]]


class DashboardReader(Protocol):
    """Batch reads that recheck current authority before every result."""

    def revision(self) -> tuple: ...
    def catalog(self) -> DashboardCatalog: ...
    def data(self, project_ids: list[int], status: str = 'Approved') -> DashboardData: ...
    def shortages(self, project_ids: list[int], today: date) -> dict[str, float]: ...
    def resources(self, project_ids: list[int], today: date) -> dict[str, dict[str, float]]: ...
    def resource_breakdown(self, project_ids: list[int], today: date) -> ResourceBreakdown: ...
    def consuming_projects(self, project_ids: list[int], quarter: str, today: date,
                           pool_id: int | None = None, metric: str = 'overallocation') -> list[int]: ...
    def issues(self, project_ids: list[int], locale: str) -> list[dict]: ...
