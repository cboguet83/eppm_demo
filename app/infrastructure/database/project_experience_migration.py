"""Add contact landlines and localized property aliases without rewriting data."""

import sqlite3


def migrate_project_experience(connection: sqlite3.Connection) -> None:
    """Apply the additive migration within the caller's schema transaction."""
    version = "project-experience-v1"
    if connection.execute(
        "SELECT 1 FROM schema_migration WHERE version=?", (version,)
    ).fetchone():
        return
    columns = {row[1] for row in connection.execute("PRAGMA table_info(employee)")}
    if "landline" not in columns:
        connection.execute("ALTER TABLE employee ADD COLUMN landline TEXT NOT NULL DEFAULT ''")
    connection.execute("""CREATE TABLE schema_parameter_translation (
        param_id TEXT NOT NULL REFERENCES schema_parameters(param_id) ON DELETE CASCADE,
        locale TEXT NOT NULL CHECK(length(trim(locale)) > 0),
        alias TEXT NOT NULL CHECK(length(trim(alias)) > 0),
        PRIMARY KEY(param_id, locale)
    )""")
    connection.execute("INSERT INTO schema_migration(version) VALUES (?)", (version,))
