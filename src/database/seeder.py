"""Compatibility exports for database utilities now owned by infrastructure."""

from app.infrastructure.database.seeder import (
    DEFAULT_SCHEMA_GROUPS,
    DEFAULT_SCHEMA_PARAMETERS,
    DEFAULT_STATUS_OPTIONS,
    DEFAULT_PHASE_OPTIONS,
    DEFAULT_LINE_OPTIONS,
    DEFAULT_COMPLEXITY_OPTIONS,
    DEFAULT_CATEGORY_OPTIONS,
    DEFAULT_CATEGORY_TAGS,
    DEFAULT_STRATEGIC_PRIORITY_OPTIONS,
    DEFAULT_STATION_OPTIONS,
    DEFAULT_PARAM_OPTIONS,
    seed_default_data_if_empty,
    _seed_default_data,
    seed_database_data,
)


def main() -> None:
    """Delegate the historical module command to the migrated CLI boundary."""
    from scripts.seed_defaults import main as seed_main

    seed_main()


if __name__ == "__main__":
    main()
