"""Compatibility facade for callers of the former portfolio repository."""

from app.main import create_portfolio_service
from app.application.ports.portfolio import PortfolioMetrics
from app.infrastructure.repositories.portfolio import portfolio_revision
from src.repositories.project_errors import legacy_project_errors


class PortfolioRepository:
    """Preserve legacy dictionary results while delegating to portfolio use cases."""

    PAGE_SIZE = 100
    FACET_SIZE = 200

    def __init__(self, db_path: str | None = None) -> None:
        """Compose bounded portfolio queries without planning enrichment."""
        self.db_path = db_path
        self.service = create_portfolio_service(db_path, include_allocations=False)

    def get_metrics(self) -> PortfolioMetrics:
        """Read existing demo budget summaries without loading project rows."""
        with legacy_project_errors():
            return self.service.get_metrics()

    def get_page(self, columns: list[dict], query: dict, offset: int = 0) -> dict:
        """Preserve the legacy bounded page dictionary."""
        with legacy_project_errors():
            return self.service.get_page(columns, query, offset)

    def get_facet(self, columns: list[dict], query: dict, column: str, search: str = '') -> dict:
        """Preserve global column statistics and bounded facet choices."""
        with legacy_project_errors():
            return self.service.get_facet(columns, query, column, search)
