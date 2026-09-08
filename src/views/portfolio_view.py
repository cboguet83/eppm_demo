"""Screen 1: Portfolio Overview View with Interactive Master List and Details Inspection."""

from dataclasses import asdict
import hashlib
import json
from typing import Any

import pandas as pd
import streamlit as st

from src.i18n import t
from src.models.constants import (
    PAGE_PLANNING,
    PARAM_TYPE_HYPERLINK,
    PARAM_TYPE_NUMBER,
    PARAM_TYPE_TEXT,
    PARAM_TYPE_URL,
)
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.project_type_repo import ProjectTypeRepository
from src.repositories.portfolio_repo import PortfolioRepository, portfolio_revision
from src.repositories.schema_repo import SchemaRepository
from src.services.organization_service import OrganizationService
from src.services.project_overallocation import overallocated_project_ids
from src.views.portfolio_table_component import portfolio_project_table
from src.views.project_dialogs import open_create_project_dialog, open_edit_project_dialog
from src.views.project_collaboration_view import render_project_contacts, render_project_log

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

    proj_obj = project_repo.get_project_by_id(proj_id)
    if proj_obj is None:
        st.info("The selected project no longer exists.")
        return
    params = ProjectTypeRepository(project_repo.db_path).get_template(proj_obj.project_type_id)
    allowed = set(params["param_id"]) if not params.empty else set()
    dyn_dict = {pid: value for pid, value in proj_obj.dynamic_attributes.items() if pid in allowed}
    st.caption(f"{t('project_types.label')}: {selected_proj.get('project_template', '')}")
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

    # Labels and values deliberately use the same native caption font size.
    summary = [
        (t("portfolio.col_status", default="Status"), str(proj_status)),
        (t("master_data.field_project_manager", default="Project Manager"), str(pm_name)),
        (t("portfolio.filter_level_3_manager", default="Managing Func (L3)"), str(l3_name)),
        (t("portfolio.col_planned", default="Planned (€)"), f"€{planned:,.2f}"),
        (t("portfolio.col_actual", default="Actual (€)"), f"€{actual:,.2f}"),
        (t("portfolio.kpi_variance", default="Variance"), f"€{variance:,.2f} · {burn_rate:.1f}% burn"),
    ]
    with st.container(horizontal=True, horizontal_alignment="distribute"):
        for label, value in summary:
            with st.container(width="content"):
                st.caption(label)
                st.caption(value)

    # Render only the effective template, including user-created groups/fields.
    groups = schema_repo.get_all_groups()
    group_names = dict(zip(groups["id"], groups["group_name"])) if not groups.empty else {}
    field_groups = list(params.groupby("group_id", dropna=False, sort=False)) if not params.empty else []
    labels = [group_names.get(group_id, t("schema.param_group_none")) for group_id, _ in field_groups]
    labels += [t("project_collaboration.contacts", default="Project Contacts"),
               t("project_collaboration.log", default="Project log")]
    tabs = st.tabs(labels, key=f"project_details_tabs_{proj_id}", on_change="rerun")
    for tab, (_, fields) in zip(tabs, field_groups):
        if tab.open:
            with tab:
                for _, prop in fields.iterrows():
                    value = dyn_dict.get(prop["param_id"])
                    display = ", ".join(map(str, value)) if isinstance(value, list) else str(value) if value is not None else "—"
                    alias = prop.get('alias')
                    label = str(prop['param_name'])
                    if pd.notna(alias) and alias:
                        label += f" ({alias})"
                    st.write(f"{label}{' *' if prop['mandatory'] else ''}: {display or '—'}")
    if tabs[-2].open:
        with tabs[-2]:
            render_project_contacts(int(proj_id), project_repo.db_path)
    if tabs[-1].open:
        with tabs[-1]:
            render_project_log(int(proj_id), project_repo.db_path)

@st.cache_data(ttl=60, max_entries=128, show_spinner=False)
def _load_portfolio_page(db_path, revision, columns, query, offset):
    page = PortfolioRepository(db_path).get_page(columns, query, offset)
    overloaded = overallocated_project_ids(db_path, [row["project_id"] for row in page["rows"]])
    for row in page["rows"]:
        row["is_overallocated"] = row["project_id"] in overloaded
    return page


@st.cache_data(ttl=60, max_entries=64, show_spinner=False)
def _load_portfolio_facet(db_path, revision, columns, query, column, search):
    return PortfolioRepository(db_path).get_facet(columns, query, column, search)


