"""Screen 1: Portfolio Overview View."""

from typing import Any

import pandas as pd
import streamlit as st

from src.i18n import t
from src.models.constants import (
    PARAM_TYPE_DATE,
    PARAM_TYPE_HYPERLINK,
    PARAM_TYPE_MULTI_ENUM,
    PARAM_TYPE_NUMBER,
    PARAM_TYPE_TAGS,
    PARAM_TYPE_TEXT,
    PARAM_TYPE_URL,
)
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository
from src.services.portfolio_service import PortfolioService


def render_portfolio_overview(
    project_repo: ProjectRepository,
    schema_repo: SchemaRepository,
) -> None:
    """Renders the Portfolio Overview screen with KPI cards, filtering, and dynamic table."""
    st.header(f"📊 {t('portfolio.title')}")

    df_projects = project_repo.get_all_projects()
    params = schema_repo.get_all_parameters()

    if df_projects.empty:
        st.info(t("master_data.dynamic_empty", default="No projects registered yet."))
        return

    # 1. Financial KPI Summary Banner
    metrics = PortfolioService.calculate_portfolio_metrics(df_projects)
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric(t("portfolio.kpi_total_projects"), metrics.total_projects)
    col2.metric(t("portfolio.kpi_planned_budget"), f"€{metrics.total_planned:,.2f}")
    col3.metric(t("portfolio.kpi_actual_spend"), f"€{metrics.total_actual:,.2f}")
    col4.metric(
        t("portfolio.kpi_variance"),
        f"€{metrics.variance:,.2f}",
        delta=f"€{metrics.variance:,.2f}",
        delta_color="normal" if metrics.variance >= 0 else "inverse",
    )
    col5.metric(t("portfolio.kpi_burn_rate"), f"{metrics.burn_rate:.1f}%")

    st.divider()

    # 2. Dynamic Attribute Unpacking
    df_merged = PortfolioService.flatten_dynamic_attributes(df_projects, params)

    # Map project manager function name
    org_repo = OrganizationRepository(project_repo.db_path)
    df_funcs = org_repo.get_all_functions()
    func_name_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    if "function_id" in df_merged.columns:
        df_merged["project_manager"] = df_merged["function_id"].map(func_name_map).fillna("—")
    else:
        df_merged["project_manager"] = "—"

    # 3. Dynamic Column Configuration
    column_configs: dict[str, Any] = {
        "id": st.column_config.TextColumn(t("portfolio.col_id"), help="Unique project identifier", width="small"),
        "name": st.column_config.TextColumn(t("portfolio.col_name"), width="medium"),
        "project_manager": st.column_config.TextColumn(
            t("master_data.field_project_manager", default="Project Manager"),
            help="Project Manager",
            width="medium",
        ),
        "status": st.column_config.TextColumn(t("portfolio.col_status"), width="small"),
        "planned_budget": st.column_config.NumberColumn(t("portfolio.col_planned"), format="€%.2f"),
        "actual_budget": st.column_config.NumberColumn(t("portfolio.col_actual"), format="€%.2f"),
    }

    if not params.empty and "param_id" in params.columns:
        for _, p in params.iterrows():
            pid = str(p["param_id"])
            pname = str(p.get("param_name", pid))
            ptype = str(p.get("param_type", PARAM_TYPE_TEXT)).upper()

            if ptype in (PARAM_TYPE_URL, PARAM_TYPE_HYPERLINK):
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
            elif ptype == PARAM_TYPE_DATE:
                column_configs[pid] = st.column_config.TextColumn(
                    label=pname,
                    help=f"Date ({pid})",
                )
            elif ptype == PARAM_TYPE_NUMBER:
                column_configs[pid] = st.column_config.NumberColumn(
                    label=pname,
                    help=f"Number ({pid})",
                )
            else:
                column_configs[pid] = st.column_config.TextColumn(
                    label=pname,
                    help=f"{ptype} parameter ({pid})",
                )

    # 4. Search & Status Filtering Toolbar
    filter_col1, filter_col2 = st.columns([2, 1])
    search_term = filter_col1.text_input(t("portfolio.filter_search"), placeholder=t("portfolio.filter_search_placeholder"))
    all_statuses = df_merged["status"].dropna().unique().tolist()
    status_filter = filter_col2.multiselect(
        t("portfolio.filter_status"),
        options=all_statuses,
        default=[],
        placeholder=t("portfolio.filter_all"),
    )

    filtered_df = df_merged.copy()
    if status_filter:
        filtered_df = filtered_df[filtered_df["status"].isin(status_filter)]

    if search_term.strip():
        term = search_term.lower()
        filtered_df = filtered_df[
            filtered_df["id"].astype(str).str.lower().str.contains(term, na=False)
            | filtered_df["name"].astype(str).str.lower().str.contains(term, na=False)
        ]

    # 5. Render Data Grid
    st.subheader(t("portfolio.table_header", count=len(filtered_df)))
    st.dataframe(
        filtered_df,
        column_config=column_configs,
        width="stretch",
        hide_index=True,
    )
