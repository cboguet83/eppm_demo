"""Database Flush Utility.

Removes all project records, milestones/steps, and task dependencies from the SQLite database.
"""

from contextlib import closing


from app.infrastructure.database.connection import get_db
from app.infrastructure.database.project_collaboration_migration import seed_project_event_types
from app.shared.logging import get_logger

logger = get_logger(__name__)


def flush_database(db_path: str | None = None, flush_all: bool = False) -> dict[str, int]:
    """Flushes all projects, milestones/tasks, and task dependencies from the database.

    Args:
        db_path: Optional SQLite database file path. If None, uses configured default.
        flush_all: If True, also flushes organization, employee, and schema definition tables.

    Returns:
        dict[str, int]: Dictionary containing counts of deleted records.
    """
    logger.info("Starting database flush operation (flush_all=%s)...", flush_all)
    counts: dict[str, int] = {
        "projects_deleted": 0,
        "tasks_deleted": 0,
        "dependencies_deleted": 0,
    }

    with closing(get_db(db_path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        cursor = conn.cursor()

        # Measure counts before deletion
        cursor.execute("SELECT COUNT(*) FROM task_dependencies")
        counts["dependencies_deleted"] = int(cursor.fetchone()[0])

        cursor.execute("SELECT COUNT(*) FROM project_task")
        counts["tasks_deleted"] = int(cursor.fetchone()[0])

        cursor.execute("SELECT COUNT(*) FROM project")
        counts["projects_deleted"] = int(cursor.fetchone()[0])

        # Execute table flushes
        cursor.execute("DELETE FROM project_contact")
        cursor.execute("DELETE FROM project_log_event")
        cursor.execute("DELETE FROM project_property_value_item")
        cursor.execute("DELETE FROM project_property_value")
        cursor.execute("DELETE FROM resource_pool_assignment")
        cursor.execute("DELETE FROM task_tag")
        cursor.execute("DELETE FROM project_tag")
        cursor.execute("DELETE FROM task_dependencies")
        cursor.execute("DELETE FROM project_task")
        cursor.execute("DELETE FROM project")

        if flush_all:
            for table in (
                "project_role_translation",
                "project_event_type_translation",
                "project_role",
                "project_event_type",
            ):
                cursor.execute(f"DELETE FROM {table}")
            seed_project_event_types(conn)
            cursor.execute("DELETE FROM project_type_property_default_item")
            cursor.execute("DELETE FROM project_type_property_default")
            cursor.execute("DELETE FROM project_type_property_rule")
            cursor.execute("DELETE FROM project_type_property")
            cursor.execute("DELETE FROM project_type")
            cursor.execute("DELETE FROM resource_pool_group_member")
            cursor.execute("DELETE FROM resource_pool_group")
            cursor.execute("DELETE FROM resource_pool_tag")
            cursor.execute("DELETE FROM resource_pool_mapping")
            cursor.execute("DELETE FROM resource_pool")
            cursor.execute("DELETE FROM team_function")
            cursor.execute("DELETE FROM tag_dictionnary")
            cursor.execute("DELETE FROM tag_group")
            cursor.execute("DELETE FROM employee_calendar_exception")
            cursor.execute("DELETE FROM employee")
            cursor.execute("DELETE FROM team")
            cursor.execute("DELETE FROM function")
            cursor.execute("DELETE FROM function_type")
            cursor.execute("DELETE FROM schema_param_options")
            cursor.execute("DELETE FROM schema_parameter_translation")
            cursor.execute("DELETE FROM schema_parameters")
            cursor.execute("DELETE FROM schema_groups")
            cursor.execute("DELETE FROM schema_migration WHERE version='demo-bootstrap-v1'")
            cursor.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('project_type','resource_pool_group','resource_pool_group_member','resource_pool_tag')"
            )
            cursor.execute("INSERT INTO project_type(id,name,is_general) VALUES (1,'General',1)")

        # Reset autoincrement sequence counters
        cursor.execute(
            "DELETE FROM sqlite_sequence WHERE name IN ("
            "'project', 'project_task', 'task_dependencies', 'task_tag', 'project_tag', "
            "'resource_pool_assignment', 'resource_pool_mapping', 'resource_pool', 'team_function', "
            "'tag_dictionnary', 'tag_group', 'employee_calendar_exception', 'employee', 'team', 'function', "
            "'function_type', 'schema_param_options', 'schema_groups')"
        )

        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

    logger.info(
        "Database flushed successfully: %d projects, %d tasks, %d dependencies removed.",
        counts["projects_deleted"],
        counts["tasks_deleted"],
        counts["dependencies_deleted"],
    )
    return counts
