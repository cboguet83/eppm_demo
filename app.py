"""PPM Studio Pro - Enterprise Project Portfolio Management Demo Application.

This application provides a comprehensive Streamlit dashboard for managing
project portfolios, dynamic schema attributes, milestone planning schedules,
and financial budget tracking with interactive Plotly visual analytics.
"""

import datetime
import io
import json
import sqlite3
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

# ==============================================================================
# CONSTANTS & CONFIGURATION
# ==============================================================================
DB_NAME: str = "ppm_mock.db"

PAGE_PORTFOLIO: str = "1. Portfolio Overview"
PAGE_PROJECT_MASTER: str = "2. Project Master Data"
PAGE_SCHEMA_DEF: str = "3. Parameters Definition (Schema)"
PAGE_PLANNING: str = "4. Planning & Milestone Loader"
PAGE_BUDGET: str = "5. Budget Tracking"

STATUS_DRAFT: str = "Draft"
STATUS_IN_PROGRESS: str = "In Progress"
STATUS_ON_HOLD: str = "On Hold"
STATUS_COMPLETED: str = "Completed"
STATUS_CANCELLED: str = "Cancelled"
STATUS_LIST: list[str] = [
    STATUS_DRAFT,
    STATUS_IN_PROGRESS,
    STATUS_ON_HOLD,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
]

PARAM_TYPE_TEXT: str = "TEXT"
PARAM_TYPE_ENUM: str = "ENUM"
PARAM_TYPE_MULTI_ENUM: str = "MULTI_ENUM"
PARAM_TYPE_URL: str = "URL"
PARAM_TYPES: list[str] = [
    PARAM_TYPE_TEXT,
    PARAM_TYPE_ENUM,
    PARAM_TYPE_MULTI_ENUM,
    PARAM_TYPE_URL,
]


# ==============================================================================
# DATABASE INITIALIZATION & REPOSITORY
# ==============================================================================
def get_db(db_path: str = DB_NAME) -> sqlite3.Connection:
    """Creates and returns a SQLite database connection with foreign keys enabled.

    Args:
        db_path: Filepath to the SQLite database.

    Returns:
        sqlite3.Connection: Active database connection.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = DB_NAME) -> None:
    """Initializes the database schema and performs schema migrations if needed.

    Args:
        db_path: Filepath to the SQLite database.
    """
    with get_db(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        cursor = conn.cursor()

        # 1. Parameter Groups Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT UNIQUE NOT NULL,
                display_order INTEGER DEFAULT 0
            )
        """)

        # 2. Normalized Parameters Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_parameters (
                param_id TEXT PRIMARY KEY,
                group_id INTEGER NOT NULL,
                param_name TEXT NOT NULL,
                param_type TEXT NOT NULL,
                FOREIGN KEY (group_id) REFERENCES schema_groups (id) ON DELETE CASCADE
            )
        """)

        # Migration check: if schema_parameters exists but lacks primary key on param_id
        cursor.execute("PRAGMA table_info(schema_parameters)")
        param_cols = {col[1]: col for col in cursor.fetchall()}
        if "param_id" not in param_cols or param_cols["param_id"][5] == 0:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_parameters_migrated (
                    param_id TEXT PRIMARY KEY,
                    group_id INTEGER NOT NULL,
                    param_name TEXT NOT NULL,
                    param_type TEXT NOT NULL,
                    FOREIGN KEY (group_id) REFERENCES schema_groups (id) ON DELETE CASCADE
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

        # 3. Discrete Enum Options Table
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

        # 5. Project Milestones Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                task_name TEXT NOT NULL,
                phase TEXT DEFAULT 'General',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                progress_pct INTEGER DEFAULT 0,
                FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
            )
        """)

        # Schema migrations for project_milestones
        cursor.execute("PRAGMA table_info(project_milestones)")
        milestone_cols = [col[1] for col in cursor.fetchall()]
        if "phase" not in milestone_cols:
            cursor.execute("ALTER TABLE project_milestones ADD COLUMN phase TEXT DEFAULT 'General'")
        if "progress_pct" not in milestone_cols:
            cursor.execute("ALTER TABLE project_milestones ADD COLUMN progress_pct INTEGER DEFAULT 0")

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


