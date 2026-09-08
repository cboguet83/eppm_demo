"""Compatibility exports for database utilities now owned by infrastructure."""

from app.infrastructure.database.demo_catalog import (
    DEMO_TYPES,
    SCOPE_DEFAULTS,
    install_type_catalog,
    sample_values,
    seed_sample_projects,
)
