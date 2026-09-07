"""Screen 1: Portfolio Overview View with Interactive Master List and Details Inspection."""

import json
from typing import Any, Optional

import pandas as pd
import streamlit as st

from src.i18n import t
from src.models.constants import (
    PAGE_PROJECT_MASTER,
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
from src.services.organization_service import OrganizationService
from src.services.portfolio_service import PortfolioService

ALLOWED_DYNAMIC_PARAMS: set[str] = {
    "phase",
    "code_station",
    "code_line",
    "strategic_priority",
    "category",
    "category_tags",
    "complexity",
}


def _render_project_details_panel(
    selected_proj: pd.Series,
    params: pd.DataFrame,
    project_repo: ProjectRepository,
) -> None:
    """Renders the detailed inspection panel below the Projects Master List for the selected project.

    Args:
        selected_proj: Series containing the selected project's attributes.
        params: Schema parameters DataFrame.
        project_repo: ProjectRepository instance.
    """
    proj_id = selected_proj["id"]
    proj_name = selected_proj["name"]
    proj_status = selected_proj.get("status", "—")
    pm_name = selected_proj.get("project_manager", "—")
    l3_name = selected_proj.get("level_3_manager_name", "—")
    planned = float(selected_proj.get("planned_budget", 0.0))
    actual = float(selected_proj.get("actual_budget", 0.0))
    variance = planned - actual
    burn_rate = (actual / planned * 100.0) if planned > 0 else 0.0

    raw_dyn = selected_proj.get("dynamic_attributes", "{}")
    dyn_dict: dict[str, Any] = {}
    if isinstance(raw_dyn, dict):
        dyn_dict = raw_dyn
    elif isinstance(raw_dyn, str) and raw_dyn.strip():
        try:
            dyn_dict = json.loads(raw_dyn)
        except (json.JSONDecodeError, TypeError):
            dyn_dict = {}

    st.markdown("---")
    head_c1, head_c2 = st.columns([4, 1])
    with head_c1:
        st.subheader(f"📌 {t('portfolio.details_title', default='Project Details')}: #{proj_id} — {proj_name}")
    with head_c2:
        if st.button(
            f"✏️ {t('portfolio.btn_open_in_master', default='Edit in Master Data')}",
            key=f"btn_edit_master_{proj_id}",
            use_container_width=True,
        ):
            st.session_state["target_edit_project_id"] = proj_id
            st.session_state["nav_redirect"] = PAGE_PROJECT_MASTER
            st.rerun()

    # KPI Summary Cards
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric(t("portfolio.col_status", default="Status"), str(proj_status))
    m2.metric(t("master_data.field_project_manager", default="Project Manager"), str(pm_name))
    m3.metric(t("portfolio.filter_level_3_manager", default="Managing Func (L3)"), str(l3_name))
    m4.metric(t("portfolio.col_planned", default="Planned (€)"), f"€{planned:,.2f}")
    m5.metric(t("portfolio.col_actual", default="Actual (€)"), f"€{actual:,.2f}")
    m6.metric(
        t("portfolio.kpi_variance", default="Variance"),
        f"€{variance:,.2f}",
        delta=f"{burn_rate:.1f}% burn",
        delta_color="normal" if variance >= 0 else "inverse",
    )

    # Detailed Categorized Tabs
    t_basic, t_loc, t_links, t_class = st.tabs([
        f"📋 {t('portfolio.tab_details_basic', default='Basic & Scoping')}",
        f"📍 {t('portfolio.tab_details_localization', default='Localization')}",
        f"🔗 {t('portfolio.tab_details_links', default='Useful Links')}",
        f"🏷️ {t('portfolio.tab_details_classification', default='Classification')}",
    ])

    def _get_val(key: str, alias: str = "") -> str:
        v = dyn_dict.get(key)
        if v is None and alias:
            v = dyn_dict.get(alias)
        if v is None:
            return "—"
        if isinstance(v, list):
            return ", ".join(str(item) for item in v) if v else "—"
        return str(v) if str(v).strip() else "—"

    with t_basic:
        b1, b2 = st.columns(2)
        with b1:
            st.markdown(f"**Code Courrier:** `{_get_val('code courrier', 'Code Courrier')}`")
            st.markdown(f"**Lot:** `{_get_val('lot', 'Lot')}`")
            st.markdown(f"**Phase:** `{_get_val('phase', 'Phase')}`")
            st.markdown(f"**Start Date:** `{_get_val('start_date', 'Start Date')}`")
            st.markdown(f"**Stop Date:** `{_get_val('stop_Date', 'Stop Date')}`")
            st.markdown(f"**Description:** {_get_val('description', 'Description')}")
            st.markdown(f"**Commentaire:** {_get_val('commentaire', 'Commentaire')}")
        with b2:
            st.markdown(f"**Benefits:** {_get_val('benefits', 'Benefits')}")
            st.markdown(f"**Acceptance Criteria:** {_get_val('acceptance_ctriteria', 'Acceptance Criteria')}")
            st.markdown(f"**Scope:** {_get_val('scope', 'Scope')}")
            st.markdown(f"**Out of Scope:** {_get_val('out_of_scope', 'Out of Scope')}")
            st.markdown(f"**Risks:** {_get_val('risks', 'Risks')}")
            st.markdown(f"**Stakeholders:** {_get_val('stakeholders', 'Stakeholders')}")
            st.markdown(f"**Interfaces:** {_get_val('interfaces', 'Interfaces')}")

    with t_loc:
        l1, l2 = st.columns(2)
        with l1:
            st.markdown(f"**Code Station:** `{_get_val('code_station', 'Code Station')}`")
            st.markdown(f"**Station:** `{_get_val('station', 'Station')}`")
            st.markdown(f"**Code Line:** `{_get_val('code_line', 'code ligne')}`")
            st.markdown(f"**Section:** `{_get_val('section', 'Section')}`")
        with l2:
            st.markdown(f"**Latitude:** `{_get_val('lat', 'Latitude')}`")
            st.markdown(f"**Longitude:** `{_get_val('long', 'Longitude')}`")
            st.markdown(f"**PK Start:** `{_get_val('pk_start', 'PK Start')}`")
            st.markdown(f"**PK Stop:** `{_get_val('pk_stop', 'PK Stop')}`")

    with t_links:
        acc_url = _get_val("acc_link", "ACC Link")
        pb_url = _get_val("pb_link", "PB Link")
        orga_url = _get_val("orga_link", "Organization Link")
        k1, k2, k3 = st.columns(3)
        with k1:
            st.markdown("**ACC Link:**")
            if acc_url and acc_url != "—" and acc_url.startswith("http"):
                st.markdown(f"[🔗 Open ACC]({acc_url})")
            else:
                st.write(acc_url)
        with k2:
            st.markdown("**PB Link:**")
            if pb_url and pb_url != "—" and pb_url.startswith("http"):
                st.markdown(f"[🔗 Open PB]({pb_url})")
            else:
                st.write(pb_url)
        with k3:
            st.markdown("**Organization Link:**")
            if orga_url and orga_url != "—" and orga_url.startswith("http"):
                st.markdown(f"[🔗 Open Confluence]({orga_url})")
            else:
                st.write(orga_url)

    with t_class:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Strategic Priority:** `{_get_val('strategic_priority', 'Strategic Priority')}`")
            st.markdown(f"**Category:** `{_get_val('category', 'Category')}`")
            st.markdown(f"**Complexity:** `{_get_val('complexity', 'Complexity')}`")
        with c2:
            tags_val = dyn_dict.get("category_tags", [])
            st.markdown("**Category Tags:**")
            if isinstance(tags_val, list) and tags_val:
                st.write(" ".join(f"`{t_item}`" for t_item in tags_val))
            else:
                st.write("—")


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

    # 2. Dynamic Attribute Unpacking & Organization Enrichment
    df_merged = PortfolioService.flatten_dynamic_attributes(df_projects, params)
    org_repo = OrganizationRepository(project_repo.db_path)
    df_funcs = org_repo.get_all_functions()
    df_merged = OrganizationService.enrich_projects_with_organization(df_merged, df_funcs)

    # 3. Dynamic Column Configuration (whitelisted allowed dynamic parameters)
    column_configs: dict[str, Any] = {
        "id": st.column_config.TextColumn(t("portfolio.col_id"), help="Unique project identifier", width="small"),
        "name": st.column_config.TextColumn(t("portfolio.col_name"), width="medium"),
        "project_manager": st.column_config.TextColumn(
            t("master_data.field_project_manager", default="Project Manager"),
            help="Project Manager",
            width="medium",
        ),
        "level_3_manager_name": st.column_config.TextColumn(
            t("portfolio.filter_level_3_manager", default="Managing Function (Level 3)"),
            help="Managing function of project manager at level 3 of hierarchy",
            width="medium",
        ),
        "status": st.column_config.TextColumn(t("portfolio.col_status"), width="small"),
        "planned_budget": st.column_config.NumberColumn(t("portfolio.col_planned"), format="€%.2f"),
        "actual_budget": st.column_config.NumberColumn(t("portfolio.col_actual"), format="€%.2f"),
    }

    display_cols: list[str] = [
        "id",
        "name",
        "project_manager",
        "level_3_manager_name",
        "status",
        "planned_budget",
        "actual_budget",
    ]

    if not params.empty and "param_id" in params.columns:
        for _, p in params.iterrows():
            pid = str(p["param_id"])
            pname = str(p.get("param_name", pid))
            ptype = str(p.get("param_type", PARAM_TYPE_TEXT)).upper()

            # Strictly whitelist only requested dynamic parameters
            if pname not in ALLOWED_DYNAMIC_PARAMS:
                continue

            target_col = pid if pid in df_merged.columns else (pname if pname in df_merged.columns else None)
            if not target_col:
                continue

            if target_col not in display_cols:
                display_cols.append(target_col)

            if ptype in (PARAM_TYPE_URL, PARAM_TYPE_HYPERLINK):
                column_configs[target_col] = st.column_config.LinkColumn(
                    label=pname,
                    help=f"Dynamic URL ({pid})",
                    display_text="Open Link ↗",
                )
            elif ptype in (PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS):
                column_configs[target_col] = st.column_config.ListColumn(
                    label=pname,
                    help=f"Tags / Multi-selection ({pid})",
                )
            elif ptype == PARAM_TYPE_DATE:
                column_configs[target_col] = st.column_config.TextColumn(
                    label=pname,
                    help=f"Date ({pid})",
                )
            elif ptype == PARAM_TYPE_NUMBER:
                column_configs[target_col] = st.column_config.NumberColumn(
                    label=pname,
                    help=f"Number ({pid})",
                )
            else:
                column_configs[target_col] = st.column_config.TextColumn(
                    label=pname,
                    help=f"{ptype} parameter ({pid})",
                )

    # 4. Search, Status, Project Manager & Level 3 Hierarchy Filters
    f_c1, f_c2, f_c3, f_c4 = st.columns([2, 1, 1.5, 1.5])
    with f_c1:
        search_term = st.text_input(
            t("portfolio.filter_search"),
            placeholder=t("portfolio.filter_search_placeholder"),
        )
    with f_c2:
        all_statuses = sorted([s for s in df_merged["status"].dropna().unique() if s])
        status_filter = st.multiselect(
            t("portfolio.filter_status"),
            options=all_statuses,
            default=[],
            placeholder=t("portfolio.filter_all"),
        )
    with f_c3:
        all_l3 = sorted([m for m in df_merged["level_3_manager_name"].dropna().unique() if m and m != "—"])
        l3_filter = st.multiselect(
            t("portfolio.filter_level_3_manager"),
            options=all_l3,
            default=[],
            placeholder=t("portfolio.filter_all_level3", default="All Level 3 Functions"),
        )
    with f_c4:
        pm_scope = df_merged[df_merged["level_3_manager_name"].isin(l3_filter)] if l3_filter else df_merged
        all_pms = sorted([pm for pm in pm_scope["project_manager"].dropna().unique() if pm and pm != "—"])
        pm_filter = st.multiselect(
            t("portfolio.filter_project_manager"),
            options=all_pms,
            default=[],
            placeholder=t("portfolio.filter_all_managers", default="All Project Managers"),
        )

    filtered_df = df_merged.copy()
    if status_filter:
        filtered_df = filtered_df[filtered_df["status"].isin(status_filter)]
    if l3_filter:
        filtered_df = filtered_df[filtered_df["level_3_manager_name"].isin(l3_filter)]
    if pm_filter:
        filtered_df = filtered_df[filtered_df["project_manager"].isin(pm_filter)]
    if search_term.strip():
        term = search_term.lower()
        filtered_df = filtered_df[
            filtered_df["id"].astype(str).str.lower().str.contains(term, na=False)
            | filtered_df["name"].astype(str).str.lower().str.contains(term, na=False)
        ]

    # 5. Render Data Grid with Row Selection
    st.subheader(t("portfolio.table_header", count=len(filtered_df)))
    st.caption(t("portfolio.details_hint", default="💡 Click on any project in the table above to display its details below."))

    available_cols = [c for c in display_cols if c in filtered_df.columns]
    event = st.dataframe(
        filtered_df[available_cols],
        column_config=column_configs,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="portfolio_master_table",
    )

    # 6. Render Project Details Below the Master List
    selected_row_indices: list[int] = []
    if event and hasattr(event, "selection"):
        sel_obj = getattr(event, "selection")
        if isinstance(sel_obj, dict):
            selected_row_indices = sel_obj.get("rows", [])
        else:
            selected_row_indices = getattr(sel_obj, "rows", [])

    if selected_row_indices and len(selected_row_indices) > 0:
        sel_idx = selected_row_indices[0]
        if 0 <= sel_idx < len(filtered_df):
            selected_proj = filtered_df.iloc[sel_idx]
            _render_project_details_panel(selected_proj, params, project_repo)
