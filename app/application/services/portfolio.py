"""Bounded portfolio browsing, filtering, and editor reference queries."""

from hashlib import sha256

from app.application.exceptions import PortfolioRevisionChanged
from app.application.ports.portfolio import (
    AllocationReader, PortfolioColumn, PortfolioFacet, PortfolioMetrics,
    PortfolioPage, PortfolioReader, PortfolioRow, ProjectCatalog,
)


def portfolio_revision_token(revision: tuple) -> str:
    """Digest a display revision without exposing session or database identifiers."""
    return sha256(repr(revision).encode("utf-8")).hexdigest()


def normalize_query(query: dict) -> dict:
    """Normalize dynamic component input before it reaches SQL construction.

    The wire format is a JSON dictionary. Unknown columns are subsequently
    ignored against server-supplied metadata by the persistence adapter.
    """
    filters = query.get("filters")
    sort = query.get("sort")
    templates = query.get("templates")
    return {
        "search": str(query.get("search") or "").strip(),
        "templates": [v for v in templates if isinstance(v, str)] if isinstance(templates, list) else [],
        "filters": filters if isinstance(filters, dict) else {},
        "sort": {key: value for key, value in sort.items() if isinstance(value, str)}
        if isinstance(sort, dict) else {},
    }


class PortfolioService:
    """Coordinate bounded reads and optional planning-capacity enrichment."""

    def __init__(self, reader: PortfolioReader, allocations: AllocationReader | None = None) -> None:
        """Inject query storage and the separately owned planning-capacity reader."""
        self._reader = reader
        self._allocations = allocations

    def revision(self) -> tuple:
        """Return a source-specific cache token, including the database identity."""
        return self._reader.revision()

    def get_metrics(self) -> PortfolioMetrics:
        """Read aggregate totals without loading individual project records."""
        return self._reader.get_metrics()

    def get_page(
        self, columns: list[PortfolioColumn], query: dict, offset: int = 0, *,
        include_allocations: bool = True,
    ) -> PortfolioPage:
        """Read one page, optionally deferring capacity badges until rows are visible."""
        try:
            offset = max(0, int(offset))
        except (TypeError, ValueError, OverflowError):
            offset = 0
        page = self._reader.get_page(columns, normalize_query(query), offset)
        if include_allocations and self._allocations is not None:
            overloaded = self._allocations([int(row["project_id"]) for row in page["rows"]])
            for row in page["rows"]:
                row["is_overallocated"] = row["project_id"] in overloaded
        return page

    def get_allocation_badges(self, project_ids: list[int], revision: str) -> dict[str, object]:
        """Read capacity warnings and reject results spanning a data or access change."""
        current = self.revision()
        if portfolio_revision_token(current) != revision:
            raise PortfolioRevisionChanged()
        overloaded = self._allocations(project_ids) if self._allocations is not None else set()
        if self.revision() != current:
            raise PortfolioRevisionChanged()
        return {"project_ids": project_ids, "overallocated": sorted(overloaded)}

    def get_facet(
        self, columns: list[PortfolioColumn], query: dict, column: str, search: str = "",
    ) -> PortfolioFacet:
        """Read globally computed statistics and at most 200 distinct choices."""
        return self._reader.get_facet(columns, normalize_query(query), column, search)

    def get_detail(self, project_id: int) -> PortfolioRow | None:
        """Read one selected project's summary independently of grid filters."""
        return self._reader.get_detail(project_id)

    def get_catalog(self, *, include_managers: bool = True) -> ProjectCatalog:
        """Read schema and manager options used by project presentation."""
        return self._reader.get_catalog(include_managers=include_managers)
