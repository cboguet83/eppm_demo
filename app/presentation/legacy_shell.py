"""PPM Studio Pro - Enterprise Project Portfolio Management Demo Application.

Transitional Streamlit shell. Migrate one feature at a time; new feature logic
belongs in app.application and app.domain. Startup delegates here from app.main.
"""

import importlib

import streamlit as st
import streamlit.components.v1 as components

import src.i18n.translator as _i18n_module
import src.database.schema_init as _schema_init_module
import src.models.constants as _constants_module
import src.models.organization as _org_models_module
import src.repositories.milestone_repo as _milestone_repo_module
import src.repositories.organization_repo as _organization_repo_module
import src.repositories.project_repo as _project_repo_module
import src.repositories.project_collaboration_repo as _project_collaboration_repo_module
import src.repositories.portfolio_repo as _portfolio_repo_module
import src.repositories.resource_pool_repo as _resource_pool_repo_module
import src.repositories.schema_repo as _schema_repo_module
import src.repositories.tag_repo as _tag_repo_module
import src.services.milestone_service as _milestone_service_module
import src.services.organization_service as _organization_service_module
import src.services.portfolio_service as _portfolio_service_module
import src.services.project_overallocation as _project_overallocation_module
import src.services.planning_data as _planning_data_module
import src.services.resource_pool_service as _resource_pool_service_module
import src.services.schema_service as _schema_service_module
import src.services.tag_service as _tag_service_module
import src.views.budget_view as _budget_module
import src.views.project_dialogs as _project_dialogs_module
import src.views.project_collaboration_view as _project_collaboration_module
import src.views.planning_view as _planning_module
import src.views.portfolio_view as _portfolio_module
import src.views.portfolio_table_component as _portfolio_table_module
import src.views.schema_def_view as _schema_def_module
import src.views.settings_view as _settings_module

importlib.reload(_constants_module)
importlib.reload(_org_models_module)
importlib.reload(_i18n_module)
importlib.reload(_schema_init_module)
importlib.reload(_project_repo_module)
importlib.reload(_project_collaboration_repo_module)
importlib.reload(_portfolio_repo_module)
importlib.reload(_milestone_repo_module)
importlib.reload(_schema_repo_module)
importlib.reload(_organization_repo_module)
importlib.reload(_resource_pool_repo_module)
importlib.reload(_tag_repo_module)
importlib.reload(_portfolio_service_module)
importlib.reload(_project_overallocation_module)
importlib.reload(_milestone_service_module)
importlib.reload(_schema_service_module)
importlib.reload(_organization_service_module)
importlib.reload(_resource_pool_service_module)
importlib.reload(_tag_service_module)
importlib.reload(_planning_data_module)
importlib.reload(_project_dialogs_module)
importlib.reload(_project_collaboration_module)
importlib.reload(_portfolio_table_module)
importlib.reload(_portfolio_module)
importlib.reload(_schema_def_module)
importlib.reload(_planning_module)
importlib.reload(_settings_module)
importlib.reload(_budget_module)


from src.config import config
from src.database.connection import get_db
from src.database.schema_init import init_db
from src.database.seeder import seed_default_data_if_empty
from src.i18n import SUPPORTED_LOCALES, get_current_locale, set_current_locale, t
from src.logging_config import get_logger, setup_logging
from src.models.constants import (
    PAGE_BUDGET,
    PAGE_PLANNING,
    PAGE_PORTFOLIO,
    PAGE_SCHEMA_DEF,
    PAGE_SETTINGS,
    PARAM_TYPE_ENUM,
    PARAM_TYPE_MULTI_ENUM,
    PARAM_TYPE_TAGS,
    PARAM_TYPE_TEXT,
    PARAM_TYPE_URL,
    PARAM_TYPES,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_DRAFT,
    STATUS_IN_PROGRESS,
    STATUS_LIST,
    STATUS_ON_HOLD,
)

ProjectRepository = _project_repo_module.ProjectRepository
MilestoneRepository = _milestone_repo_module.MilestoneRepository
SchemaRepository = _schema_repo_module.SchemaRepository
OrganizationRepository = _organization_repo_module.OrganizationRepository
TagRepository = _tag_repo_module.TagRepository
ResourcePoolRepository = _resource_pool_repo_module.ResourcePoolRepository

PortfolioService = _portfolio_service_module.PortfolioService
MilestoneService = _milestone_service_module.MilestoneService
SchemaService = _schema_service_module.SchemaService
OrganizationService = _organization_service_module.OrganizationService
TagService = _tag_service_module.TagService
ResourcePoolService = _resource_pool_service_module.ResourcePoolService

