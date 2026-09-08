"""Compatibility export for the shared SQLite connection factory."""

from app.infrastructure.database.connection import get_db

__all__ = ["get_db"]