def _portfolio_columns(params: pd.DataFrame) -> list[dict]:
    columns = [
        {"key": "name", "label": t("portfolio.col_name"), "format": "text"},
        {"key": "project_template", "label": t("project_types.label"), "format": "text"},
        {"key": "project_manager", "label": t("master_data.field_project_manager"), "format": "text"},
        {"key": "level_3_manager_name", "label": t("portfolio.filter_level_3_manager"), "format": "text"},
        {"key": "status", "label": t("portfolio.col_status"), "format": "text"},
        {"key": "planned_budget", "label": t("portfolio.col_planned"), "format": "currency"},
        {"key": "actual_budget", "label": t("portfolio.col_actual"), "format": "currency"},
    ]
    # The compact master grid retains its curated columns. Details and both
    # dialogs use the entire effective template, with no field whitelist.
    for prop in params.to_dict("records"):
        if prop["param_name"] not in ALLOWED_DYNAMIC_PARAMS:
            continue
        ptype = prop["param_type"]
        fmt = "number" if ptype == PARAM_TYPE_NUMBER else (
            "url" if ptype in (PARAM_TYPE_URL, PARAM_TYPE_HYPERLINK) else "text")
        columns.append({"key": "property:" + str(prop["param_id"]), "param_id": str(prop["param_id"]),
                        "label": prop["param_name"], "format": fmt})
    return columns


@st.fragment
def _render_portfolio_browser(project_repo: ProjectRepository, schema_repo: SchemaRepository) -> None:
    """Scroll requests rerun only this fragment, not navigation or global KPIs."""
    params = schema_repo.get_all_parameters()
    columns = _portfolio_columns(params)
    templates = ProjectTypeRepository(project_repo.db_path).get_all_types()
    search = st.text_input(t("portfolio.filter_search"), placeholder=t("portfolio.filter_search_placeholder"))
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.subheader(t("portfolio.table_header"))
        if st.button("Create new project", icon=":material/add:", type="primary",
                     key="btn_create_project_from_portfolio"):
            open_create_project_dialog(project_repo, schema_repo)
    st.caption("Click a project to see its details. Scroll to load more projects automatically.")

    revision = portfolio_revision(project_repo.db_path)
    context = hashlib.sha256(json.dumps([revision, columns, search],
                                       sort_keys=True).encode()).hexdigest()
    component_state = st.session_state.get(_PORTFOLIO_TABLE_KEY, {})
    request = (component_state.get("request") if isinstance(component_state, dict)
               else getattr(component_state, "request", None)) or {}
    query = dict(request.get("query") or {})
    query.update(search=search, templates=[])
    current_request = request.get("context") == context
    offset = request.get("offset", 0) if current_request else 0
    try:
        offset = max(0, int(offset)) // 100 * 100
    except (TypeError, ValueError):
        offset = 0
    page = _load_portfolio_page(project_repo.db_path, revision, columns, query, offset)
    facet = None
    if current_request and request.get("kind") == "facet" and request.get("column") in {c["key"] for c in columns}:
        facet = _load_portfolio_facet(project_repo.db_path, revision, columns, query,
                                     request["column"], str(request.get("search") or ""))
    _sync_portfolio_project_selection()
    gantt_project = (component_state.get("gantt_click") if isinstance(component_state, dict)
                     else getattr(component_state, "gantt_click", None))
    if gantt_project is not None and project_repo.get_project_by_id(gantt_project) is not None:
        st.session_state["target_planning_project_id"] = int(gantt_project)
        st.session_state.pop("active_resource_pool_filter", None)
        st.session_state.pop("pending_resource_pool_filter", None)
        st.session_state["nav_redirect"] = PAGE_PLANNING
        st.rerun()
    portfolio_project_table(
        page["rows"], columns, st.session_state.get(_SELECTED_PROJECT_KEY),
        key=_PORTFOLIO_TABLE_KEY,
        page_info={**{k: v for k, v in page.items() if k != "rows"},
                   "context": context, "query": query,
                   "request_id": request.get("nonce") if current_request else None,
                   "facet": facet},
    )

    selected_id = st.session_state.get(_SELECTED_PROJECT_KEY)
    if selected_id is not None:
        project = project_repo.get_project_by_id(selected_id)
        if project is not None:
            org = OrganizationRepository(project_repo.db_path)
            selected = OrganizationService.enrich_projects_with_organization(
                pd.DataFrame([asdict(project)]), org.get_all_functions(), org.get_all_employees()).iloc[0]
            names = dict(zip(templates["id"], templates["name"]))
            selected["project_template"] = names.get(project.project_type_id, "")
            _render_project_details_panel(selected, params, project_repo, schema_repo)


def render_portfolio_overview(project_repo: ProjectRepository, schema_repo: SchemaRepository) -> None:
    """Render the compact project list; shared totals remain in navigation."""
    _render_portfolio_browser(project_repo, schema_repo)
