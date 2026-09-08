"""Compatibility entry point for the injected budget screen."""

from typing import Protocol

from app.main import create_budget_service
from app.presentation.pages.budgets import render_budget_tracking as render_budget


class BudgetSource(Protocol):
    """Historical callers provide their configured database path."""

    db_path: str | None


def render_budget_tracking(project_repo: BudgetSource) -> None:
    """Compose the budget service for the historical repository argument."""
    render_budget(create_budget_service(project_repo.db_path))
