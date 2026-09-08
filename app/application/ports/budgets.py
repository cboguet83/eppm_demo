"""Minimal budget reporting projections, independent of project persistence."""

from dataclasses import dataclass
from typing import Protocol

from app.domain.projects.budgets import BudgetAmounts


@dataclass(frozen=True)
class ProjectBudget:
    """Project identity and the two monetary values needed by budget reporting."""

    id: int
    name: str
    status: str
    amounts: BudgetAmounts


class BudgetReader(Protocol):
    """Read the budget report's minimal rows from one source snapshot."""

    def read_budgets(self) -> list[ProjectBudget]: ...
