"""Rebuild derived staffing using global direct employee priority."""

import psycopg


def refresh_direct_priority(connection: psycopg.Connection) -> None:
    """Publish new Python calculations atomically with migration 0056."""
    from app.infrastructure.postgresql.staffing_projection import refresh_staffing
    refresh_staffing(connection)