def seed_default_data_if_empty(db_path: str = DB_NAME) -> None:
    """Populates the database with demo schema, projects, and milestones if empty.

    Args:
        db_path: Filepath to the SQLite database.
    """
    with get_db(db_path) as conn:
        cursor = conn.cursor()

        # Check if schema groups exist
        cursor.execute("SELECT COUNT(*) FROM schema_groups")
        group_count = cursor.fetchone()[0]

        if group_count == 0:
            cursor.execute("INSERT INTO schema_groups (id, group_name, display_order) VALUES (1, 'Strategic Alignment', 1)")
            cursor.execute("INSERT INTO schema_groups (id, group_name, display_order) VALUES (2, 'Governance & Architecture', 2)")

            cursor.execute("INSERT INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_001', 1, 'Strategic Priority', 'ENUM')")
            cursor.execute("INSERT INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_002', 1, 'Business Unit', 'ENUM')")
            cursor.execute("INSERT INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_003', 2, 'Tech Stack Tags', 'MULTI_ENUM')")
            cursor.execute("INSERT INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_004', 2, 'Repository URL', 'URL')")
            cursor.execute("INSERT INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_005', 2, 'Lead Architect', 'TEXT')")

            prm_001_opts = ["P1 - Critical", "P2 - High", "P3 - Medium", "P4 - Low"]
            for idx, opt in enumerate(prm_001_opts, 1):
                cursor.execute("INSERT INTO schema_param_options (param_id, option_value, display_order) VALUES ('PRM_001', ?, ?)", (opt, idx))

            prm_002_opts = ["Engineering", "Product", "Operations", "Finance", "Marketing"]
            for idx, opt in enumerate(prm_002_opts, 1):
                cursor.execute("INSERT INTO schema_param_options (param_id, option_value, display_order) VALUES ('PRM_002', ?, ?)", (opt, idx))

            prm_003_opts = ["Python", "React", "Cloud Native", "AI/ML", "Kubernetes", "PostgreSQL"]
            for idx, opt in enumerate(prm_003_opts, 1):
                cursor.execute("INSERT INTO schema_param_options (param_id, option_value, display_order) VALUES ('PRM_003', ?, ?)", (opt, idx))

        # Check existing projects
        cursor.execute("SELECT id FROM projects")
        existing_pids = {row[0] for row in cursor.fetchall()}

        sample_projects = [
            (
                "PRJ-001",
                "NextGen ERP Modernization",
                STATUS_IN_PROGRESS,
                450000.0,
                380000.0,
                json.dumps({
                    "PRM_001": "P1 - Critical",
                    "PRM_002": "Engineering",
                    "PRM_003": ["Python", "Cloud Native", "Kubernetes"],
                    "PRM_004": "https://github.com/enterprise/erp-modernization",
                    "PRM_005": "Dr. Sarah Connor",
                }),
            ),
            (
                "PRJ-002",
                "Customer 360 AI Analytics",
                STATUS_IN_PROGRESS,
                280000.0,
                310000.0,
                json.dumps({
                    "PRM_001": "P1 - Critical",
                    "PRM_002": "Product",
                    "PRM_003": ["Python", "AI/ML"],
                    "PRM_004": "https://github.com/enterprise/c360-ai",
                    "PRM_005": "Alex Chen",
                }),
            ),
            (
                "PRJ-003",
                "Global Supply Chain Audit",
                STATUS_COMPLETED,
                150000.0,
                142000.0,
                json.dumps({
                    "PRM_001": "P2 - High",
                    "PRM_002": "Operations",
                    "PRM_003": ["Cloud Native"],
                    "PRM_004": "https://docs.enterprise.internal/audit",
                    "PRM_005": "Elena Rostova",
                }),
            ),
            (
                "PRJ-004",
                "Mobile Client 2.0 Redesign",
                STATUS_DRAFT,
                200000.0,
                18000.0,
                json.dumps({
                    "PRM_001": "P3 - Medium",
                    "PRM_002": "Engineering",
                    "PRM_003": ["React", "Python"],
                    "PRM_004": "https://github.com/enterprise/mobile-v2",
                    "PRM_005": "Marcus Vance",
                }),
            ),
            (
                "PRJ-005",
                "Financial Ledger Consolidation",
                STATUS_ON_HOLD,
                320000.0,
                180000.0,
                json.dumps({
                    "PRM_001": "P2 - High",
                    "PRM_002": "Finance",
                    "PRM_003": ["PostgreSQL"],
                    "PRM_004": "https://wiki.enterprise.internal/fin-ledger",
                    "PRM_005": "Patricia Kelly",
                }),
            ),
        ]

        if not existing_pids:
            cursor.executemany(
                "INSERT INTO projects (id, name, status, planned_budget, actual_budget, dynamic_attributes) VALUES (?, ?, ?, ?, ?, ?)",
                sample_projects,
            )
            cursor.execute("SELECT id FROM projects")
            existing_pids = {row[0] for row in cursor.fetchall()}

        # Check if milestones exist
        cursor.execute("SELECT COUNT(*) FROM project_milestones")
        milestone_count = cursor.fetchone()[0]

        if milestone_count == 0:
            sample_milestones = [
                ("PRJ-001", "Architecture & Scoping", "Phase 1 - Inception", "2026-01-10", "2026-02-15", 100),
                ("PRJ-001", "Core Microservices Dev", "Phase 2 - Build", "2026-02-16", "2026-06-30", 75),
                ("PRJ-001", "Integration & UAT", "Phase 3 - Validation", "2026-07-01", "2026-09-15", 25),
                ("PRJ-001", "Production Cutover", "Phase 4 - Rollout", "2026-09-16", "2026-10-31", 0),
                ("PRJ-002", "Data Pipeline Ingestion", "Phase 1 - Data Eng", "2026-02-01", "2026-04-15", 100),
                ("PRJ-002", "Model Training & Tuning", "Phase 2 - ML Dev", "2026-04-16", "2026-07-30", 65),
                ("PRJ-002", "Dashboard & API Integration", "Phase 3 - Frontend/API", "2026-08-01", "2026-10-15", 10),
                ("PRJ-003", "Requirements Gathering", "Phase 1 - Discovery", "2026-01-05", "2026-02-10", 100),
                ("PRJ-003", "Audit Execution", "Phase 2 - Audit", "2026-02-11", "2026-04-20", 100),
                ("PRJ-003", "Executive Reporting", "Phase 3 - Final Report", "2026-04-21", "2026-05-15", 100),
            ]
            valid_milestones = [m for m in sample_milestones if m[0] in existing_pids]
            if valid_milestones:
                cursor.executemany(
                    "INSERT INTO project_milestones (project_id, task_name, phase, start_date, end_date, progress_pct) VALUES (?, ?, ?, ?, ?, ?)",
                    valid_milestones,
                )

        conn.commit()


# ==============================================================================
# SCHEMA & DATA PROCESSING HELPERS
# ==============================================================================
def generate_param_id(db_path: str = DB_NAME) -> str:
    """Generates the next sequential parameter ID (e.g., PRM_001, PRM_002).

    Args:
        db_path: Filepath to the SQLite database.

    Returns:
        str: Formatted next parameter ID.
    """
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(schema_parameters)")
        param_cols = [c[1] for c in cursor.fetchall()]
        col_to_select = "param_id" if "param_id" in param_cols else "id"
        cursor.execute(f"SELECT {col_to_select} FROM schema_parameters")
        rows = cursor.fetchall()
        max_num = 0
        for (val,) in rows:
            if isinstance(val, int):
                max_num = max(max_num, val)
            elif isinstance(val, str):
                if val.startswith("PRM_"):
                    try:
                        num = int(val.split("_")[1])
                        max_num = max(max_num, num)
                    except (IndexError, ValueError):
                        pass
                elif val.isdigit():
                    max_num = max(max_num, int(val))
        return f"PRM_{max_num + 1:03d}"


