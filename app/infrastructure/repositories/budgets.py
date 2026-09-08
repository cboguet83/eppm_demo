"""Minimal reads of the existing SQLite budget fields."""

from app.application.ports.budgets import ProjectBudget
from app.domain.projects.budgets import (
    BudgetAmounts,
    PortfolioMetrics,
    euro_amount,
    summarize_budgets,
)
from app.infrastructure.database.project_transactions import project_connection


def read_budget_totals(db_path: str | None) -> PortfolioMetrics:
    """Stream only the two amount columns into decimal aggregation."""
    with project_connection(db_path) as connection:
        rows = connection.execute("SELECT planned_budget,actual_budget FROM project")
        return summarize_budgets(
            BudgetAmounts(euro_amount(planned), euro_amount(actual)) for planned, actual in rows
        )


class SqliteBudgetReader:
    """Read budget report fields without hydrating unrelated custom properties."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain the database path without opening a connection."""
        self.db_path = db_path

    def read_budgets(self) -> list[ProjectBudget]:
        """Read one ordered snapshot and convert stored numbers at the boundary."""
        with project_connection(self.db_path) as connection:
            rows = connection.execute(
                "SELECT id,name,status,planned_budget,actual_budget FROM project ORDER BY id"
            )
            return [
                ProjectBudget(
                    project_id,
                    name,
                    status,
                    BudgetAmounts(euro_amount(planned), euro_amount(actual)),
                )
                for project_id, name, status, planned, actual in rows
            ]
