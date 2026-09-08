"""Budget reporting using injected reads and shared decimal rules."""

from dataclasses import dataclass

from app.application.ports.budgets import BudgetReader, ProjectBudget
from app.domain.projects.budgets import (
    BudgetAnalysis,
    PortfolioMetrics,
    analyze_budget,
    summarize_budgets,
)


@dataclass(frozen=True)
class BudgetReportRow:
    """A project's stored amounts and calculated financial health."""

    project: ProjectBudget
    analysis: BudgetAnalysis


@dataclass(frozen=True)
class BudgetReport:
    """Consistent report rows and portfolio totals from the same snapshot."""

    rows: list[BudgetReportRow]
    metrics: PortfolioMetrics


class BudgetService:
    """Build the existing budget analysis without loading project properties."""

    def __init__(self, reader: BudgetReader) -> None:
        """Inject the minimal reporting reader."""
        self._reader = reader

    def get_report(self) -> BudgetReport:
        """Calculate project health and totals from one consistent set of rows."""
        projects = self._reader.read_budgets()
        return BudgetReport(
            [BudgetReportRow(project, analyze_budget(project.amounts)) for project in projects],
            summarize_budgets(project.amounts for project in projects),
        )
