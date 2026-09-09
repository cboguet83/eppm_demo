"""Screen 1: Portfolio Overview View with Interactive Master List and Details Inspection."""

import hashlib
import html
import json
from typing import Any

import pandas as pd
import streamlit as st
from app.presentation.components.authorized_cache import authorized_cache

from app.application.exceptions import ProjectStorageError, ProjectTypeStorageError, SchemaStorageError
from app.application.services.portfolio import PortfolioService
from app.domain.projects.budgets import BudgetAmounts, analyze_budget, euro_amount
from app.domain.projects.links import normalize_link
from app.presentation.i18n import get_current_locale, t
from app.presentation.components.property_labels import localize_parameters, parameter_groups, property_label
from app.presentation.components.project_workspace import ProjectWorkspace
from app.presentation.components.project_type_frames import template_frame
from app.presentation.components.portfolio_table import portfolio_project_table
from app.presentation.components.project_dialogs import open_create_project_dialog, open_edit_project_dialog

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


@st.fragment
def _render_project_details_panel(
    selected_proj: pd.Series,
    params: pd.DataFrame,
    workspace: ProjectWorkspace,
) -> None:
    """Isolate detail tab reruns and preserve the page's existing scroll range."""
    from app.presentation.components.tab_position import preserve_tab_position

    key = f"project_details_panel_{selected_proj['id']}"
    with st.container(key=key):
        preserve_tab_position(key)
        _render_project_details_body(selected_proj, params, workspace)


def _property_value_html(display: str, param_type: str, label: str) -> str:
    """Escape property values and retain navigation for valid legacy URL fields."""
    escaped = html.escape(display or "—")
    if param_type not in {"URL", "HYPERLINK"}:
        return escaped
    try:
        link = normalize_link(display, label)
    except ValueError:
        # Invalid legacy URLs remain inspectable without becoming navigation.
        return escaped
    return (
        f'<a href="{html.escape(link["url"], quote=True)}" '
        f'target="_blank" rel="noopener noreferrer">{escaped}</a>'
    )


def _render_project_details_body(
    selected_proj: pd.Series,
    params: pd.DataFrame,
    workspace: ProjectWorkspace,
) -> None:
    """Renders the detailed inspection panel below the Projects Master List for the selected project.

    Args:
        selected_proj: Series containing the selected project's attributes.
        params: Schema parameters DataFrame.
        workspace: Injected project use cases and collaboration sections.
    """
    proj_id = selected_proj["id"]
    proj_name = selected_proj["name"]
    proj_status = selected_proj.get("status", "—")
    pm_name = selected_proj.get("project_manager", "—")
    l3_name = selected_proj.get("level_3_manager_name", "—")
    planned = euro_amount(selected_proj.get("planned_budget"))
    actual = euro_amount(selected_proj.get("actual_budget"))
    analysis = analyze_budget(BudgetAmounts(planned, actual))
    variance = analysis.variance
    burn_rate_label = f"{analysis.burn_rate:.1f}%" if analysis.burn_rate is not None else "—"

    proj_obj = workspace.projects.get_project_by_id(proj_id)
    if proj_obj is None:
        st.info("The selected project no longer exists.")
        return
    params = localize_parameters(
        template_frame(workspace.types.template_reference(proj_obj.project_type_id)),
        workspace.schema.alias_references(get_current_locale()),
    )
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
            open_edit_project_dialog(int(proj_id), workspace)

    # Labels and values deliberately use the same native caption font size.
    summary = [
        (t("portfolio.col_status", default="Status"), str(proj_status)),
        (t("master_data.field_project_manager", default="Project Manager"), str(pm_name)),
        (t("portfolio.filter_level_3_manager", default="Managing Func (L3)"), str(l3_name)),
        (t("portfolio.col_planned", default="Planned (€)"), f"€{planned:,.2f}"),
        (t("portfolio.col_actual", default="Actual (€)"), f"€{actual:,.2f}"),
        (t("portfolio.kpi_variance", default="Variance"), f"€{variance:,.2f} · {burn_rate_label} burn"),
    ]
    with st.container(horizontal=True, horizontal_alignment="distribute"):
        for label, value in summary:
            with st.container(width="content"):
                st.caption(label)
                st.caption(value)

    # Render only the effective template, including user-created groups/fields.
    groups = pd.DataFrame(workspace.portfolio.get_catalog(include_managers=False).groups)
    field_groups = parameter_groups(params, groups)
    if not any(label.casefold() == "useful links" for label, _ in field_groups):
        field_groups.append(("useful links", params.iloc[:0]))
    labels = [t("portfolio.tab_details_links") if label.casefold() == "useful links" else label
              for label, _ in field_groups]
    labels += [t("project_collaboration.contacts", default="Project Contacts"),
               t("project_collaboration.log", default="Project log")]
    tabs = st.tabs(labels, key=f"project_details_tabs_{proj_id}", on_change="rerun")
    for tab, (group_label, fields) in zip(tabs, field_groups):
        if tab.open:
            with tab:
                for _, prop in fields.iterrows():
                    value = dyn_dict.get(prop["param_id"])
                    display = ", ".join(map(str, value)) if isinstance(value, list) else str(value) if value is not None else "—"
                    label = property_label(prop.to_dict(), {})
                    value_html = _property_value_html(display, prop["param_type"], label)
                    st.html(
                        '<div style="display:grid;grid-template-columns:minmax(10rem,25%) minmax(0,1fr);'
                        'column-gap:2rem;padding:.25rem 0;overflow-wrap:anywhere">'
                        f'<span>{html.escape(label)}{" *" if prop["mandatory"] else ""}:</span>'
                        f'<span>{value_html}</span></div>'
                    )
                if group_label.casefold() == "useful links" and workspace.render_links:
                    workspace.render_links(int(proj_id))
    if tabs[-2].open:
        with tabs[-2]:
            workspace.render_contacts(int(proj_id))
    if tabs[-1].open:
        with tabs[-1]:
            workspace.render_log(int(proj_id))

