"""Streamlit application shell with injected services and page renderers."""

import streamlit as st

from app.application.exceptions import DatabaseMaintenanceError
from app.presentation.components.application_workspace import ApplicationWorkspace
from app.presentation.i18n import SUPPORTED_LOCALES, get_current_locale, set_current_locale, t
from app.presentation.navigation import (
    PAGE_PORTFOLIO,
    PAGE_PLANNING,
    PAGE_SETTINGS,
    PAGE_SCHEMA_DEF,
)
from app.presentation.startup import bootstrap_database


def render_application(workspace: ApplicationWorkspace) -> None:
    """Main routing and execution entrypoint for Streamlit UI."""
    # Pass the version explicitly: default argument changes do not invalidate
    # Streamlit's cached startup result on a development hot reload.
    try:
        bootstrap_database(
            database_identity=workspace.database_identity,
            schema_version=workspace.schema_version,
            force=workspace.force_reseed,
            projects=workspace.seed_projects,
            _service=workspace.maintenance,
        )
    except (DatabaseMaintenanceError, ValueError) as error:
        st.error(str(error))
        return

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
        button[data-testid^="stBaseButton-primary"],
        button[data-testid^="stBaseButton-secondary"],
        [data-testid="stDownloadButton"] button,
        [data-testid="stFormSubmitButton"] button,
        [data-testid="stPopoverButton"] {
            background-color: #C41039 !important;
            border-color: #C41039 !important;
            color: white !important;
        }
        button:disabled { opacity: .5; }
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
            project_id = _positive_identifier(target_proj_id)
            task_id = _positive_identifier(target_task_id)
            if project_id is not None:
                st.session_state["target_planning_project_id"] = project_id
                st.session_state["ms_multi_projects"] = [project_id]
            if task_id is not None:
                st.session_state["target_planning_task_id"] = task_id
        elif target_nav in ("schema", PAGE_SCHEMA_DEF):
            st.session_state["app_sidebar_nav"] = PAGE_SETTINGS
            st.session_state["settings_active_section"] = "parameters"
            st.session_state["rb_settings_section"] = "param_def"
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

    try:
        totals = workspace.maintenance.counts()
    except DatabaseMaintenanceError as error:
        st.error(str(error))
        return
    with st.sidebar:
        st.divider()
        st.caption(t("planning_totals.title", default="Planning totals · entire portfolio"))
        projects_col, tasks_col = st.columns(2)
        projects_col.caption(
            f"{t('planning_totals.projects', default='Total projects')}  \n{totals['projects']:,}"
        )
        tasks_col.caption(
            f"{t('planning_totals.tasks', default='Total tasks')}  \n{totals['tasks']:,}"
        )
        dependencies_col, pools_col = st.columns(2)
        dependencies_col.caption(
            f"{t('planning_totals.dependencies', default='Total dependencies')}  \n{totals['dependencies']:,}"
        )
        pools_col.caption(
            f"{t('planning_totals.pools', default='Total pools')}  \n{totals['pools']:,}"
        )

    st.sidebar.markdown("---")
    with st.sidebar.expander(
        f"⚡ {t('app.seeding_options', default='Database Seeding')}", expanded=False
    ):
        ui_num_projects = st.number_input(
            t("app.seed_projects_count", default="Projects to generate (0 = demo)"),
            min_value=0,
            max_value=10000,
            value=50,
            step=10,
            key="sb_num_projects_input",
            help=t(
                "app.seed_projects_help",
                default="Number of mock projects to generate. Set to 0 to seed only default core templates.",
            ),
        )
        if st.button(
            f"🔄 {t('app.btn_force_reseed', default='Force Re-seed Database')}",
            key="btn_sidebar_force_reseed",
            width="stretch",
        ):
            with st.spinner(t("app.seeding_in_progress", default="Re-seeding database...")):
                try:
                    workspace.maintenance.startup(force=True, projects=int(ui_num_projects))
                    seed_counts = workspace.maintenance.counts()
                except (DatabaseMaintenanceError, ValueError) as error:
                    st.error(str(error))
                    return
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

        from app.presentation.components.allocation_seeding import render_pool_allocation_controls

        render_pool_allocation_controls(workspace.maintenance)

    if "seeding_status_message" in st.session_state:
        st.sidebar.success(st.session_state.pop("seeding_status_message"))

    workspace.pages[page]()


def _positive_identifier(value: str | None) -> int | None:
    """Ignore malformed or nonpositive deep-link identifiers at the UI boundary."""
    try:
        identifier = int(value) if value is not None else 0
    except (ValueError, TypeError):
        return None
    return identifier if identifier > 0 else None