render_portfolio_overview = _portfolio_module.render_portfolio_overview
render_schema_definition = _schema_def_module.render_schema_definition
render_planning_milestones = _planning_module.render_planning_milestones
render_settings_view = _settings_module.render_settings_view
render_budget_tracking = _budget_module.render_budget_tracking

DB_NAME: str = config.db_path

# Configure logging
setup_logging()
logger = get_logger("app")


# ==============================================================================
# MAIN APPLICATION ROUTING & ENTRYPOINT
# ==============================================================================
def parse_cli_args() -> tuple[bool, int]:
    """Parses command-line arguments for force seeding and project counts.

    Returns:
        tuple[bool, int]: (force_reseed, seed_projects_count)
    """
    import argparse

    parser = argparse.ArgumentParser(description="PPM Studio Pro", add_help=False)
    parser.add_argument(
        "--force-reseed",
        "--force",
        "-f",
        action="store_true",
        default=False,
        help="Force re-seeding the database on startup.",
    )
    parser.add_argument(
        "--projects",
        "-n",
        "--seed-projects",
        type=int,
        default=0,
        help="Number of mock projects to generate if force seeding.",
    )
    args, _ = parser.parse_known_args()
    return bool(args.force_reseed), int(args.projects)


def _get_database_seed_counts(db_path: str) -> dict[str, int]:
    """Return the persisted project, task, and dependency totals after seeding."""
    with get_db(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM project),
                (SELECT COUNT(*) FROM project_task),
                (SELECT COUNT(*) FROM task_dependencies),
                (SELECT COUNT(*) FROM project_type),
                (SELECT COUNT(*) FROM project_property_value)
            """
        ).fetchone()
    return {
        "projects": int(row[0]),
        "tasks": int(row[1]),
        "dependencies": int(row[2]),
        "project_types": int(row[3]),
        "property_values": int(row[4]),
    }


def _get_planning_totals(db_path: str) -> dict[str, int]:
    """Read global planning counts in one query without loading table contents."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT (SELECT COUNT(*) FROM project), "
            "(SELECT COUNT(*) FROM project_task), "
            "(SELECT COUNT(*) FROM task_dependencies), "
            "(SELECT COUNT(*) FROM resource_pool)"
        ).fetchone()
    return dict(zip(("projects", "tasks", "dependencies", "pools"), map(int, row)))


@st.cache_resource
def bootstrap_database(schema_version: str = "project-collaboration-v1") -> bool:
    """Initializes the database schema and performs seeding on server startup.

    Guarantees execution runs exactly once per container/process lifecycle,
    preventing destructive re-seeding on Streamlit script reruns.
    The schema version invalidates the startup cache when database migrations change.
    """
    init_db()
    cli_force, cli_projects = parse_cli_args()
    force = config.force_reseed or cli_force
    num_projects = cli_projects if cli_projects > 0 else config.seed_projects_count

    if force:
        logger.info("Force re-seeding active (projects=%d)...", num_projects)
        if num_projects > 0:
            try:
                from scripts.seed_database import seed_database

                seed_database(
                    num_projects=num_projects,
                    db_path=config.db_path,
                    clean_first=True,
                )
            except Exception as exc:
                logger.error(
                    "Failed to seed %d projects: %s. Stopping; the pre-seed backup is retained.",
                    num_projects,
                    exc,
                )
                raise
        else:
            seed_default_data_if_empty(force=True)
    else:
        seed_default_data_if_empty(force=False)
    return True


