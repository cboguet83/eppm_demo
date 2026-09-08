"""Historical app.py helper exports composed from their migrated owners."""

import pandas as pd

from app.main import (
    SCHEMA_VERSION,
    create_maintenance_service,
    create_schema_service,
    parse_cli_args,
)
from app.presentation.components.budget_frames import (
    calculate_frame_metrics as calculate_portfolio_metrics,
)
from app.presentation.components.planning_catalog import flatten_dynamic_attributes
from app.presentation.components.schema_frames import groups_frame, parameters_frame, options_frame
from app.presentation.startup import bootstrap_database as cached_startup
from app.shared.config import config

DB_NAME = config.db_path


def bootstrap_database(schema_version: str = SCHEMA_VERSION) -> bool:
    """Retain the former startup helper with explicit source and options keys."""
    from pathlib import Path

    cli_force, cli_projects = parse_cli_args()
    identity = str(Path(config.db_path).resolve())
    return cached_startup(
        database_identity=identity,
        schema_version=schema_version,
        force=config.force_reseed or cli_force,
        projects=cli_projects if cli_projects > 0 else config.seed_projects_count,
        _service=create_maintenance_service(identity),
    )


bootstrap_database.clear = cached_startup.clear


def generate_param_id(db_path: str | None = None) -> str:
    """Retain the historical schema-property ID preview."""
    return create_schema_service(db_path).generate_param_id()


def get_next_available_group_order(db_path: str | None = None) -> int:
    """Retain the historical schema-group order preview."""
    return create_schema_service(db_path).get_next_available_group_order()


def load_full_schema(
    db_path: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Retain the historical tuple of schema group, parameter, and option frames."""
    service = create_schema_service(db_path)
    return (
        groups_frame(service.get_all_groups()),
        parameters_frame(service.get_all_parameters()),
        options_frame(service.get_all_options()),
    )


def _get_database_seed_counts(db_path: str) -> dict[str, int]:
    """Keep the historical post-seed count projection."""
    counts = create_maintenance_service(db_path).counts()
    return {
        key: counts[key]
        for key in ("projects", "tasks", "dependencies", "project_types", "property_values")
    }


def _get_planning_totals(db_path: str) -> dict[str, int]:
    """Keep the historical planning sidebar count projection."""
    counts = create_maintenance_service(db_path).counts()
    return {key: counts[key] for key in ("projects", "tasks", "dependencies", "pools")}
