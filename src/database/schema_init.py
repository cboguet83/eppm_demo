"""Database schema initialization and migration engine."""

import sqlite3
from typing import Optional

from src.config import config
from src.database.connection import get_db
from src.logging_config import get_logger

logger = get_logger(__name__)


def init_db(db_path: Optional[str] = None) -> None:
    """Initializes the database schema and performs schema migrations if needed.

    Args:
        db_path: Filepath to the SQLite database. If None, uses default from config.
    """
    target_path = db_path if db_path is not None else config.db_path
    logger.info("Initializing database schema for %s", target_path)

    with get_db(target_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        cursor = conn.cursor()

        # 1. Parameter Groups Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT UNIQUE NOT NULL,
                display_order INTEGER UNIQUE NOT NULL
            )
        """)

        # 2. Normalized Parameters Table (group_id can be NULL for ungrouped parameters)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_parameters (
                param_id TEXT PRIMARY KEY,
                group_id INTEGER,
                param_name TEXT NOT NULL,
                param_type TEXT NOT NULL,
                FOREIGN KEY (group_id) REFERENCES schema_groups (id) ON DELETE SET NULL
            )
        """)

        # Migration check: ensure schema_parameters uses param_id as primary key
        cursor.execute("PRAGMA table_info(schema_parameters)")
        param_cols = {col[1]: col for col in cursor.fetchall()}
        if "param_id" not in param_cols or param_cols["param_id"][5] == 0:
            logger.info("Migrating schema_parameters to enforce param_id PRIMARY KEY")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_parameters_migrated (
                    param_id TEXT PRIMARY KEY,
                    group_id INTEGER,
                    param_name TEXT NOT NULL,
                    param_type TEXT NOT NULL,
                    FOREIGN KEY (group_id) REFERENCES schema_groups (id) ON DELETE SET NULL
                )
            """)
            if "param_id" in param_cols:
                cursor.execute("""
                    INSERT OR IGNORE INTO schema_parameters_migrated (param_id, group_id, param_name, param_type)
                    SELECT COALESCE(param_id, 'PRM_' || printf('%03d', id)), group_id, param_name, param_type
                    FROM schema_parameters
                """)
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO schema_parameters_migrated (param_id, group_id, param_name, param_type)
                    SELECT 'PRM_' || printf('%03d', id), group_id, param_name, param_type
                    FROM schema_parameters
                """)
            cursor.execute("DROP TABLE schema_parameters")
            cursor.execute("ALTER TABLE schema_parameters_migrated RENAME TO schema_parameters")

        # 3. Discrete Enum & Tags Options Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_param_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                param_id TEXT NOT NULL,
                option_value TEXT NOT NULL,
                display_order INTEGER DEFAULT 0,
                FOREIGN KEY (param_id) REFERENCES schema_parameters (param_id) ON DELETE CASCADE
            )
        """)

        # 4. Project Master Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'Draft',
                planned_budget REAL DEFAULT 0.0,
                actual_budget REAL DEFAULT 0.0,
                dynamic_attributes TEXT
            )
        """)

        # 5. Project Steps / Milestones Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                task_name TEXT NOT NULL,
                phase TEXT DEFAULT 'General',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                progress_pct INTEGER DEFAULT 0,
                predecessor_id INTEGER,
                FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                FOREIGN KEY (predecessor_id) REFERENCES project_milestones (id) ON DELETE SET NULL
            )
        """)

        # Schema migrations for project_milestones
        cursor.execute("PRAGMA table_info(project_milestones)")
        milestone_cols = [col[1] for col in cursor.fetchall()]
        if "phase" not in milestone_cols:
            cursor.execute("ALTER TABLE project_milestones ADD COLUMN phase TEXT DEFAULT 'General'")
        if "progress_pct" not in milestone_cols:
            cursor.execute("ALTER TABLE project_milestones ADD COLUMN progress_pct INTEGER DEFAULT 0")
        if "predecessor_id" not in milestone_cols:
            cursor.execute("ALTER TABLE project_milestones ADD COLUMN predecessor_id INTEGER")

        # Schema migrations for projects
        cursor.execute("PRAGMA table_info(projects)")
        proj_cols = [col[1] for col in cursor.fetchall()]
        if "dynamic_attributes" not in proj_cols:
            cursor.execute("ALTER TABLE projects ADD COLUMN dynamic_attributes TEXT")
        if "planned_budget" not in proj_cols:
            cursor.execute("ALTER TABLE projects ADD COLUMN planned_budget REAL DEFAULT 0.0")
        if "actual_budget" not in proj_cols:
            cursor.execute("ALTER TABLE projects ADD COLUMN actual_budget REAL DEFAULT 0.0")

        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
    logger.info("Schema initialization complete")