def run_app() -> None:
    """Main routing and execution entrypoint for Streamlit UI."""
    # Pass the version explicitly: default argument changes do not invalidate
    # Streamlit's cached startup result on a development hot reload.
    bootstrap_database(schema_version="project-collaboration-v1")



    st.set_page_config(
        page_title=t("app.title", default="PPM Studio Pro"),
        page_icon="🏗️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Clean Streamlit UI elements without breaking sidebar controls
    st.markdown(
        """
        <style>
        .stDeployButton, [data-testid="stDeployButton"], .stAppDeployButton, [data-testid="stDecoration"] {
            display: none !important;
            visibility: hidden !important;
        }
        #MainMenu { visibility: hidden; }
        footer { visibility: hidden; }

        /* Reduce top whitespace across all views */
        .block-container {
            padding-top: 1.5rem !important;
        }

        /* Ensure native Streamlit sidebar collapse/expand controls are always accessible */
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapseButton"] {
            visibility: visible !important;
            display: flex !important;
            opacity: 1 !important;
            z-index: 1000 !important;
            pointer-events: auto !important;
        }

        /* Multiselect selected tag pills styled with #C41039 */
        div[data-baseweb="tag"],
        span[data-baseweb="tag"],
        [data-testid="stMultiSelect"] div[data-baseweb="tag"],
        [data-testid="stMultiSelect"] span[data-baseweb="tag"],
        [data-testid="stMultiSelectTag"],
        [data-baseweb="tag"] {
            background-color: #FDE8EC !important;
            background: #FDE8EC !important;
            border: 1px solid #C41039 !important;
            border-radius: 6px !important;
        }
        div[data-baseweb="tag"] *,
        span[data-baseweb="tag"] *,
        [data-testid="stMultiSelect"] div[data-baseweb="tag"] *,
        [data-testid="stMultiSelect"] span[data-baseweb="tag"] *,
        [data-testid="stMultiSelectTag"] * {
            color: #C41039 !important;
            fill: #C41039 !important;
        }
        div[data-baseweb="tag"] span,
        span[data-baseweb="tag"] span,
        [data-testid="stMultiSelect"] [data-baseweb="tag"] span {
            color: #C41039 !important;
            font-weight: 600 !important;
        }
        div[data-baseweb="tag"] svg,
        span[data-baseweb="tag"] svg,
        [data-baseweb="tag"] svg path {
            fill: #C41039 !important;
            color: #C41039 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Instantiate decoupled repositories
    schema_repo = SchemaRepository()
    project_repo = ProjectRepository()
    milestone_repo = MilestoneRepository()
    org_repo = OrganizationRepository()
    tag_repo = TagRepository()
    pool_repo = ResourcePoolRepository()

    # Language Switcher at top of sidebar
    current_loc = get_current_locale()
    locale_codes = list(SUPPORTED_LOCALES.keys())
    current_idx = locale_codes.index(current_loc) if current_loc in locale_codes else 0

    def on_language_change() -> None:
        new_loc = st.session_state.get("app_language_selector", "en")
        set_current_locale(new_loc)

    selected_loc = st.sidebar.selectbox(
        t("app.language_selector", default="🌐 Language"),
        options=locale_codes,
        format_func=lambda c: SUPPORTED_LOCALES.get(c, c),
        index=current_idx,
        key="app_language_selector",
        on_change=on_language_change,
    )
    if selected_loc != current_loc:
        set_current_locale(selected_loc)
        st.rerun()

    st.sidebar.title(f"📌 {t('app.title', default='PPM Demo Portal')}")

    nav_map = {
        PAGE_PORTFOLIO: f"1. 📊 {t('nav.portfolio')}",
        PAGE_PLANNING: f"2. 📅 {t('nav.planning')}",
        PAGE_SETTINGS: f"3. ⚙️ {t('nav.settings', default='Settings')}",
    }

    page_keys = [PAGE_PORTFOLIO, PAGE_PLANNING, PAGE_SETTINGS]

    # Deep-link routing via URL query parameters (e.g. ?nav=planning&project_id=123)
    if "nav" in st.query_params:
        target_nav = st.query_params.get("nav")
        target_proj_id = st.query_params.get("project_id")
        target_task_id = st.query_params.get("task_id")

        if target_nav in ("planning", PAGE_PLANNING):
            st.session_state["app_sidebar_nav"] = PAGE_PLANNING
            if target_proj_id:
                try:
                    p_id_int = int(target_proj_id)
                    st.session_state["target_planning_project_id"] = p_id_int
                    st.session_state["ms_multi_projects"] = [p_id_int]
                except (ValueError, TypeError):
                    pass
            if target_task_id:
                try:
                    st.session_state["target_planning_task_id"] = int(target_task_id)
                except (ValueError, TypeError):
                    pass
        elif target_nav in ("schema", PAGE_SCHEMA_DEF):
            st.session_state["app_sidebar_nav"] = PAGE_SETTINGS
            st.session_state["settings_active_section"] = "parameters"
        elif target_nav in page_keys:
            st.session_state["app_sidebar_nav"] = target_nav

        st.query_params.clear()

    if "nav_redirect" in st.session_state and st.session_state["nav_redirect"]:
        st.session_state["app_sidebar_nav"] = st.session_state.pop("nav_redirect")
    if st.session_state.get("app_sidebar_nav") not in page_keys:
        st.session_state["app_sidebar_nav"] = PAGE_PORTFOLIO

    page = st.sidebar.radio(
        t("app.sidebar_nav", default="Navigation"),
        page_keys,
        format_func=lambda k: nav_map.get(k, k),
        key="app_sidebar_nav",
    )

    totals = _get_planning_totals(config.db_path)
    with st.sidebar:
        st.divider()
        st.caption(t("planning_totals.title", default="Planning totals · entire portfolio"))
        projects_col, tasks_col = st.columns(2)
        projects_col.caption(f"{t('planning_totals.projects', default='Total projects')}  \n{totals['projects']:,}")
        tasks_col.caption(f"{t('planning_totals.tasks', default='Total tasks')}  \n{totals['tasks']:,}")
        dependencies_col, pools_col = st.columns(2)
        dependencies_col.caption(f"{t('planning_totals.dependencies', default='Total dependencies')}  \n{totals['dependencies']:,}")
        pools_col.caption(f"{t('planning_totals.pools', default='Total pools')}  \n{totals['pools']:,}")

    st.sidebar.markdown("---")
    with st.sidebar.expander(f"⚡ {t('app.seeding_options', default='Database Seeding')}", expanded=False):
        ui_num_projects = st.number_input(
            t("app.seed_projects_count", default="Projects to generate (0 = demo)"),
            min_value=0,
            max_value=10000,
            value=50,
            step=10,
            key="sb_num_projects_input",
            help=t("app.seed_projects_help", default="Number of mock projects to generate. Set to 0 to seed only default core templates."),
        )
        if st.button(
            f"🔄 {t('app.btn_force_reseed', default='Force Re-seed Database')}",
            key="btn_sidebar_force_reseed",
            width="stretch",
        ):
            with st.spinner(t("app.seeding_in_progress", default="Re-seeding database...")):
                if ui_num_projects > 0:
                    from scripts.seed_database import seed_database

                    seed_database(num_projects=int(ui_num_projects), db_path=config.db_path, clean_first=True)
                else:
                    seed_default_data_if_empty(force=True)
                seed_counts = _get_database_seed_counts(config.db_path)
                st.cache_resource.clear()
                st.cache_data.clear()
                st.session_state["seeding_status_message"] = t(
                    "project_types.seed_success",
                    default=(
                        "Database successfully re-seeded: {projects} projects, "
                        "{tasks} tasks, and {dependencies} dependencies created."
                    ),
                    **seed_counts,
                )
                st.rerun()

    if "seeding_status_message" in st.session_state:
        st.sidebar.success(st.session_state.pop("seeding_status_message"))

    if page == PAGE_PORTFOLIO:
        render_portfolio_overview(project_repo, schema_repo)
    elif page == PAGE_PLANNING:
        render_planning_milestones(
            project_repo,
            milestone_repo,
            tag_repo,
            pool_repo,
            org_repo,
            schema_repo,
        )
    elif page in (PAGE_SETTINGS, PAGE_SCHEMA_DEF):
        render_settings_view(org_repo, tag_repo, project_repo, milestone_repo, pool_repo, schema_repo)
    elif page == PAGE_BUDGET:
        render_budget_tracking(project_repo)



# Backward-compatibility aliases for external scripts/tests
generate_param_id = SchemaService.generate_param_id
get_next_available_group_order = SchemaService.get_next_available_group_order
calculate_portfolio_metrics = PortfolioService.calculate_portfolio_metrics
flatten_dynamic_attributes = PortfolioService.flatten_dynamic_attributes


def load_full_schema(db_path=None):
    """Loads all schema tables (backward compatibility alias)."""
    repo = SchemaRepository(db_path)
    return repo.get_all_groups(), repo.get_all_parameters(), repo.get_all_options()


if __name__ == "__main__":
    if not st.runtime.exists():
        import sys

        if "-h" in sys.argv or "--help" in sys.argv:
            print("PPM Studio Pro CLI")
            print("Usage: python app.py [OPTIONS]")
            print("\nOptions:")
            print("  -f, --force, --force-reseed   Force re-seeding the database.")
            print("  -n, --projects <COUNT>        Number of mock projects to generate.")
            print("  -h, --help                    Show this help message and exit.")
            sys.exit(0)

        cli_force, cli_projects = parse_cli_args()
        if cli_force or cli_projects > 0:
            init_db()
            target_projects = cli_projects if cli_projects > 0 else config.seed_projects_count
            if target_projects > 0:
                from scripts.seed_database import seed_database

                print(f"Force re-seeding database with {target_projects} projects at {config.db_path}...")
                seed_database(num_projects=target_projects, db_path=config.db_path, clean_first=True)
            else:
                print(f"Force re-seeding default data at {config.db_path}...")
                seed_default_data_if_empty(force=True)
            print("Database seeding completed successfully.")
            sys.exit(0)
        else:
            run_app()
    else:
        run_app()
