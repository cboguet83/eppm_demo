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
                description TEXT DEFAULT '',
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
        if "description" not in milestone_cols:
            cursor.execute("ALTER TABLE project_milestones ADD COLUMN description TEXT DEFAULT ''")
        if "predecessor_id" not in milestone_cols:
            cursor.execute("ALTER TABLE project_milestones ADD COLUMN predecessor_id INTEGER")

        # 6. Task Dependencies Table (Multi-predecessors, external project/tasks, link types, lag offsets)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                predecessor_task_id INTEGER,
                predecessor_project_id TEXT,
                link_type TEXT DEFAULT 'FS',
                lag_days INTEGER DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES project_milestones (id) ON DELETE CASCADE,
                FOREIGN KEY (predecessor_task_id) REFERENCES project_milestones (id) ON DELETE CASCADE,
                FOREIGN KEY (predecessor_project_id) REFERENCES projects (id) ON DELETE CASCADE
            )
        """)

        # Migration from legacy project_milestones.predecessor_id into task_dependencies if empty
        cursor.execute("SELECT COUNT(*) FROM task_dependencies")
        dep_count = cursor.fetchone()[0]
        if dep_count == 0:
            cursor.execute("""
                INSERT INTO task_dependencies (task_id, predecessor_task_id, link_type, lag_days)
                SELECT id, predecessor_id, 'FS', 0
                FROM project_milestones
                WHERE predecessor_id IS NOT NULL
            """)

        # 7. Hierarchy Level Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hierarchy_level (
                hierarchy_level_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                parent_hierarchy_level_id INTEGER,
                manager_function_id INTEGER,
                FOREIGN KEY (parent_hierarchy_level_id) REFERENCES hierarchy_level (hierarchy_level_id) ON DELETE SET NULL,
                FOREIGN KEY (manager_function_id) REFERENCES function (function_id) ON DELETE SET NULL
            )
        """)

        # 8. Function Type Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS function_type (
                function_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
                function_type TEXT NOT NULL UNIQUE
            )
        """)

        # 9. Function Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS function (
                function_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                hierarchy_level_id INTEGER NOT NULL,
                function_type_id INTEGER,
                manager_function_id INTEGER,
                dual_manager_function_id INTEGER,
                FOREIGN KEY (hierarchy_level_id) REFERENCES hierarchy_level (hierarchy_level_id) ON DELETE RESTRICT,
                FOREIGN KEY (function_type_id) REFERENCES function_type (function_type_id) ON DELETE SET NULL,
                FOREIGN KEY (manager_function_id) REFERENCES function (function_id) ON DELETE SET NULL,
                FOREIGN KEY (dual_manager_function_id) REFERENCES function (function_id) ON DELETE SET NULL
            )
        """)

        # 10. Employee Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employee (
                employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
                firstname TEXT NOT NULL,
                lastname TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                mobile TEXT DEFAULT '',
                sigle TEXT DEFAULT '',
                employee_code TEXT NOT NULL UNIQUE,
                function_id INTEGER,
                FOREIGN KEY (function_id) REFERENCES function (function_id) ON DELETE SET NULL
            )
        """)

        # 11. Schema migrations for projects and organization tables
        cursor.execute("PRAGMA table_info(projects)")
        proj_cols = [col[1] for col in cursor.fetchall()]
        if "dynamic_attributes" not in proj_cols:
            cursor.execute("ALTER TABLE projects ADD COLUMN dynamic_attributes TEXT")
        if "planned_budget" not in proj_cols:
            cursor.execute("ALTER TABLE projects ADD COLUMN planned_budget REAL DEFAULT 0.0")
        if "actual_budget" not in proj_cols:
            cursor.execute("ALTER TABLE projects ADD COLUMN actual_budget REAL DEFAULT 0.0")

        cursor.execute("PRAGMA table_info(function)")
        func_cols = [col[1] for col in cursor.fetchall()]
        if "function_type_id" not in func_cols:
            cursor.execute("ALTER TABLE function ADD COLUMN function_type_id INTEGER REFERENCES function_type(function_type_id)")

        cursor.execute("PRAGMA table_info(employee)")
        emp_cols = [col[1] for col in cursor.fetchall()]
        if "function_type_id" in emp_cols:
            try:
                cursor.execute("ALTER TABLE employee DROP COLUMN function_type_id")
            except sqlite3.OperationalError:
                # If DROP COLUMN is not supported in this SQLite build, recreate table
                cursor.execute("""
                    CREATE TABLE employee_new (
                        employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        firstname TEXT NOT NULL,
                        lastname TEXT NOT NULL,
                        email TEXT NOT NULL UNIQUE,
                        mobile TEXT DEFAULT '',
                        sigle TEXT DEFAULT '',
                        employee_code TEXT NOT NULL UNIQUE,
                        function_id INTEGER,
                        FOREIGN KEY (function_id) REFERENCES function (function_id) ON DELETE SET NULL
                    )
                """)
                cursor.execute("""
                    INSERT INTO employee_new (employee_id, firstname, lastname, email, mobile, sigle, employee_code, function_id)
                    SELECT employee_id, firstname, lastname, email, mobile, sigle, employee_code, function_id FROM employee
                """)
                cursor.execute("DROP TABLE employee")
                cursor.execute("ALTER TABLE employee_new RENAME TO employee")

        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
    logger.info("Schema initialization complete")
