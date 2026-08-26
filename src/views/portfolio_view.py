"""Screen 1: Portfolio Overview View."""

from typing import Any

import pandas as pd
import streamlit as st

from src.models.constants import PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS, PARAM_TYPE_TEXT, PARAM_TYPE_URL
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository
from src.services.portfolio_service import PortfolioService


def render_portfolio_overview(
    project_repo: ProjectRepository,
    schema_repo: SchemaRepository,
) -> None:
    """Renders the Portfolio Overview screen with KPI cards, filtering, and dynamic table."""
    st.header("📊 Portfolio Overview")

    df_projects = project_repo.get_all_projects()
    params = schema_repo.get_all_parameters()

    if df_projects.empty:
        st.info("No projects registered yet. Go to 'Project Master Data' to create one.")
        return

    # 1. Financial KPI Summary Banner
    metrics = PortfolioService.calculate_portfolio_metrics(df_projects)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Projects", metrics.total_projects)
    col2.metric("Total Planned Budget", f"${metrics.total_planned:,.2f}")
    col3.metric("Total Actual Spend", f"${metrics.total_actual:,.2f}")
    col4.metric(
        "Budget Variance",
        f"${metrics.variance:,.2f}",
        delta=f"${metrics.variance:,.2f}",
        delta_color="normal" if metrics.variance >= 0 else "inverse",
    )

    st.divider()

    # 2. Dynamic Attribute Unpacking
    df_merged = PortfolioService.flatten_dynamic_attributes(df_projects, params)

    # 3. Dynamic Column Configuration
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
            elif ptype in (PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS):
                column_configs[pid] = st.column_config.ListColumn(
                    label=pname,
                    help=f"Tags / Multi-selection ({pid})",
                )
            else:
                column_configs[pid] = st.column_config.TextColumn(
                    label=pname,
                    help=f"{ptype} parameter ({pid})",
                )

    # 4. Search & Status Filtering Toolbar
    st.subheader("Portfolio Register")
    filter_col1, filter_col2 = st.columns([2, 1])
    search_term = filter_col1.text_input("🔍 Search by Project Code or Name", "")
    all_statuses = df_merged["status"].dropna().unique().tolist()
    status_filter = filter_col2.multiselect(
        "Filter by Status",
        options=all_statuses,
        default=all_statuses,
    )

    filtered_df = df_merged[df_merged["status"].isin(status_filter)]
    if search_term.strip():
        term = search_term.lower()
        filtered_df = filtered_df[
            filtered_df["id"].astype(str).str.lower().str.contains(term, na=False)
            | filtered_df["name"].astype(str).str.lower().str.contains(term, na=False)
        ]

    # 5. Render Data Grid
    st.dataframe(
        filtered_df,
        column_config=column_configs,
        width="stretch",
        hide_index=True,
    )
