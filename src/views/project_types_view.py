"""Compatibility entry points for the migrated project-type screen."""

import pandas as pd

from app.presentation.pages import project_types
from src.repositories.project_type_repo import ProjectTypeRepository


def applicability_input(
    repo: ProjectTypeRepository, key: str, param_id: str | None = None,
) -> tuple[bool, list[int]]:
    """Adapt a legacy repository caller to the application-backed control."""
    return project_types.applicability_input(repo.service, key, param_id)


def render_project_types(repo: ProjectTypeRepository, options: pd.DataFrame) -> None:
    """Adapt a legacy repository caller to the migrated page."""
    project_types.render_project_types(repo.service, options)
