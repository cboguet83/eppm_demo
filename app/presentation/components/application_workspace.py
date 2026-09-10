"""Dependencies and startup inputs for the Streamlit application shell."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.application.ports.planning import PlanningTotals


@dataclass(frozen=True)
class ApplicationWorkspace:
    """Authorized page renderers and project-scoped planning totals."""

    database_identity: str
    pages: Mapping[str, Callable[[], None]]
    totals: Callable[[], PlanningTotals] | None
