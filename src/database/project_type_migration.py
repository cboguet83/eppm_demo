"""Compatibility exports for database utilities now owned by infrastructure."""

from app.infrastructure.database.project_type_migration import (
    backup_legacy_database,
    migrate_project_types,
)
