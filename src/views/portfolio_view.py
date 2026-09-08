"""Screen 1: Portfolio Overview View with Interactive Master List and Details Inspection."""

import json
from typing import Any

import pandas as pd
import streamlit as st

from src.i18n import t
from src.models.constants import (
    PARAM_TYPE_HYPERLINK,
    PARAM_TYPE_NUMBER,
    PARAM_TYPE_TEXT,
    PARAM_TYPE_URL,
)
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository
from src.services.organization_service import OrganizationService
from src.services.portfolio_service import PortfolioService
from src.views.portfolio_table_component import portfolio_project_table
from src.views.project_dialogs import open_create_project_dialog, open_edit_project_dialog

ALLOWED_DYNAMIC_PARAMS: set[str] = {
    "phase",
    "code_line",
    "strategic_priority",
    "category",
    "category_tags",
    "complexity",
}

_PORTFOLIO_TABLE_KEY = "portfolio_master_table"
_SELECTED_PROJECT_KEY = "selected_portfolio_project_id"


def _sync_portfolio_project_selection(
    component_key: str = _PORTFOLIO_TABLE_KEY,
    selection_key: str = _SELECTED_PROJECT_KEY,
) -> None:
    """Apply a row-click event before the next page body is rendered."""
    component_state = st.session_state.get(component_key)
    if isinstance(component_state, dict):
        project_id = component_state.get("row_click")
    else:
        project_id = getattr(component_state, "row_click", None)
    if project_id is not None:
        st.session_state[selection_key] = project_id


def _portfolio_table_value(value: Any) -> Any:
    """Convert pandas and collection values to JSON-safe component values."""
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def _build_portfolio_table_rows(
    frame: pd.DataFrame,
    display_columns: list[str],
) -> list[dict[str, Any]]:
    """Build the safe row payload while retaining a hidden project identifier."""
    rows: list[dict[str, Any]] = []
    for _, source in frame.iterrows():
        row = {column: _portfolio_table_value(source.get(column)) for column in display_columns}
        row["project_id"] = _portfolio_table_value(source.get("id"))
        rows.append(row)
    return rows


