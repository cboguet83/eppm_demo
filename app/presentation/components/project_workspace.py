"""Injected dependencies shared by the project dialogs and portfolio screen."""

from collections.abc import Callable
from dataclasses import dataclass

from app.application.services.projects import ProjectService
from app.application.services.project_types import ProjectTypeService
from app.application.services.portfolio import PortfolioService
from app.application.services.schema import SchemaService


@dataclass(frozen=True)
class ProjectWorkspace:
    """Use cases and lazily called sections assembled by the composition root.

    Collaboration callbacks retain lazy rendering and receive their application
    service from the composition root.
    """

    projects: ProjectService
    types: ProjectTypeService
    portfolio: PortfolioService
    render_contacts: Callable[[int], None]
    render_log: Callable[[int], None]
    schema: SchemaService
    render_links: Callable[[int], None] | None = None
