"""Database Flush Utility.

Removes all project records, milestones/steps, and task dependencies from the SQLite database.
"""

import argparse
import os
import sys
from typing import Optional

# Ensure project root is in sys.path when running script directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.connection import get_db
from src.logging_config import get_logger

logger = get_logger(__name__)


def flush_database(db_path: Optional[str] = None, flush_all: bool = False) -> dict[str, int]:
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

    with get_db(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        cursor = conn.cursor()

        # Measure counts before deletion
        cursor.execute("SELECT COUNT(*) FROM task_dependencies")
        counts["dependencies_deleted"] = int(cursor.fetchone()[0])

        cursor.execute("SELECT COUNT(*) FROM project_milestones")
        counts["tasks_deleted"] = int(cursor.fetchone()[0])

        cursor.execute("SELECT COUNT(*) FROM projects")
        counts["projects_deleted"] = int(cursor.fetchone()[0])

        # Execute table flushes
        cursor.execute("DELETE FROM task_dependencies")
        cursor.execute("DELETE FROM project_milestones")
        cursor.execute("DELETE FROM projects")

        if flush_all:
            cursor.execute("DELETE FROM employee")
            cursor.execute("DELETE FROM team")
            cursor.execute("DELETE FROM function")
            cursor.execute("DELETE FROM function_type")
            cursor.execute("DELETE FROM schema_param_options")
            cursor.execute("DELETE FROM schema_parameters")
            cursor.execute("DELETE FROM schema_groups")

        # Reset autoincrement sequence counters
        cursor.execute(
            "DELETE FROM sqlite_sequence WHERE name IN ("
            "'project_milestones', 'task_dependencies', 'employee', 'team', 'function', "
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


def main() -> None:
    """CLI entrypoint for database flush script."""
    parser = argparse.ArgumentParser(description="Flush all projects and tasks from the EPPM database.")
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Optional path to custom SQLite database file.",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Bypass interactive confirmation prompt.",
    )

    args = parser.parse_args()

    if not args.yes:
        confirm = input("[!] Are you sure you want to flush ALL projects and tasks from the database? (y/N): ").strip().lower()
        if confirm != "y":
            print("Flush operation cancelled.")
            sys.exit(0)

    result = flush_database(args.db_path)
    print("--------------------------------------------------")
    print("[+] EPPM Database Flushed Successfully:")
    print(f"   - Projects deleted:     {result['projects_deleted']:,}")
    print(f"   - Tasks deleted:        {result['tasks_deleted']:,}")
    print(f"   - Dependencies deleted: {result['dependencies_deleted']:,}")
    print("--------------------------------------------------")


if __name__ == "__main__":
    main()
