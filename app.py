"""PPM Studio Pro - Enterprise Project Portfolio Management Demo Application.

Main entry point and UI routing controller for Streamlit.
"""

import streamlit as st

from src.config import config
from src.database.connection import get_db
from src.database.schema_init import init_db
from src.database.seeder import seed_default_data_if_empty
from src.logging_config import get_logger, setup_logging

DB_NAME: str = config.db_path
from src.models.constants import (
    PAGE_BUDGET,
    PAGE_PLANNING,
    PAGE_PORTFOLIO,
    PAGE_PROJECT_MASTER,
    PAGE_SCHEMA_DEF,
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
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository
from src.services.milestone_service import MilestoneService
from src.services.portfolio_service import PortfolioService
from src.services.schema_service import SchemaService
from src.views.budget_view import render_budget_tracking
from src.views.planning_view import render_planning_milestones
from src.views.portfolio_view import render_portfolio_overview
from src.views.project_master_view import render_project_master
from src.views.schema_def_view import render_schema_definition

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

    st.set_page_config(page_title="PPM Studio Pro", page_icon="🏗️", layout="wide")

    # Instantiate decoupled repositories
    schema_repo = SchemaRepository()
    project_repo = ProjectRepository()
    milestone_repo = MilestoneRepository()

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
        render_portfolio_overview(project_repo, schema_repo)
    elif page == PAGE_PROJECT_MASTER:
        render_project_master(project_repo, schema_repo)
    elif page == PAGE_SCHEMA_DEF:
        render_schema_definition(schema_repo)
    elif page == PAGE_PLANNING:
        render_planning_milestones(project_repo, milestone_repo)
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