"""Authorized dashboard read projections, independent of database models."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

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


class DashboardReader(Protocol):
    """Batch reads that recheck current authority before every result."""

    def revision(self) -> tuple: ...
    def catalog(self) -> DashboardCatalog: ...
    def data(self, project_ids: list[int]) -> DashboardData: ...
    def shortages(self, project_ids: list[int], today: date) -> dict[str, float]: ...
    def issues(self, project_ids: list[int], locale: str) -> list[dict]: ...
