"""Dependencies and startup inputs for the Streamlit application shell."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.application.services.maintenance import MaintenanceService


@dataclass(frozen=True)
class ApplicationWorkspace:
    """Application services, page renderers, and explicitly supplied startup options."""

    database_identity: str
    schema_version: str
    force_reseed: bool
    seed_projects: int
    maintenance: MaintenanceService
    pages: Mapping[str, Callable[[], None]]
