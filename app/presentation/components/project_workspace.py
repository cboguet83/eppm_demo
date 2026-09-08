"""Injected dependencies shared by the project dialogs and portfolio screen."""

from collections.abc import Callable
from dataclasses import dataclass

from app.application.services.projects import ProjectService
from app.application.services.project_types import ProjectTypeService
from app.application.services.portfolio import PortfolioService


@dataclass(frozen=True)
class ProjectWorkspace:
    """Use cases and lazily called sections assembled by the composition root.

    Collaboration sections remain owned by their existing feature until its
    migration. Callbacks keep those dependencies out of the migrated screen.
    """

    projects: ProjectService
    types: ProjectTypeService
    portfolio: PortfolioService
    render_contacts: Callable[[int], None]
    render_log: Callable[[int], None]