def load_full_schema(
    db_path: str = DB_NAME,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Loads all schema definition tables from the database.

    Args:
        db_path: Filepath to the SQLite database.

    Returns:
        tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]: DataFrames for groups, parameters, and options.
    """
    with get_db(db_path) as conn:
        groups = pd.read_sql("SELECT * FROM schema_groups ORDER BY display_order, id", conn)
        params = pd.read_sql("SELECT param_id, group_id, param_name, param_type FROM schema_parameters", conn)
        options = pd.read_sql("SELECT * FROM schema_param_options ORDER BY display_order, id", conn)
    return groups, params, options


def flatten_dynamic_attributes(
    df_projects: pd.DataFrame, params: pd.DataFrame
) -> pd.DataFrame:
    """Unpacks JSON dynamic_attributes column into individual DataFrame columns.

    Args:
        df_projects: Projects DataFrame containing id and dynamic_attributes columns.
        params: Schema parameters DataFrame.

    Returns:
        pd.DataFrame: Merged DataFrame with flattened dynamic attributes.
    """
    if df_projects.empty:
        return df_projects

    flattened_rows: list[dict[str, Any]] = []
    for _, row in df_projects.iterrows():
        raw_json = row.get("dynamic_attributes")
        attrs: dict[str, Any] = {}
        if pd.notna(raw_json) and isinstance(raw_json, str) and raw_json.strip():
            try:
                parsed = json.loads(raw_json)
                if isinstance(parsed, dict):
                    attrs = parsed
            except json.JSONDecodeError:
                attrs = {}
        attrs["id"] = row["id"]
        flattened_rows.append(attrs)

    df_dyn = pd.DataFrame(flattened_rows)
    df_merged = pd.merge(
        df_projects.drop(columns=["dynamic_attributes"], errors="ignore"),
        df_dyn,
        on="id",
        how="left",
    )

    if not params.empty and "param_id" in params.columns:
        for _, p in params.iterrows():
            pid = str(p["param_id"])
            ptype = str(p.get("param_type", PARAM_TYPE_TEXT))
            if pid not in df_merged.columns:
                df_merged[pid] = None
            if ptype == PARAM_TYPE_MULTI_ENUM:
                df_merged[pid] = df_merged[pid].apply(
                    lambda x: x if isinstance(x, list) else ([x] if pd.notna(x) and x != "" else [])
                )
    return df_merged


def calculate_portfolio_metrics(df_projects: pd.DataFrame) -> dict[str, float]:
    """Calculates summary financial KPIs from a projects DataFrame.

    Args:
        df_projects: Projects DataFrame containing planned_budget and actual_budget.

    Returns:
        dict[str, float]: Dictionary containing total_planned, total_actual, variance, and burn_rate.
    """
    if df_projects.empty:
        return {"total_planned": 0.0, "total_actual": 0.0, "variance": 0.0, "burn_rate": 0.0}

    total_planned = float(df_projects["planned_budget"].sum())
    total_actual = float(df_projects["actual_budget"].sum())
    variance = total_planned - total_actual
    burn_rate = (total_actual / total_planned * 100.0) if total_planned > 0 else 0.0

    return {
        "total_planned": total_planned,
        "total_actual": total_actual,
        "variance": variance,
        "burn_rate": burn_rate,
    }


# ==============================================================================
# SCREEN 1: PORTFOLIO OVERVIEW
# ==============================================================================
def screen_portfolio_overview() -> None:
    """Renders the Portfolio Overview screen with KPI cards and dynamic project grid."""
    st.header("📊 Portfolio Overview")

    with get_db() as conn:
        df_projects = pd.read_sql(
            "SELECT id, name, status, planned_budget, actual_budget, dynamic_attributes FROM projects",
            conn,
        )

    _, params, _ = load_full_schema()

    if df_projects.empty:
        st.info("No projects registered yet. Go to 'Project Master Data' to create one.")
        return

    # --- 1. PORTFOLIO KPI BANNER ---
    metrics = calculate_portfolio_metrics(df_projects)
    total_planned = metrics["total_planned"]
    total_actual = metrics["total_actual"]
    variance = metrics["variance"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Projects", len(df_projects))
    col2.metric("Total Planned Budget", f"${total_planned:,.2f}")
    col3.metric("Total Actual Spend", f"${total_actual:,.2f}")
    col4.metric(
        "Budget Variance",
        f"${variance:,.2f}",
        delta=f"${variance:,.2f}",
        delta_color="normal" if variance >= 0 else "inverse",
    )

    st.divider()

    # --- 2. DYNAMIC ATTRIBUTE FLATTENING ---
    df_merged = flatten_dynamic_attributes(df_projects, params)

    # --- 3. DYNAMIC COLUMN CONFIGURATION ---
    column_configs: dict[str, Any] = {
        "id": st.column_config.TextColumn("Project Code", help="Unique project identifier", width="small"),
        "name": st.column_config.TextColumn("Project Title", width="medium"),
        "status": st.column_config.TextColumn("Status", width="small"),
        "planned_budget": st.column_config.NumberColumn("Planned ($)", format="$%.2f"),
        "actual_budget": st.column_config.NumberColumn("Actual ($)", format="$%.2f"),
    }

    if not params.empty and "param_id" in params.columns:
        for _, p in params.iterrows():
            pid = str(p["param_id"])
            pname = str(p.get("param_name", pid))
            ptype = str(p.get("param_type", PARAM_TYPE_TEXT))

            if ptype == PARAM_TYPE_URL:
                column_configs[pid] = st.column_config.LinkColumn(
                    label=pname,
                    help=f"Dynamic URL ({pid})",
                    display_text="Open Link ↗",
                )
            elif ptype == PARAM_TYPE_MULTI_ENUM:
                column_configs[pid] = st.column_config.ListColumn(
                    label=pname,
                    help=f"Selected options ({pid})",
                )
            else:
                column_configs[pid] = st.column_config.TextColumn(
                    label=pname,
                    help=f"{ptype} parameter ({pid})",
                )

    # --- 4. FILTERING TOOLBAR ---
    st.subheader("Portfolio Register")

    filter_col1, filter_col2 = st.columns([2, 1])
    search_term = filter_col1.text_input("🔍 Search by Project Code or Name", "")
    all_statuses = df_merged["status"].dropna().unique().tolist()
    status_filter = filter_col2.multiselect(
        "Filter by Status",
        options=all_statuses,
        default=all_statuses,
    )

    # Apply filters
    filtered_df = df_merged[df_merged["status"].isin(status_filter)]
    if search_term.strip():
        term = search_term.lower()
        filtered_df = filtered_df[
            filtered_df["id"].astype(str).str.lower().str.contains(term, na=False)
            | filtered_df["name"].astype(str).str.lower().str.contains(term, na=False)
        ]

    # --- 5. RENDER DATAFRAME ---
    st.dataframe(
        filtered_df,
        column_config=column_configs,
        use_container_width=True,
        hide_index=True,
    )


# ==============================================================================
# SCREEN 2: PROJECT MASTER DATA
# ==============================================================================
def screen_project_master_data() -> None:
    """Renders the Project Master Data screen for creating, editing, and deleting projects."""
    st.header("📋 Project Master Data")

    tab_create, tab_edit = st.tabs(["➕ Create New Project", "✏️ Edit / Delete Existing Project"])
    groups, params, options = load_full_schema()

    # --------------------------------------------------------------------------
    # TAB 1: CREATE PROJECT
    # --------------------------------------------------------------------------
    with tab_create:
        st.subheader("Create a New Project")
        with st.form("form_create_project", clear_on_submit=True):
            col1, col2 = st.columns(2)
            new_id = col1.text_input("Project Code / ID *", placeholder="e.g. PRJ-006")
            new_name = col2.text_input("Project Title *", placeholder="e.g. Cloud Data Lake Platform")

            col3, col4, col5 = st.columns(3)
            new_status = col3.selectbox("Status", options=STATUS_LIST, index=0)
            new_planned = col4.number_input("Planned Budget ($)", min_value=0.0, value=150000.0, step=5000.0)
            new_actual = col5.number_input("Actual Spend ($)", min_value=0.0, value=0.0, step=5000.0)

            st.write("#### 🧩 Dynamic Schema Attributes")
            dyn_values: dict[str, Any] = {}

            if groups.empty or params.empty:
                st.caption("No dynamic schema parameters configured. Add schema in 'Parameters Definition'.")
            else:
                for _, grp in groups.iterrows():
                    gid = grp["id"]
                    gname = grp["group_name"]
                    grp_params = params[params["group_id"] == gid]

                    if grp_params.empty:
                        continue

                    with st.expander(f"📁 {gname}", expanded=True):
                        for _, p in grp_params.iterrows():
                            pid = str(p["param_id"])
                            pname = str(p["param_name"])
                            ptype = str(p["param_type"])

                            if ptype == PARAM_TYPE_TEXT:
                                dyn_values[pid] = st.text_input(pname, key=f"create_{pid}")
                            elif ptype == PARAM_TYPE_URL:
                                dyn_values[pid] = st.text_input(pname, placeholder="https://...", key=f"create_{pid}")
                            elif ptype == PARAM_TYPE_ENUM:
                                p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                dyn_values[pid] = st.selectbox(pname, options=[""] + p_opts, key=f"create_{pid}")
                            elif ptype == PARAM_TYPE_MULTI_ENUM:
                                p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                dyn_values[pid] = st.multiselect(pname, options=p_opts, key=f"create_{pid}")

            btn_submit = st.form_submit_button("💾 Save New Project", use_container_width=True)
            if btn_submit:
                clean_id = new_id.strip()
                clean_name = new_name.strip()

                if not clean_id or not clean_name:
                    st.error("Project Code and Project Title are required.")
                else:
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT id FROM projects WHERE id = ?", (clean_id,))
                        if cursor.fetchone():
                            st.error(f"Project with Code '{clean_id}' already exists. Use a unique Code.")
                        else:
                            cursor.execute(
                                "INSERT INTO projects (id, name, status, planned_budget, actual_budget, dynamic_attributes) VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    clean_id,
                                    clean_name,
                                    new_status,
                                    new_planned,
                                    new_actual,
                                    json.dumps(dyn_values),
                                ),
                            )
                            conn.commit()
                            st.success(f"Project '{clean_id} - {clean_name}' created successfully!")
                            st.rerun()

    # --------------------------------------------------------------------------
    # TAB 2: EDIT / DELETE PROJECT
    # --------------------------------------------------------------------------
    with tab_edit:
        st.subheader("Manage Existing Project")

        with get_db() as conn:
            df_existing = pd.read_sql("SELECT * FROM projects ORDER BY id", conn)

        if df_existing.empty:
            st.info("No projects available to edit.")
            return

        proj_options = df_existing["id"].tolist()
        proj_map = dict(zip(df_existing["id"], df_existing["name"]))

        selected_id = st.selectbox(
            "Select Project",
            options=proj_options,
            format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
        )

        curr_row = df_existing[df_existing["id"] == selected_id].iloc[0]
        try:
            curr_dyn = json.loads(curr_row["dynamic_attributes"]) if curr_row["dynamic_attributes"] else {}
        except json.JSONDecodeError:
            curr_dyn = {}

        with st.form("form_edit_project"):
            col1, col2 = st.columns(2)
            edit_name = col1.text_input("Project Title *", value=str(curr_row["name"]))
            edit_status_idx = STATUS_LIST.index(curr_row["status"]) if curr_row["status"] in STATUS_LIST else 0
            edit_status = col2.selectbox("Status", options=STATUS_LIST, index=edit_status_idx)

            col3, col4 = st.columns(2)
            edit_planned = col3.number_input(
                "Planned Budget ($)",
                min_value=0.0,
                value=float(curr_row["planned_budget"]),
                step=5000.0,
            )
            edit_actual = col4.number_input(
                "Actual Spend ($)",
                min_value=0.0,
                value=float(curr_row["actual_budget"]),
                step=5000.0,
            )

            st.write("#### 🧩 Dynamic Schema Attributes")
            edit_dyn_values: dict[str, Any] = {}

            if not groups.empty and not params.empty:
                for _, grp in groups.iterrows():
                    gid = grp["id"]
                    gname = grp["group_name"]
                    grp_params = params[params["group_id"] == gid]

                    if grp_params.empty:
                        continue

                    with st.expander(f"📁 {gname}", expanded=True):
                        for _, p in grp_params.iterrows():
                            pid = str(p["param_id"])
                            pname = str(p["param_name"])
                            ptype = str(p["param_type"])
                            val = curr_dyn.get(pid)

                            if ptype == PARAM_TYPE_TEXT:
                                edit_dyn_values[pid] = st.text_input(
                                    pname,
                                    value=str(val) if val is not None else "",
                                    key=f"edit_{pid}",
                                )
                            elif ptype == PARAM_TYPE_URL:
                                edit_dyn_values[pid] = st.text_input(
                                    pname,
                                    value=str(val) if val is not None else "",
                                    placeholder="https://...",
                                    key=f"edit_{pid}",
                                )
                            elif ptype == PARAM_TYPE_ENUM:
                                p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                all_opts = [""] + p_opts
                                cur_idx = all_opts.index(val) if val in all_opts else 0
                                edit_dyn_values[pid] = st.selectbox(
                                    pname,
                                    options=all_opts,
                                    index=cur_idx,
                                    key=f"edit_{pid}",
                                )
                            elif ptype == PARAM_TYPE_MULTI_ENUM:
                                p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                cur_multi = val if isinstance(val, list) else ([val] if val else [])
                                valid_multi = [o for o in cur_multi if o in p_opts]
                                edit_dyn_values[pid] = st.multiselect(
                                    pname,
                                    options=p_opts,
                                    default=valid_multi,
                                    key=f"edit_{pid}",
                                )

            btn_update = st.form_submit_button("💾 Update Project Details", use_container_width=True)
            if btn_update:
                if not edit_name.strip():
                    st.error("Project Title is required.")
                else:
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE projects SET name = ?, status = ?, planned_budget = ?, actual_budget = ?, dynamic_attributes = ? WHERE id = ?",
                            (
                                edit_name.strip(),
                                edit_status,
                                edit_planned,
                                edit_actual,
                                json.dumps(edit_dyn_values),
                                selected_id,
                            ),
                        )
                        conn.commit()
                        st.success(f"Project '{selected_id}' updated successfully!")
                        st.rerun()

        st.divider()
        st.write("#### ⚠️ Danger Zone")
        col_del1, col_del2 = st.columns([3, 1])
        confirm_del = col_del1.checkbox(f"Confirm deletion of project '{selected_id}' and all its milestones")
        if col_del2.button("🗑️ Delete Project", type="secondary", disabled=not confirm_del):
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM projects WHERE id = ?", (selected_id,))
                conn.commit()
                st.success(f"Project '{selected_id}' deleted successfully.")
                st.rerun()


# ==============================================================================
# SCREEN 3: PARAMETERS DEFINITION (SCHEMA BUILDER)
# ==============================================================================
def screen_parameters_definition() -> None:
    """Renders the Parameters Definition screen for managing dynamic schema groups, fields, and options."""
    st.header("⚙️ Parameters Definition (Schema Builder)")
    st.caption("Define custom attributes and taxonomies that dynamically render across all projects and portfolios.")

    tab_groups, tab_params, tab_options, tab_preview = st.tabs([
        "📁 Schema Groups",
        "🏷️ Parameters & Fields",
        "🔘 Discrete Enum Options",
        "👁️ Live Schema Tree",
    ])

    groups, params, options = load_full_schema()

    # --------------------------------------------------------------------------
    # TAB 1: SCHEMA GROUPS
    # --------------------------------------------------------------------------
    with tab_groups:
        st.subheader("Manage Schema Groups")
        with st.form("form_add_group"):
            col1, col2 = st.columns([3, 1])
            new_grp_name = col1.text_input("Group Name *", placeholder="e.g. Risk & Compliance")
            new_grp_order = col2.number_input("Display Order", min_value=0, value=len(groups) + 1, step=1)
            btn_add_grp = st.form_submit_button("➕ Add Schema Group")

            if btn_add_grp:
                if not new_grp_name.strip():
                    st.error("Group name cannot be empty.")
                else:
                    try:
                        with get_db() as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                "INSERT INTO schema_groups (group_name, display_order) VALUES (?, ?)",
                                (new_grp_name.strip(), int(new_grp_order)),
                            )
                            conn.commit()
                            st.success(f"Group '{new_grp_name}' added!")
                            st.rerun()
                    except sqlite3.IntegrityError:
                        st.error(f"A group named '{new_grp_name}' already exists.")

        st.write("##### Existing Schema Groups")
        if groups.empty:
            st.info("No groups created yet.")
        else:
            st.dataframe(groups, use_container_width=True, hide_index=True)

            del_grp_id = st.selectbox(
                "Delete Group (Cascades to child parameters)",
                options=groups["id"].tolist(),
                format_func=lambda x: str(groups[groups["id"] == x]["group_name"].iloc[0]),
            )
            if st.button("🗑️ Delete Selected Group", key="btn_del_grp"):
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM schema_groups WHERE id = ?", (del_grp_id,))
                    conn.commit()
                    st.success("Group deleted.")
                    st.rerun()

    # --------------------------------------------------------------------------
    # TAB 2: PARAMETERS & FIELDS
    # --------------------------------------------------------------------------
    with tab_params:
        st.subheader("Manage Schema Parameters")
        if groups.empty:
            st.warning("Please create at least one Schema Group first.")
        else:
            with st.form("form_add_param"):
                col1, col2 = st.columns(2)
                auto_id = generate_param_id()
                new_param_id = col1.text_input("Parameter ID *", value=auto_id, help="Unique identifier key")
                new_param_name = col2.text_input("Parameter Label / Name *", placeholder="e.g. Lead Architect")

                col3, col4 = st.columns(2)
                grp_map = dict(zip(groups["id"], groups["group_name"]))
                selected_gid = col3.selectbox(
                    "Assign to Group *",
                    options=groups["id"].tolist(),
                    format_func=lambda x: f"{x} - {grp_map.get(x, '')}",
                )
                selected_ptype = col4.selectbox("Parameter Data Type *", options=PARAM_TYPES)

                initial_opts = ""
                if selected_ptype in (PARAM_TYPE_ENUM, PARAM_TYPE_MULTI_ENUM):
                    initial_opts = st.text_input(
                        "Initial Option Values (comma-separated)",
                        placeholder="Option 1, Option 2, Option 3",
                    )

                btn_add_param = st.form_submit_button("➕ Add Parameter")
                if btn_add_param:
                    clean_pid = new_param_id.strip()
                    clean_pname = new_param_name.strip()
                    if not clean_pid or not clean_pname:
                        st.error("Parameter ID and Label are required.")
                    else:
                        try:
                            with get_db() as conn:
                                cursor = conn.cursor()
                                cursor.execute(
                                    "INSERT INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES (?, ?, ?, ?)",
                                    (clean_pid, selected_gid, clean_pname, selected_ptype),
                                )

                                # Add initial options if provided
                                if selected_ptype in (PARAM_TYPE_ENUM, PARAM_TYPE_MULTI_ENUM) and initial_opts.strip():
                                    raw_opts = [o.strip() for o in initial_opts.split(",") if o.strip()]
                                    for idx, opt_val in enumerate(raw_opts, 1):
                                        cursor.execute(
                                            "INSERT INTO schema_param_options (param_id, option_value, display_order) VALUES (?, ?, ?)",
                                            (clean_pid, opt_val, idx),
                                        )

                                conn.commit()
                                st.success(f"Parameter '{clean_pid} - {clean_pname}' created successfully!")
                                st.rerun()
                        except sqlite3.IntegrityError:
                            st.error(f"Parameter ID '{clean_pid}' already exists.")

        st.write("##### Existing Parameters")
        if params.empty:
            st.info("No parameters created yet.")
        else:
            params_display = pd.merge(
                params,
                groups.rename(columns={"id": "group_id", "group_name": "Group"}),
                on="group_id",
                how="left",
            )[["param_id", "Group", "param_name", "param_type"]]
            st.dataframe(params_display, use_container_width=True, hide_index=True)

            del_param_id = st.selectbox("Select Parameter to Delete", options=params["param_id"].tolist())
            if st.button("🗑️ Delete Selected Parameter", key="btn_del_param"):
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM schema_parameters WHERE id = ?", (del_param_id,))
                    conn.commit()
                    st.success("Parameter deleted.")
                    st.rerun()

    # --------------------------------------------------------------------------
    # TAB 3: DISCRETE ENUM OPTIONS
    # --------------------------------------------------------------------------
    with tab_options:
        st.subheader("Manage Enum & Multi-Enum Options")
        enum_params = params[params["param_type"].isin([PARAM_TYPE_ENUM, PARAM_TYPE_MULTI_ENUM])]

        if enum_params.empty:
            st.info("No ENUM or MULTI_ENUM parameters configured yet.")
        else:
            p_map = dict(zip(enum_params["param_id"], enum_params["param_name"]))
            target_pid = st.selectbox(
                "Select Enum Parameter",
                options=enum_params["param_id"].tolist(),
                format_func=lambda x: f"{x} - {p_map.get(x, '')}",
            )

            current_opts = options[options["param_id"] == target_pid]
            st.write(f"**Current Options for `{target_pid}`:**")
            if current_opts.empty:
                st.caption("No options configured.")
            else:
                st.dataframe(
                    current_opts[["id", "option_value", "display_order"]],
                    use_container_width=True,
                    hide_index=True,
                )

            with st.form("form_add_opt"):
                col1, col2 = st.columns([3, 1])
                opt_val = col1.text_input("New Option Value *", placeholder="e.g. Critical")
                opt_ord = col2.number_input("Display Order", min_value=0, value=len(current_opts) + 1, step=1)
                btn_add_opt = st.form_submit_button("➕ Add Option")

                if btn_add_opt:
                    if not opt_val.strip():
                        st.error("Option value cannot be empty.")
                    else:
                        with get_db() as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                "INSERT INTO schema_param_options (param_id, option_value, display_order) VALUES (?, ?, ?)",
                                (target_pid, opt_val.strip(), int(opt_ord)),
                            )
                            conn.commit()
                            st.success(f"Option '{opt_val}' added!")
                            st.rerun()

            if not current_opts.empty:
                del_opt_id = st.selectbox(
                    "Delete Option",
                    options=current_opts["id"].tolist(),
                    format_func=lambda x: str(current_opts[current_opts["id"] == x]["option_value"].iloc[0]),
                )
                if st.button("🗑️ Delete Selected Option"):
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM schema_param_options WHERE id = ?", (del_opt_id,))
                        conn.commit()
                        st.success("Option deleted.")
                        st.rerun()

    # --------------------------------------------------------------------------
    # TAB 4: LIVE SCHEMA TREE
    # --------------------------------------------------------------------------
    with tab_preview:
        st.subheader("Schema Hierarchy Explorer")
        if groups.empty:
            st.info("Schema is empty.")
        else:
            for _, grp in groups.iterrows():
                gid = grp["id"]
                st.markdown(f"### 📁 `{grp['group_name']}` (Order: {grp['display_order']})")
                grp_params = params[params["group_id"] == gid]
                if grp_params.empty:
                    st.caption("  *No parameters assigned to this group.*")
                else:
                    for _, p in grp_params.iterrows():
                        pid = p["param_id"]
                        ptype = p["param_type"]
                        pname = p["param_name"]
                        st.markdown(f"- 🏷️ **{pname}** (`{pid}`) — Type: `{ptype}`")
                        if ptype in (PARAM_TYPE_ENUM, PARAM_TYPE_MULTI_ENUM):
                            p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                            if p_opts:
                                st.markdown("  - Options: " + ", ".join([f"`{o}`" for o in p_opts]))
                            else:
                                st.markdown("  - *No options defined.*")
                st.divider()


# ==============================================================================
# SCREEN 4: PLANNING & MILESTONE LOADER
# ==============================================================================
def screen_planning_milestones() -> None:
    """Renders the Planning & Milestone Loader screen with Gantt chart visualization and CSV bulk import."""
    st.header("📅 Planning & Milestone Loader")

    with get_db() as conn:
        df_projects = pd.read_sql("SELECT id, name, status, planned_budget, actual_budget FROM projects ORDER BY id", conn)

    if df_projects.empty:
        st.info("No projects registered yet. Please create a project first in 'Project Master Data'.")
        return

    proj_map = dict(zip(df_projects["id"], df_projects["name"]))
    selected_id = st.selectbox(
        "Select Project to View / Manage Schedule",
        options=df_projects["id"].tolist(),
        format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
    )

    proj_info = df_projects[df_projects["id"] == selected_id].iloc[0]
    col1, col2, col3 = st.columns(3)
    col1.metric("Status", str(proj_info["status"]))
    col2.metric("Planned Budget", f"${float(proj_info['planned_budget']):,.2f}")
    col3.metric("Actual Spend", f"${float(proj_info['actual_budget']):,.2f}")

    st.divider()

    # Load Milestones
    with get_db() as conn:
        df_milestones = pd.read_sql(
            "SELECT id, project_id, task_name, phase, start_date, end_date, progress_pct FROM project_milestones WHERE project_id = ? ORDER BY start_date",
            conn,
            params=(selected_id,),
        )

    # --- 1. GANTT / TIMELINE VISUALIZATION ---
    st.subheader(f"Timeline & Gantt Chart: {selected_id}")
    if df_milestones.empty:
        st.info("No milestones defined for this project yet. Add tasks below or upload a schedule CSV.")
    else:
        df_plot = df_milestones.copy()
        df_plot["start_date"] = pd.to_datetime(df_plot["start_date"])
        df_plot["end_date"] = pd.to_datetime(df_plot["end_date"])

        fig = px.timeline(
            df_plot,
            x_start="start_date",
            x_end="end_date",
            y="task_name",
            color="phase",
            hover_data=["progress_pct"],
            title=f"Milestone Schedule — {proj_info['name']}",
            template="plotly_white",
        )
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(
            height=360,
            margin=dict(l=20, r=20, t=40, b=20),
            xaxis_title="Timeline Date",
            yaxis_title="Tasks / Milestones",
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- 2. ADD MILESTONE FORM ---
    st.subheader("Add Single Milestone")
    with st.form("form_add_milestone", clear_on_submit=True):
        col_t1, col_t2 = st.columns(2)
        task_name = col_t1.text_input("Task / Milestone Name *", placeholder="e.g. UAT Testing")
        phase_name = col_t2.text_input("Phase / Category", value="Phase 1 - Build")

        col_d1, col_d2, col_d3 = st.columns(3)
        today = datetime.date.today()
        start_d = col_d1.date_input("Start Date", value=today)
        end_d = col_d2.date_input("End Date", value=today + datetime.timedelta(days=30))
        prog_val = col_d3.slider("Progress (%)", min_value=0, max_value=100, value=0)

        btn_add_ms = st.form_submit_button("➕ Add Milestone")
        if btn_add_ms:
            if not task_name.strip():
                st.error("Task Name is required.")
            elif start_d > end_d:
                st.error("Start Date cannot be after End Date.")
            else:
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO project_milestones (project_id, task_name, phase, start_date, end_date, progress_pct) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            selected_id,
                            task_name.strip(),
                            phase_name.strip() if phase_name.strip() else "General",
                            start_d.isoformat(),
                            end_d.isoformat(),
                            int(prog_val),
                        ),
                    )
                    conn.commit()
                    st.success("Milestone added successfully!")
                    st.rerun()

    # --- 3. MILESTONE TABLE & ACTIONS ---
    if not df_milestones.empty:
        st.subheader("Milestones Register")
        st.dataframe(
            df_milestones[["id", "task_name", "phase", "start_date", "end_date", "progress_pct"]],
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "task_name": st.column_config.TextColumn("Task Name", width="medium"),
                "phase": st.column_config.TextColumn("Phase", width="small"),
                "start_date": st.column_config.DateColumn("Start Date"),
                "end_date": st.column_config.DateColumn("End Date"),
                "progress_pct": st.column_config.ProgressColumn("Progress", min_value=0, max_value=100, format="%d%%"),
            },
            use_container_width=True,
            hide_index=True,
        )

        col_act1, col_act2 = st.columns([3, 1])
        del_ms_id = col_act1.selectbox(
            "Select Milestone to Delete",
            options=df_milestones["id"].tolist(),
            format_func=lambda x: f"ID {x} - {df_milestones[df_milestones['id'] == x]['task_name'].iloc[0]}",
        )
        if col_act2.button("🗑️ Delete Milestone"):
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM project_milestones WHERE id = ?", (del_ms_id,))
                conn.commit()
                st.success("Milestone deleted.")
                st.rerun()

    # --- 4. CSV BULK LOADER & EXPORTER ---
    st.divider()
    st.subheader("📥 CSV Bulk Loader & Exporter")

    col_exp, col_imp = st.columns(2)
    with col_exp:
        st.write("##### Export Schedule Template")
        template_csv = "task_name,phase,start_date,end_date,progress_pct\nSample Task 1,Phase 1,2026-06-01,2026-06-30,50\nSample Task 2,Phase 2,2026-07-01,2026-08-15,0"
        st.download_button(
            label="📄 Download CSV Template",
            data=template_csv,
            file_name="milestone_template.csv",
            mime="text/csv",
        )

    with col_imp:
        st.write("##### Bulk Import Milestones")
        uploaded_file = st.file_uploader("Upload Milestones CSV", type=["csv"])
        if uploaded_file is not None:
            try:
                df_upload = pd.read_csv(uploaded_file)
                required_cols = {"task_name", "start_date", "end_date"}
                if not required_cols.issubset(set(df_upload.columns)):
                    st.error(f"CSV must include columns: {required_cols}")
                else:
                    st.dataframe(df_upload.head(), use_container_width=True)
                    if st.button("🚀 Import and Save Milestones"):
                        inserted = 0
                        with get_db() as conn:
                            cursor = conn.cursor()
                            for _, row in df_upload.iterrows():
                                cursor.execute(
                                    "INSERT INTO project_milestones (project_id, task_name, phase, start_date, end_date, progress_pct) VALUES (?, ?, ?, ?, ?, ?)",
                                    (
                                        selected_id,
                                        str(row["task_name"]),
                                        str(row.get("phase", "General")),
                                        str(row["start_date"]),
                                        str(row["end_date"]),
                                        int(row.get("progress_pct", 0)),
                                    ),
                                )
                                inserted += 1
                            conn.commit()
                        st.success(f"Successfully imported {inserted} milestones!")
                        st.rerun()
            except Exception as e:
                st.error(f"Error parsing CSV: {e}")


# ==============================================================================
# SCREEN 5: BUDGET TRACKING
# ==============================================================================
def screen_budget_tracking() -> None:
    """Renders the Budget Tracking screen with financial KPIs, variance analytics, and visual breakdown charts."""
    st.header("💰 Budget Tracking & Financial Analytics")

    with get_db() as conn:
        df_projects = pd.read_sql("SELECT id, name, status, planned_budget, actual_budget FROM projects", conn)

    if df_projects.empty:
        st.info("No projects registered yet. Please create projects in 'Project Master Data'.")
        return

    # --- 1. FINANCIAL KPI SUMMARY CARDS ---
    metrics = calculate_portfolio_metrics(df_projects)
    total_planned = metrics["total_planned"]
    total_actual = metrics["total_actual"]
    variance = metrics["variance"]
    burn_rate = metrics["burn_rate"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Portfolio Planned", f"${total_planned:,.2f}")
    col2.metric("Portfolio Actual Spend", f"${total_actual:,.2f}")
    col3.metric(
        "Net Variance",
        f"${variance:,.2f}",
        delta=f"${variance:,.2f}",
        delta_color="normal" if variance >= 0 else "inverse",
    )
    col4.metric("Portfolio Burn Rate", f"{burn_rate:.1f}%")

    if variance < 0:
        st.warning(f"⚠️ Portfolio is currently over budget by **${abs(variance):,.2f}**!")
    else:
        st.success(f"✅ Portfolio financial health is on track with a budget surplus of **${variance:,.2f}**.")

    st.divider()

    # --- 2. PLANNED VS ACTUAL GROUPED BAR CHART ---
    st.subheader("Project-by-Project Planned vs Actual Spend")

    df_melt = df_projects.melt(
        id_vars=["id", "name"],
        value_vars=["planned_budget", "actual_budget"],
        var_name="Budget_Type",
        value_name="Amount",
    )
    df_melt["Budget_Type"] = df_melt["Budget_Type"].map(
        {"planned_budget": "Planned Budget ($)", "actual_budget": "Actual Spend ($)"}
    )
    df_melt["Project_Label"] = df_melt["id"] + " - " + df_melt["name"]

    fig_bar = px.bar(
        df_melt,
        x="Project_Label",
        y="Amount",
        color="Budget_Type",
        barmode="group",
        title="Planned Budget vs Actual Spend by Project",
        template="plotly_white",
        color_discrete_map={
            "Planned Budget ($)": "#2563EB",
            "Actual Spend ($)": "#F59E0B",
        },
    )
    fig_bar.update_layout(
        xaxis_title="Project",
        yaxis_title="Amount ($)",
        legend_title="Type",
        height=380,
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # --- 3. TWO-COLUMN CHARTS: VARIANCE & STATUS ALLOCATION ---
    col_v, col_s = st.columns(2)

    with col_v:
        st.subheader("Budget Variance by Project")
        df_var = df_projects.copy()
        df_var["Variance"] = df_var["planned_budget"] - df_var["actual_budget"]
        df_var["Variance_Color"] = df_var["Variance"].apply(lambda x: "Surplus (Under)" if x >= 0 else "Deficit (Over)")

        fig_var = px.bar(
            df_var,
            x="id",
            y="Variance",
            color="Variance_Color",
            title="Variance ($) [Planned - Actual]",
            template="plotly_white",
            color_discrete_map={
                "Surplus (Under)": "#10B981",
                "Deficit (Over)": "#EF4444",
            },
        )
        fig_var.update_layout(height=350, xaxis_title="Project Code", yaxis_title="Variance ($)")
        st.plotly_chart(fig_var, use_container_width=True)

    with col_s:
        st.subheader("Spend Distribution by Status")
        fig_pie = px.pie(
            df_projects,
            names="status",
            values="actual_budget",
            title="Actual Spend Distribution by Project Status",
            hole=0.45,
            template="plotly_white",
        )
        fig_pie.update_layout(height=350)
        st.plotly_chart(fig_pie, use_container_width=True)

    # --- 4. DETAILED BUDGET HEALTH REGISTER ---
    st.subheader("Project Financial Health Register")
    df_health = df_projects.copy()
    df_health["variance"] = df_health["planned_budget"] - df_health["actual_budget"]
    df_health["burn_rate_pct"] = (
        (df_health["actual_budget"] / df_health["planned_budget"]) * 100.0
    ).fillna(0.0)

    def get_health_tag(row: pd.Series) -> str:
        if row["actual_budget"] > row["planned_budget"]:
            return "🔴 Over Budget"
        if row["burn_rate_pct"] >= 85.0:
            return "🟡 Near Capacity"
        return "🟢 On Track"

    df_health["health_status"] = df_health.apply(get_health_tag, axis=1)

    st.dataframe(
        df_health[["id", "name", "status", "planned_budget", "actual_budget", "variance", "burn_rate_pct", "health_status"]],
        column_config={
            "id": st.column_config.TextColumn("Project Code", width="small"),
            "name": st.column_config.TextColumn("Project Title", width="medium"),
            "status": st.column_config.TextColumn("Status", width="small"),
            "planned_budget": st.column_config.NumberColumn("Planned ($)", format="$%.2f"),
            "actual_budget": st.column_config.NumberColumn("Actual ($)", format="$%.2f"),
            "variance": st.column_config.NumberColumn("Variance ($)", format="$%.2f"),
            "burn_rate_pct": st.column_config.NumberColumn("Burn Rate (%)", format="%.1f%%"),
            "health_status": st.column_config.TextColumn("Financial Health", width="small"),
        },
        use_container_width=True,
        hide_index=True,
    )


# ==============================================================================
# MAIN APPLICATION ROUTING & ENTRYPOINT
# ==============================================================================
def run_app() -> None:
    """Main routing and execution entrypoint for Streamlit UI."""
    init_db()
    seed_default_data_if_empty()

    st.set_page_config(page_title="PPM Studio Pro", page_icon="🏗️", layout="wide")

    st.sidebar.title("📌 PPM Demo Portal")
    page = st.sidebar.radio(
        "Navigation",
        [
            PAGE_PORTFOLIO,
            PAGE_PROJECT_MASTER,
            PAGE_SCHEMA_DEF,
            PAGE_PLANNING,
            PAGE_BUDGET,
        ],
    )

    if page == PAGE_PORTFOLIO:
        screen_portfolio_overview()
    elif page == PAGE_PROJECT_MASTER:
        screen_project_master_data()
    elif page == PAGE_SCHEMA_DEF:
        screen_parameters_definition()
    elif page == PAGE_PLANNING:
        screen_planning_milestones()
    elif page == PAGE_BUDGET:
        screen_budget_tracking()


if __name__ == "__main__" or st.runtime.exists():
    run_app()