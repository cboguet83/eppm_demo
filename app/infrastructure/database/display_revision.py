"""Transactional business revisions for portfolio and planning display caches."""

import sqlite3
from uuid import uuid4

from app.application.exceptions import ProjectStorageError


# Explicit source tables: derived caches and authentication/session housekeeping
# must not invalidate business displays. Permissions have their own revision.
DISPLAY_SOURCE_TABLES = frozenset({
    "wbs", "project_wbs",
    "employee", "employee_calendar_exception", "function", "function_type",
    "project", "project_contact", "project_event_type", "project_event_type_translation",
    "project_link", "project_log_event", "project_property_value", "project_property_value_item",
    "project_role", "project_role_translation", "project_tag", "project_task", "project_type",
    "project_type_property", "project_type_property_default", "project_type_property_default_item",
    "project_type_property_rule", "resource_pool", "resource_pool_assignment",
    "resource_pool_group", "resource_pool_group_member", "resource_pool_mapping",
    "resource_pool_tag", "schema_groups", "schema_param_options", "schema_parameter_translation",
    "schema_parameters", "tag_dictionnary", "tag_group", "task_dependencies", "task_tag",
    "team", "team_function",
})


def install_display_revision(connection: sqlite3.Connection) -> None:
    """Install idempotent invalidation triggers in the schema upgrade transaction.

    Existing business records and permissions remain unchanged. Each source write
    increments the revision in its own transaction, including rollback semantics.
    """
    connection.execute("""CREATE TABLE IF NOT EXISTS display_revision (
        id INTEGER PRIMARY KEY CHECK(id=1), epoch TEXT NOT NULL, revision INTEGER NOT NULL)""")
    connection.execute("INSERT OR IGNORE INTO display_revision VALUES(1,?,0)", (uuid4().hex,))
    for table in sorted(DISPLAY_SOURCE_TABLES):
        for operation in ("INSERT", "UPDATE", "DELETE"):
            connection.execute(f"""CREATE TRIGGER IF NOT EXISTS display_{table}_{operation.lower()}
                AFTER {operation} ON {table}
                BEGIN UPDATE display_revision SET revision=revision+1 WHERE id=1; END""")


def read_display_revision(connection: sqlite3.Connection) -> tuple[str, int, int]:
    """Read business and security versions from the caller's current snapshot."""
    row = connection.execute("""SELECT d.epoch,d.revision,s.revision
        FROM display_revision d CROSS JOIN app_security_state s WHERE d.id=1 AND s.id=1""").fetchone()
    if row is None:
        raise ProjectStorageError("The display revision is unavailable. Run the database migration command.")
    return str(row[0]), int(row[1]), int(row[2])
