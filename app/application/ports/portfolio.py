"""Plain-data contracts for bounded portfolio queries and editor reference data."""

from dataclasses import dataclass
from typing import NotRequired, Protocol, TypedDict

from app.domain.projects.project_types import PropertyDefinition

Scalar = str | int | float | bool | None
PortfolioRow = dict[str, Scalar]


class PortfolioColumn(TypedDict):
    """Server-defined column metadata; SQL expressions never come from clients."""

    key: str
    format: str
    label: NotRequired[str]
    param_id: NotRequired[str]


class PortfolioPage(TypedDict):
    """One bounded page and the count of all matching projects."""

    rows: list[PortfolioRow]
    total: int
    offset: int
    page_size: int


class FacetValue(TypedDict):
    """A distinct filtered value and its global frequency."""

    value: Scalar
    count: int


class PortfolioFacet(TypedDict):
    """Bounded choices with statistics over the complete filtered result."""

    column: str
    search: str
    stats: list[list[Scalar]]
    format: str
    values: list[FacetValue]
    has_more: bool


@dataclass(frozen=True)
class PortfolioMetrics:
    """Legacy demo budget totals in euros; not an authoritative finance ledger."""

    total_projects: int = 0
    total_planned: float = 0.0
    total_actual: float = 0.0
    variance: float = 0.0
    burn_rate: float = 0.0


class PropertyGroup(TypedDict):
    """Display grouping for project properties."""

    id: int
    group_name: str
    display_order: int


class PropertyOption(TypedDict):
    """An allowed option in configured display order."""

    id: int
    param_id: str
    option_value: str
    display_order: int


@dataclass(frozen=True)
class ProjectCatalog:
    """Reference data needed by project dialogs and portfolio columns."""

    groups: list[PropertyGroup]
    parameters: list[PropertyDefinition]
    options: list[PropertyOption]
    managers: dict[int, str]


class PortfolioReader(Protocol):
    """Persistence reads; query dictionaries are validated at the use-case boundary."""

    def revision(self) -> tuple: ...
    def get_metrics(self) -> PortfolioMetrics: ...
    def get_page(self, columns: list[PortfolioColumn], query: dict, offset: int = 0) -> PortfolioPage: ...
    def get_facet(self, columns: list[PortfolioColumn], query: dict, column: str, search: str = "") -> PortfolioFacet: ...
    def get_detail(self, project_id: int) -> PortfolioRow | None: ...
    def get_catalog(self, *, include_managers: bool = True) -> ProjectCatalog: ...


class AllocationReader(Protocol):
    """Read overload flags only for the projects in the requested page."""

    def __call__(self, project_ids: list[int]) -> set[int]: ...
