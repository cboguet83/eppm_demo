"""PPM Studio Pro - Enterprise Project Portfolio Management Demo Application.

Main entry point and UI routing controller for Streamlit.
"""

import importlib

import streamlit as st
import streamlit.components.v1 as components

import src.i18n.translator as _i18n_module
import src.models.constants as _constants_module
import src.models.organization as _org_models_module
import src.repositories.milestone_repo as _milestone_repo_module
import src.repositories.organization_repo as _organization_repo_module
import src.repositories.project_repo as _project_repo_module
import src.repositories.schema_repo as _schema_repo_module
import src.services.milestone_service as _milestone_service_module
import src.services.organization_service as _organization_service_module
import src.services.portfolio_service as _portfolio_service_module
import src.services.schema_service as _schema_service_module
import src.views.budget_view as _budget_module
import src.views.planning_view as _planning_module
import src.views.portfolio_view as _portfolio_module
import src.views.project_master_view as _project_master_module
import src.views.schema_def_view as _schema_def_module
import src.views.settings_view as _settings_module

importlib.reload(_constants_module)
importlib.reload(_org_models_module)
importlib.reload(_i18n_module)
importlib.reload(_project_repo_module)
importlib.reload(_milestone_repo_module)
importlib.reload(_schema_repo_module)
importlib.reload(_organization_repo_module)
importlib.reload(_portfolio_service_module)
importlib.reload(_milestone_service_module)
importlib.reload(_schema_service_module)
importlib.reload(_organization_service_module)
importlib.reload(_portfolio_module)
importlib.reload(_project_master_module)
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
    PAGE_PROJECT_MASTER,
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

PortfolioService = _portfolio_service_module.PortfolioService
MilestoneService = _milestone_service_module.MilestoneService
SchemaService = _schema_service_module.SchemaService
OrganizationService = _organization_service_module.OrganizationService

render_portfolio_overview = _portfolio_module.render_portfolio_overview
render_project_master = _project_master_module.render_project_master
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
def run_app() -> None:
    """Main routing and execution entrypoint for Streamlit UI."""
    init_db()
    seed_default_data_if_empty()

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
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Instantiate decoupled repositories
    schema_repo = SchemaRepository()
    project_repo = ProjectRepository()
    milestone_repo = MilestoneRepository()
    org_repo = OrganizationRepository()

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
        PAGE_PROJECT_MASTER: f"2. 📁 {t('nav.master_data')}",
        PAGE_SCHEMA_DEF: f"3. 🧩 {t('nav.schema')}",
        PAGE_PLANNING: f"4. 📅 {t('nav.planning')}",
        PAGE_SETTINGS: f"5. ⚙️ {t('nav.settings', default='Organization & Settings')}",
    }

    page_keys = [PAGE_PORTFOLIO, PAGE_PROJECT_MASTER, PAGE_SCHEMA_DEF, PAGE_PLANNING, PAGE_SETTINGS]
    page = st.sidebar.radio(
        t("app.sidebar_nav", default="Navigation"),
        page_keys,
        format_func=lambda k: nav_map.get(k, k),
    )

    if page == PAGE_PORTFOLIO:
        render_portfolio_overview(project_repo, schema_repo)
    elif page == PAGE_PROJECT_MASTER:
        render_project_master(project_repo, schema_repo)
    elif page == PAGE_SCHEMA_DEF:
        render_schema_definition(schema_repo)
    elif page == PAGE_PLANNING:
        render_planning_milestones(project_repo, milestone_repo)
    elif page == PAGE_SETTINGS:
        render_settings_view(org_repo)
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


if __name__ == "__main__" or st.runtime.exists():
    run_app()