@authorized_cache(ttl=60, max_entries=128, show_spinner=False)
def _load_portfolio_page(revision: tuple, columns: list[dict], query: dict, offset: int,
                         _service: PortfolioService) -> dict:
    """Cache by source identity/revision; injected service instances are not hashed."""
    return _service.get_page(columns, query, offset)


@authorized_cache(ttl=60, max_entries=64, show_spinner=False)
def _load_portfolio_facet(revision: tuple, columns: list[dict], query: dict, column: str,
                          search: str, _service: PortfolioService) -> dict:
    """Keep global facet results bounded independently from row pages."""
    return _service.get_facet(columns, query, column, search)


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
        fmt = "number" if ptype == "NUMBER" else (
            "url" if ptype in ("URL", "HYPERLINK") else "text")
        columns.append({"key": "property:" + str(prop["param_id"]), "param_id": str(prop["param_id"]),
                        "label": property_label(prop, {}), "format": fmt})
    return columns


@st.fragment
def _render_portfolio_browser(workspace: ProjectWorkspace) -> None:
    """Scroll requests rerun only this fragment, not navigation or global KPIs."""
    params = pd.DataFrame(workspace.portfolio.get_catalog(include_managers=False).parameters)
    columns = _portfolio_columns(localize_parameters(params, workspace.schema.alias_references(get_current_locale())))
    search = st.text_input(t("portfolio.filter_search"), placeholder=t("portfolio.filter_search_placeholder"))
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.subheader(t("portfolio.table_header"))
        if st.button("Create new project", icon=":material/add:", type="primary",
                     key="btn_create_project_from_portfolio"):
            open_create_project_dialog(workspace)
    st.caption("Click a project to see its details. Scroll to load more projects automatically.")

    revision = workspace.portfolio.revision()
    context = hashlib.sha256(json.dumps([revision, columns, search],
                                       sort_keys=True).encode()).hexdigest()
    component_state = st.session_state.get(_PORTFOLIO_TABLE_KEY, {})
    request = (component_state.get("request") if isinstance(component_state, dict)
               else getattr(component_state, "request", None)) or {}
    request = request if isinstance(request, dict) else {}
    raw_query = request.get("query")
    query = dict(raw_query) if isinstance(raw_query, dict) else {}
    query.update(search=search, templates=[])
    current_request = request.get("context") == context
    offset = request.get("offset", 0) if current_request else 0
    try:
        offset = max(0, int(offset)) // 100 * 100
    except (TypeError, ValueError, OverflowError):
        offset = 0
    page = _load_portfolio_page(revision, columns, query, offset, workspace.portfolio)
    facet = None
    if current_request and request.get("kind") == "facet" and request.get("column") in {c["key"] for c in columns}:
        facet = _load_portfolio_facet(revision, columns, query, request["column"],
                                     str(request.get("search") or ""), workspace.portfolio)
    _sync_portfolio_project_selection()
    gantt_project = (component_state.get("gantt_click") if isinstance(component_state, dict)
                     else getattr(component_state, "gantt_click", None))
    if gantt_project is not None and workspace.projects.get_project_by_id(gantt_project) is not None:
        st.session_state["target_planning_project_id"] = int(gantt_project)
        st.session_state.pop("active_resource_pool_filter", None)
        st.session_state.pop("pending_resource_pool_filter", None)
        st.session_state["nav_redirect"] = "2. Planning & Step Loader"
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
        detail = workspace.portfolio.get_detail(int(selected_id))
        if detail is not None:
            selected = pd.Series({**detail, "id": detail["project_id"]})
            for key in ("project_manager", "level_3_manager_name"):
                selected[key] = selected.get(key) or "—"
            _render_project_details_panel(selected, params, workspace)


def render_portfolio_overview(workspace: ProjectWorkspace) -> None:
    """Render the compact project list; shared totals remain in navigation."""
    try:
        _render_portfolio_browser(workspace)
    except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
        st.error(str(exc))