def _render_project_details_panel(
    selected_proj: pd.Series,
    params: pd.DataFrame,
    project_repo: ProjectRepository,
    schema_repo: SchemaRepository,
) -> None:
    """Renders the detailed inspection panel below the Projects Master List for the selected project.

    Args:
        selected_proj: Series containing the selected project's attributes.
        params: Schema parameters DataFrame.
        project_repo: ProjectRepository instance.
        schema_repo: SchemaRepository instance used by the edit dialog.
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
    # Retrieve complete dynamic attributes from repository
    dyn_dict: dict[str, Any] = {}
    if isinstance(raw_dyn, dict):
        dyn_dict = raw_dyn
    elif isinstance(raw_dyn, str) and raw_dyn.strip():
        try:
            dyn_dict = json.loads(raw_dyn)
        except (json.JSONDecodeError, TypeError):
            dyn_dict = {}
    proj_obj = project_repo.get_project_by_id(proj_id)
    if proj_obj and proj_obj.dynamic_attributes:
        if isinstance(proj_obj.dynamic_attributes, dict):
            dyn_dict = dict(proj_obj.dynamic_attributes)
        elif isinstance(proj_obj.dynamic_attributes, str) and proj_obj.dynamic_attributes.strip():
            try:
                dyn_dict = json.loads(proj_obj.dynamic_attributes)
            except (json.JSONDecodeError, TypeError):
                dyn_dict = {}

    if not dyn_dict:
        raw_dyn = selected_proj.get("dynamic_attributes", "{}")
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
            "✏️ Edit project details",
            key=f"btn_edit_details_{proj_id}",
            width="stretch",
        ):
            open_edit_project_dialog(int(proj_id), project_repo, schema_repo)

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
        # 1. Search in dyn_dict by key or alias
        val = dyn_dict.get(key)
        if (val is None or val == "") and alias:
            val = dyn_dict.get(alias)

        # 2. Search in selected_proj series columns as fallback
        if val is None or val == "":
            if key in selected_proj and pd.notna(selected_proj[key]):
                val = selected_proj[key]
            elif alias and alias in selected_proj and pd.notna(selected_proj[alias]):
                val = selected_proj[alias]

        # 3. Search by matching schema param_id
        if (val is None or val == "") and not params.empty and "param_name" in params.columns:
            matching_p = params[
                (params["param_name"].str.lower() == key.lower())
                | (params.get("alias", pd.Series(dtype=str)).astype(str).str.lower() == alias.lower())
            ]
            if not matching_p.empty:
                pid = matching_p.iloc[0]["param_id"]
                if pid in dyn_dict:
                    val = dyn_dict[pid]
                elif pid in selected_proj and pd.notna(selected_proj[pid]):
                    val = selected_proj[pid]

        if val is None:
            return "—"
        if isinstance(val, list):
            return ", ".join(str(item) for item in val) if val else "—"
        s = str(val).strip()
        return s if s else "—"

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
            tags_val = dyn_dict.get("category_tags")
            if not tags_val and "category_tags" in selected_proj and pd.notna(selected_proj["category_tags"]):
                tags_val = selected_proj["category_tags"]
            st.markdown("**Category Tags:**")
            if isinstance(tags_val, list) and tags_val:
                st.write(" ".join(f"`{t_item}`" for t_item in tags_val))
            elif isinstance(tags_val, str) and tags_val.strip() and tags_val != "—":
                st.write(f"`{tags_val}`")
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
        if st.button(
            "Create new project",
            icon=":material/add:",
            type="primary",
            key="btn_create_project_from_empty_portfolio",
        ):
            open_create_project_dialog(project_repo, schema_repo)
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
    df_employees = org_repo.get_all_employees()
    df_merged = OrganizationService.enrich_projects_with_organization(
        df_merged,
        df_funcs,
        df_employees,
    )

    # 3. Dynamic Column Configuration (whitelisted allowed dynamic parameters)
    display_cols: list[str] = [
        "name",
        "project_manager",
        "level_3_manager_name",
        "status",
        "planned_budget",
        "actual_budget",
    ]
    table_columns: list[dict[str, str]] = [
        {"key": "name", "label": t("portfolio.col_name"), "format": "text"},
        {
            "key": "project_manager",
            "label": t("master_data.field_project_manager", default="Project Manager"),
            "format": "text",
        },
        {
            "key": "level_3_manager_name",
            "label": t("portfolio.filter_level_3_manager", default="Managing Function (Level 3)"),
            "format": "text",
        },
        {"key": "status", "label": t("portfolio.col_status"), "format": "text"},
        {"key": "planned_budget", "label": t("portfolio.col_planned"), "format": "currency"},
        {"key": "actual_budget", "label": t("portfolio.col_actual"), "format": "currency"},
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

            value_format = "url" if ptype in (PARAM_TYPE_URL, PARAM_TYPE_HYPERLINK) else "text"
            if ptype == PARAM_TYPE_NUMBER:
                value_format = "number"
            table_columns.append({"key": target_col, "label": pname, "format": value_format})

    # 4. Search; column-level filtering lives in the project table headers.
    search_term = st.text_input(
        t("portfolio.filter_search"),
        placeholder=t("portfolio.filter_search_placeholder"),
    )
    filtered_df = df_merged
    if search_term.strip():
        term = search_term.lower()
        filtered_df = filtered_df[
            filtered_df["id"].astype(str).str.lower().str.contains(term, na=False)
            | filtered_df["name"].astype(str).str.lower().str.contains(term, na=False)
        ]
    # 5. Render Data Grid with direct row selection and per-column filters
    with st.container(
        horizontal=True,
        horizontal_alignment="distribute",
        vertical_alignment="center",
    ):
        st.subheader(t("portfolio.table_header", count=len(filtered_df)))
        if st.button(
            "Create new project",
            icon=":material/add:",
            type="primary",
            key="btn_create_project_from_portfolio",
        ):
            open_create_project_dialog(project_repo, schema_repo)
    st.caption(
        t(
            "portfolio.details_hint",
            default="💡 Click on any project in the table above to display its details below.",
        )
    )

    available_cols = [c for c in display_cols if c in filtered_df.columns]
    filtered_df_reset = filtered_df.reset_index(drop=True)
    available_column_specs = [column for column in table_columns if column["key"] in available_cols]
    # Component events are already in Session State at the start of the rerun.
    # Synchronize before mounting so the new selection is painted in this run.
    # Keeping the wrapper call signature stable also makes Streamlit hot reloads
    # safe when an older imported component module is still in memory.
    _sync_portfolio_project_selection()
    clicked_project_id = portfolio_project_table(
        _build_portfolio_table_rows(filtered_df_reset, available_cols),
        available_column_specs,
        st.session_state.get(_SELECTED_PROJECT_KEY),
        key=_PORTFOLIO_TABLE_KEY,
    )

    # Defensive fallback for component runtimes that expose a trigger only in
    # the mount result. The immediate rerun prevents a stale row highlight.
    selected_pid = st.session_state.get(_SELECTED_PROJECT_KEY)
    if clicked_project_id is not None and str(clicked_project_id) != str(selected_pid):
        st.session_state[_SELECTED_PROJECT_KEY] = clicked_project_id
        st.rerun()

    # 6. Render Project Details Below the Master List
    selected_pid = st.session_state.get(_SELECTED_PROJECT_KEY)
    if selected_pid is not None:
        matching = df_merged[df_merged["id"].astype(str) == str(selected_pid)]
        if not matching.empty:
            selected_proj = matching.iloc[0]
            _render_project_details_panel(selected_proj, params, project_repo, schema_repo)
