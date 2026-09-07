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
                mandatory BOOLEAN DEFAULT 0,
                alias TEXT DEFAULT '',
                FOREIGN KEY (group_id) REFERENCES schema_groups (id) ON DELETE RESTRICT
            )
        """)

        # Migration check: ensure schema_parameters uses param_id as primary key, plus mandatory and alias columns
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
                    mandatory BOOLEAN DEFAULT 0,
                    alias TEXT DEFAULT '',
                    FOREIGN KEY (group_id) REFERENCES schema_groups (id) ON DELETE RESTRICT
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
            cursor.execute("PRAGMA table_info(schema_parameters)")
            param_cols = {col[1]: col for col in cursor.fetchall()}

        if "mandatory" not in param_cols:
            cursor.execute("ALTER TABLE schema_parameters ADD COLUMN mandatory BOOLEAN DEFAULT 0")
        if "alias" not in param_cols:
            cursor.execute("ALTER TABLE schema_parameters ADD COLUMN alias TEXT DEFAULT ''")

        # 3. Discrete Enum & Tags Options Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_param_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                param_id TEXT NOT NULL,
                option_value TEXT NOT NULL,
                display_order INTEGER DEFAULT 0,
                FOREIGN KEY (param_id) REFERENCES schema_parameters (param_id) ON DELETE RESTRICT
            )
        """)

        # 4. Project Master Table (INTEGER PRIMARY KEY)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'Draft',
                planned_budget REAL DEFAULT 0.0,
                actual_budget REAL DEFAULT 0.0,
                dynamic_attributes TEXT,
                function_id INTEGER,
                FOREIGN KEY (function_id) REFERENCES function (function_id) ON DELETE RESTRICT
            )
        """)

        # Migration: Migrate legacy 'projects' table to 'project' if it exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='projects'")
        if cursor.fetchone():
            logger.info("Migrating legacy 'projects' table to 'project' with INTEGER PRIMARY KEY...")
            cursor.execute("SELECT id, name, status, planned_budget, actual_budget, dynamic_attributes FROM projects")
            legacy_projects = cursor.fetchall()
            for r in legacy_projects:
                raw_id, p_name, p_status, p_plan, p_act, p_dyn = r
                p_id_int = None
                if isinstance(raw_id, int):
                    p_id_int = raw_id
                elif isinstance(raw_id, str):
                    if raw_id.isdigit():
                        p_id_int = int(raw_id)
                    elif raw_id.startswith("PRJ-"):
                        part = raw_id.split("-")[-1]
                        if part.isdigit():
                            p_id_int = int(part)
                if p_id_int is not None:
                    cursor.execute(
                        "INSERT OR IGNORE INTO project (id, name, status, planned_budget, actual_budget, dynamic_attributes) VALUES (?, ?, ?, ?, ?, ?)",
                        (p_id_int, p_name, p_status, p_plan, p_act, p_dyn),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO project (name, status, planned_budget, actual_budget, dynamic_attributes) VALUES (?, ?, ?, ?, ?)",
                        (p_name, p_status, p_plan, p_act, p_dyn),
                    )
            cursor.execute("DROP TABLE projects")

        cursor.execute("PRAGMA table_info(project)")
        proj_cols = {col[1] for col in cursor.fetchall()}
        if "function_id" not in proj_cols:
            logger.info("Migrating project table: adding function_id column")
            cursor.execute("ALTER TABLE project ADD COLUMN function_id INTEGER REFERENCES function (function_id) ON DELETE RESTRICT")

        # 5. Project Tasks Table (renamed from project_milestones, INTEGER PRIMARY KEY)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_task (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                task_name TEXT NOT NULL,
                phase TEXT DEFAULT 'General',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                progress_pct INTEGER DEFAULT 0,
                description TEXT DEFAULT '',
                predecessor_id INTEGER,
                FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE RESTRICT,
                FOREIGN KEY (predecessor_id) REFERENCES project_task (id) ON DELETE RESTRICT
            )
        """)

        # Migration: Migrate legacy 'project_milestones' table to 'project_task' if it exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='project_milestones'")
        if cursor.fetchone():
            logger.info("Migrating legacy 'project_milestones' table to 'project_task'...")
            cursor.execute("PRAGMA table_info(project_milestones)")
            m_cols = [c[1] for c in cursor.fetchall()]
            has_desc = "description" in m_cols
            has_pred = "predecessor_id" in m_cols
            has_phase = "phase" in m_cols
            has_prog = "progress_pct" in m_cols

            cursor.execute("SELECT * FROM project_milestones")
            legacy_milestones = cursor.fetchall()
            for r in legacy_milestones:
                row_dict = dict(zip(m_cols, r))
                m_id = row_dict.get("id")
                raw_pid = row_dict.get("project_id")
                pid_int = 1
                if isinstance(raw_pid, int):
                    pid_int = raw_pid
                elif isinstance(raw_pid, str):
                    if raw_pid.isdigit():
                        pid_int = int(raw_pid)
                    elif raw_pid.startswith("PRJ-"):
                        part = raw_pid.split("-")[-1]
                        if part.isdigit():
                            pid_int = int(part)
                t_name = row_dict.get("task_name", "")
                t_phase = row_dict.get("phase", "General") if has_phase else "General"
                t_start = row_dict.get("start_date", "")
                t_end = row_dict.get("end_date", "")
                t_prog = row_dict.get("progress_pct", 0) if has_prog else 0
                t_desc = row_dict.get("description", "") if has_desc else ""
                t_pred = row_dict.get("predecessor_id") if has_pred else None

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO project_task 
                    (id, project_id, task_name, phase, start_date, end_date, progress_pct, description, predecessor_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (m_id, pid_int, t_name, t_phase, t_start, t_end, t_prog, t_desc, t_pred),
                )
            cursor.execute("DROP TABLE project_milestones")

        # 6. Task Dependencies Table (Multi-predecessors, external project/tasks, link types, lag offsets)
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='task_dependencies'")
        dep_table_row = cursor.fetchone()
        if dep_table_row and dep_table_row[0] and ("REFERENCES projects" in dep_table_row[0] or "REFERENCES project_milestones" in dep_table_row[0]):
            logger.info("Migrating task_dependencies schema to reference project and project_task...")
            cursor.execute("""
                CREATE TABLE task_dependencies_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    predecessor_task_id INTEGER,
                    predecessor_project_id INTEGER,
                    link_type TEXT DEFAULT 'FS',
                    lag_days INTEGER DEFAULT 0,
                    FOREIGN KEY (task_id) REFERENCES project_task (id) ON DELETE RESTRICT,
                    FOREIGN KEY (predecessor_task_id) REFERENCES project_task (id) ON DELETE RESTRICT,
                    FOREIGN KEY (predecessor_project_id) REFERENCES project (id) ON DELETE RESTRICT
                )
            """)
            cursor.execute("SELECT id, task_id, predecessor_task_id, predecessor_project_id, link_type, lag_days FROM task_dependencies")
            old_deps = cursor.fetchall()
            for dep in old_deps:
                d_id, t_id, pred_t_id, pred_p_id, lt, lag = dep
                int_pred_pid = None
                if pred_p_id is not None:
                    if isinstance(pred_p_id, int):
                        int_pred_pid = pred_p_id
                    elif isinstance(pred_p_id, str):
                        if pred_p_id.isdigit():
                            int_pred_pid = int(pred_p_id)
                        elif pred_p_id.startswith("PRJ-"):
                            part = pred_p_id.split("-")[-1]
                            if part.isdigit():
                                int_pred_pid = int(part)
                cursor.execute(
                    "INSERT INTO task_dependencies_new (id, task_id, predecessor_task_id, predecessor_project_id, link_type, lag_days) VALUES (?, ?, ?, ?, ?, ?)",
                    (d_id, t_id, pred_t_id, int_pred_pid, lt, lag),
                )
            cursor.execute("DROP TABLE task_dependencies")
            cursor.execute("ALTER TABLE task_dependencies_new RENAME TO task_dependencies")
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_dependencies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    predecessor_task_id INTEGER,
                    predecessor_project_id INTEGER,
                    link_type TEXT DEFAULT 'FS',
                    lag_days INTEGER DEFAULT 0,
                    FOREIGN KEY (task_id) REFERENCES project_task (id) ON DELETE RESTRICT,
                    FOREIGN KEY (predecessor_task_id) REFERENCES project_task (id) ON DELETE RESTRICT,
                    FOREIGN KEY (predecessor_project_id) REFERENCES project (id) ON DELETE RESTRICT
                )
            """)

        # Migration from legacy predecessor_id into task_dependencies if empty
        cursor.execute("SELECT COUNT(*) FROM task_dependencies")
        dep_count = cursor.fetchone()[0]
        if dep_count == 0:
            cursor.execute("""
                INSERT INTO task_dependencies (task_id, predecessor_task_id, link_type, lag_days)
                SELECT id, predecessor_id, 'FS', 0
                FROM project_task
                WHERE predecessor_id IS NOT NULL
            """)

        # 7. Function Type Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS function_type (
                function_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
                function_type TEXT NOT NULL UNIQUE
            )
        """)

        # 8. Function Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS function (
                function_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                hierarchy_level INTEGER NOT NULL,
                function_type_id INTEGER,
                manager_function_id INTEGER,
                dual_manager_function_id INTEGER,
                fte_percentage INTEGER DEFAULT 100,
                has_reports BOOLEAN DEFAULT 0,
                FOREIGN KEY (function_type_id) REFERENCES function_type (function_type_id) ON DELETE RESTRICT,
                FOREIGN KEY (manager_function_id) REFERENCES function (function_id) ON DELETE RESTRICT,
                FOREIGN KEY (dual_manager_function_id) REFERENCES function (function_id) ON DELETE RESTRICT
            )
        """)

        # 9. Team Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS team (
                team_id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_name TEXT NOT NULL,
                manager_function_id INTEGER,
                leader_function_id INTEGER,
                FOREIGN KEY (manager_function_id) REFERENCES function (function_id) ON DELETE RESTRICT,
                FOREIGN KEY (leader_function_id) REFERENCES function (function_id) ON DELETE RESTRICT
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
                occupation_percentage REAL NOT NULL DEFAULT 100.0
                    CHECK(occupation_percentage >= 0.0 AND occupation_percentage <= 100.0),
                FOREIGN KEY (function_id) REFERENCES function (function_id) ON DELETE RESTRICT
            )
        """)

        # Existing databases receive a 100% default without changing current employees.
        cursor.execute("PRAGMA table_info(employee)")
        employee_columns = [col[1] for col in cursor.fetchall()]
        if "occupation_percentage" not in employee_columns:
            cursor.execute(
                "ALTER TABLE employee ADD COLUMN occupation_percentage REAL NOT NULL DEFAULT 100.0 "
                "CHECK(occupation_percentage >= 0.0 AND occupation_percentage <= 100.0)"
            )

        # 11. Employee Calendar Exceptions (inclusive temporary occupation overrides)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employee_calendar_exception (
                exception_id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                occupation_percentage REAL NOT NULL
                    CHECK(occupation_percentage >= 0.0 AND occupation_percentage <= 100.0),
                reason TEXT DEFAULT '',
                CHECK(end_date >= start_date),
                FOREIGN KEY (employee_id) REFERENCES employee (employee_id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_employee_calendar_exception_period
            ON employee_calendar_exception (employee_id, start_date, end_date)
        """)

        # 12. Tag Group Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tag_group (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_group_name TEXT NOT NULL
            )
        """)

        # 13. Tag Dictionary Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tag_dictionnary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT NOT NULL,
                tag_group_id INTEGER,
                FOREIGN KEY (tag_group_id) REFERENCES tag_group (id) ON DELETE RESTRICT
            )
        """)

        # 14. Task Tag Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_tag (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_id INTEGER,
                task_id INTEGER NOT NULL,
                free_tag TEXT,
                FOREIGN KEY (tag_id) REFERENCES tag_dictionnary (id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES project_task (id) ON DELETE CASCADE
            )
        """)

        # 15. Project Tag Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_tag (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_id INTEGER,
                project_id INTEGER NOT NULL,
                free_tag TEXT,
                FOREIGN KEY (tag_id) REFERENCES tag_dictionnary (id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE CASCADE
            )
        """)

        # 16. Team Function Membership Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS team_function (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                function_id INTEGER NOT NULL,
                FOREIGN KEY (team_id) REFERENCES team (team_id) ON DELETE CASCADE,
                FOREIGN KEY (function_id) REFERENCES function (function_id) ON DELETE CASCADE,
                UNIQUE(team_id, function_id)
            )
        """)

        # 17. Resource Pools Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resource_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 18. Resource Pool Mappings Table (Teams & Functions with partial 0-100% allocation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resource_pool_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pool_id INTEGER NOT NULL,
                target_type TEXT NOT NULL CHECK(target_type IN ('team', 'function')),
                target_id INTEGER NOT NULL,
                allocation_pct REAL NOT NULL DEFAULT 100.0 CHECK(allocation_pct >= 0.0 AND allocation_pct <= 100.0),
                FOREIGN KEY (pool_id) REFERENCES resource_pool (id) ON DELETE CASCADE,
                UNIQUE(pool_id, target_type, target_id)
            )
        """)

        # 19. Resource Pool Assignments Table (Task or Project with FTE & optional custom period)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resource_pool_assignment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pool_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                task_id INTEGER,
                fte_assigned REAL NOT NULL CHECK(fte_assigned >= 0.0),
                start_date TEXT,
                end_date TEXT,
                notes TEXT DEFAULT '',
                FOREIGN KEY (pool_id) REFERENCES resource_pool (id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES project_task (id) ON DELETE CASCADE
            )
        """)

        # Migration check for resource_pool_assignment start_date / end_date
        cursor.execute("PRAGMA table_info(resource_pool_assignment)")
        rpa_cols = [c[1] for c in cursor.fetchall()]
        if "start_date" not in rpa_cols and len(rpa_cols) > 0:
            cursor.execute("ALTER TABLE resource_pool_assignment ADD COLUMN start_date TEXT")
        if "end_date" not in rpa_cols and len(rpa_cols) > 0:
            cursor.execute("ALTER TABLE resource_pool_assignment ADD COLUMN end_date TEXT")

        # 20. Schema migrations for project, organization, and function tables
        cursor.execute("PRAGMA table_info(project)")
        proj_cols = [col[1] for col in cursor.fetchall()]
        if "dynamic_attributes" not in proj_cols:
            cursor.execute("ALTER TABLE project ADD COLUMN dynamic_attributes TEXT")
        if "planned_budget" not in proj_cols:
            cursor.execute("ALTER TABLE project ADD COLUMN planned_budget REAL DEFAULT 0.0")
        if "actual_budget" not in proj_cols:
            cursor.execute("ALTER TABLE project ADD COLUMN actual_budget REAL DEFAULT 0.0")
        if "function_id" not in proj_cols:
            cursor.execute("ALTER TABLE project ADD COLUMN function_id INTEGER REFERENCES function(function_id) ON DELETE RESTRICT")

        # Cleanup legacy hierarchy_level table if present
        cursor.execute("DROP TABLE IF EXISTS hierarchy_level")

        cursor.execute("PRAGMA table_info(function)")
        func_cols = [col[1] for col in cursor.fetchall()]
        cursor.execute("PRAGMA foreign_key_list(function)")
        fk_list = cursor.fetchall()
        has_hl_fk = any(fk[2] == "hierarchy_level" for fk in fk_list)

        if has_hl_fk or ("hierarchy_level_id" in func_cols and "hierarchy_level" not in func_cols):
            cursor.execute("""
                CREATE TABLE function_new (
                    function_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    hierarchy_level INTEGER NOT NULL,
                    function_type_id INTEGER,
                    manager_function_id INTEGER,
                    dual_manager_function_id INTEGER,
                    fte_percentage INTEGER DEFAULT 100,
                    has_reports BOOLEAN DEFAULT 0,
                    FOREIGN KEY (function_type_id) REFERENCES function_type (function_type_id) ON DELETE RESTRICT,
                    FOREIGN KEY (manager_function_id) REFERENCES function (function_id) ON DELETE RESTRICT,
                    FOREIGN KEY (dual_manager_function_id) REFERENCES function (function_id) ON DELETE RESTRICT
                )
            """)
            lvl_col = "hierarchy_level" if "hierarchy_level" in func_cols else "hierarchy_level_id"
            ft_col = "function_type_id" if "function_type_id" in func_cols else "NULL"
            fte_col = "fte_percentage" if "fte_percentage" in func_cols else "100"
            rep_col = "has_reports" if "has_reports" in func_cols else "0"
            cursor.execute(f"""
                INSERT INTO function_new (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports)
                SELECT function_id, name, {lvl_col}, {ft_col}, manager_function_id, dual_manager_function_id, {fte_col}, {rep_col} FROM function
            """)
            cursor.execute("DROP TABLE function")
            cursor.execute("ALTER TABLE function_new RENAME TO function")
        else:
            if "function_type_id" not in func_cols:
                cursor.execute("ALTER TABLE function ADD COLUMN function_type_id INTEGER REFERENCES function_type(function_type_id) ON DELETE RESTRICT")
            if "fte_percentage" not in func_cols:
                cursor.execute("ALTER TABLE function ADD COLUMN fte_percentage INTEGER DEFAULT 100")
            if "has_reports" not in func_cols:
                cursor.execute("ALTER TABLE function ADD COLUMN has_reports BOOLEAN DEFAULT 0")

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
                        occupation_percentage REAL NOT NULL DEFAULT 100.0
                            CHECK(occupation_percentage >= 0.0 AND occupation_percentage <= 100.0),
                        FOREIGN KEY (function_id) REFERENCES function (function_id) ON DELETE RESTRICT
                    )
                """)
                occupation_col = "occupation_percentage" if "occupation_percentage" in emp_cols else "100.0"
                cursor.execute("""
                    INSERT INTO employee_new (
                        employee_id, firstname, lastname, email, mobile, sigle,
                        employee_code, function_id, occupation_percentage
                    )
                    SELECT employee_id, firstname, lastname, email, mobile, sigle,
                           employee_code, function_id, """ + occupation_col + """
                    FROM employee
                """)
                cursor.execute("DROP TABLE employee")
                cursor.execute("ALTER TABLE employee_new RENAME TO employee")

        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
    logger.info("Schema initialization complete")
