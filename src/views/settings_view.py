"""Compatibility entry point for the injected Settings screen."""

from dataclasses import replace
from typing import Protocol

from app.main import (
    create_settings_workspace,
    create_schema_service,
    create_project_type_service,
    create_tag_service,
    create_resource_pool_service,
    create_pool_capacity_service,
)
from app.presentation.pages.settings import render_settings_view as render_settings


class SettingsSource(Protocol):
    """Historical repository arguments expose their configured database path."""

    db_path: str | None


def render_settings_view(
    org_repo: SettingsSource,
    tag_repo: SettingsSource | None = None,
    project_repo: SettingsSource | None = None,
    milestone_repo: SettingsSource | None = None,
    pool_repo: SettingsSource | None = None,
    schema_repo: SettingsSource | None = None,
) -> None:
    """Retain historical arguments and any per-section database overrides."""
    workspace = create_settings_workspace(org_repo.db_path)
    if tag_repo is not None:
        workspace = replace(workspace, tags=create_tag_service(tag_repo.db_path))
    if pool_repo is not None:
        workspace = replace(
            workspace,
            resources=create_resource_pool_service(pool_repo.db_path),
            capacity=create_pool_capacity_service(pool_repo.db_path),
        )
    if schema_repo is not None:
        workspace = replace(
            workspace,
            schema=create_schema_service(schema_repo.db_path),
            types=create_project_type_service(schema_repo.db_path),
        )
    render_settings(workspace)
