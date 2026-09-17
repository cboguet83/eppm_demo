"""Initialize the private staffing projection after backfilling function links."""

import psycopg


def initialize_staffing(connection: psycopg.Connection) -> None:
    """Publish initial Python-calculated staffing inside migration 0055."""
    from app.infrastructure.postgresql.staffing_projection import refresh_staffing
    refresh_staffing(connection)
