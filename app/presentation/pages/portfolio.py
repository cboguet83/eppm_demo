"""Screen 1: Portfolio Overview View with Interactive Master List and Details Inspection."""

import hashlib
import html
import json
from contextvars import ContextVar
from dataclasses import dataclass

import pandas as pd
import streamlit as st
from app.presentation.components.authorized_cache import authorized_cache
from app.domain.access.models import Permission

from app.application.exceptions import ProjectStorageError, ProjectTypeStorageError, SchemaStorageError
from app.application.services.portfolio import PortfolioService, portfolio_revision_token
from app.application.services.project_types import ProjectTypeService
from app.application.services.schema import SchemaService
from app.domain.projects.budgets import BudgetAmounts, analyze_budget, euro_amount
from app.domain.projects.links import normalize_link
from app.domain.projects.project import Project
from app.presentation.i18n import get_current_locale, t
from app.presentation.components.property_labels import localize_parameters, parameter_groups, property_label
from app.presentation.components.project_workspace import ProjectWorkspace
from app.presentation.components.project_type_frames import template_frame
from app.presentation.components.portfolio_table import portfolio_project_table
from app.presentation.components.portfolio_project_dialog import begin_project_dialog, render_project_modal

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


@dataclass(frozen=True)
class _DetailContent:
    """Current display data reused only within one synchronous details render."""

    project: Project
    field_groups: list[tuple[str, pd.DataFrame]]
    can_edit: bool


_detail_content: ContextVar[tuple[int, int, _DetailContent] | None] = ContextVar(
    "portfolio_detail_content", default=None,
)


def _load_detail_content(project_id: int, workspace: ProjectWorkspace) -> _DetailContent | None:
    """Resolve authorized project and schema reads before emitting visible fields."""
    current = _detail_content.get()
    if current is not None and current[:2] == (id(workspace), project_id):
        return current[2]
    project = workspace.projects.get_project_by_id(project_id)
    if project is None:
        return None
    can_edit = workspace.projects.permissions().allows(Permission.EDIT, project_id)
    fields = _detail_fields(
        (), project.project_type_id, get_current_locale(),
        _service=workspace.portfolio, _types=workspace.types, _schema=workspace.schema,
    )
    return _DetailContent(project, fields, can_edit)


@authorized_cache(ttl=60, max_entries=128, show_spinner=False)
def _detail_fields(
    revision: tuple, type_id: int, locale: str, *, _service: PortfolioService,
    _types: ProjectTypeService, _schema: SchemaService,
) -> list[tuple[str, pd.DataFrame]]:
    """Reuse reference fields under the current database, actor, scope and revision."""
    params = localize_parameters(
        template_frame(_types.template_reference(type_id)), _schema.alias_references(locale),
    )
    groups = pd.DataFrame(_service.get_catalog(include_managers=False).groups)
    field_groups = parameter_groups(params, groups)
    if not any(label.casefold() == "useful links" for label, _ in field_groups):
        field_groups.append(("useful links", params.iloc[:0]))
    return field_groups


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
    if type(project_id) is int and project_id > 0:
        st.session_state[selection_key] = project_id


def _select_portfolio_project() -> None:
    """Update only the selected project's panel after the browser selects a row."""
    _sync_portfolio_project_selection()
    st.rerun("portfolio_selection")


@st.fragment
def _render_project_details_panel(
    selected_proj: pd.Series,
    params: pd.DataFrame,
    workspace: ProjectWorkspace,
) -> None:
    """Keep selected-project actions independent from the master list."""
    from app.presentation.components.tab_position import preserve_tab_position

    key = f"project_details_panel_{selected_proj['id']}"
    with st.container(key=key):
        try:
            _render_project_details_body(selected_proj, params, workspace)
        except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
            st.error(str(exc))
        preserve_tab_position(key, reveal_complete=True)


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
    proj_id = int(selected_proj["id"])
    content = _load_detail_content(proj_id, workspace)
    if content is None:
        st.info("The selected project no longer exists.")
        return
    token = _detail_content.set((id(workspace), proj_id, content))
    try:
        _draw_project_details(selected_proj, workspace)
    finally:
        _detail_content.reset(token)


def _draw_project_details(selected_proj: pd.Series, workspace: ProjectWorkspace) -> None:
    """Draw prepared summary and section data without intervening project reads."""
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

    head_c1, head_c2 = st.columns([4, 1])
    with head_c1:
        st.subheader(f"📌 {t('portfolio.details_title', default='Project Details')}: #{proj_id} — {proj_name}")
    with head_c2:
        _render_project_edit_action(int(proj_id), workspace)

    # Emit the complete summary together, retaining caption-sized labels and values.
    summary = [
        (t("portfolio.col_status", default="Status"), str(proj_status)),
        (t("master_data.field_project_manager", default="Project Manager"), str(pm_name)),
        (t("portfolio.filter_level_3_manager", default="Managing Func (L3)"), str(l3_name)),
        (t("portfolio.col_planned", default="Planned (€)"), f"€{planned:,.2f}"),
        (t("portfolio.col_actual", default="Actual (€)"), f"€{actual:,.2f}"),
        (t("portfolio.kpi_variance", default="Variance"), f"€{variance:,.2f} · {burn_rate_label} burn"),
    ]
    with st.container(key=f"project_details_summary_{proj_id}"):
        st.html(
            '<dl style="display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;'
            'font-size:.875rem;color:inherit;opacity:.7;margin:0">'
            + ''.join(
                '<div style="min-width:0;overflow-wrap:anywhere">'
                f'<dt>{html.escape(label)}</dt><dd style="margin:1rem 0 0">{html.escape(value)}</dd></div>'
                for label, value in summary
            ) + '</dl>'
        )

    _render_project_detail_sections(int(proj_id), workspace)


@st.fragment
def _render_project_edit_action(project_id: int, workspace: ProjectWorkspace) -> None:
    """Open editing without rebuilding the selected project's summary or sections."""
    try:
        current = _detail_content.get()
        can_edit = (current[2].can_edit if current is not None and current[:2] == (id(workspace), project_id)
                    else workspace.projects.permissions().allows(Permission.EDIT, project_id))
        if can_edit:
            st.button("Edit details", key=f"btn_edit_details_{project_id}", width="stretch",
                      on_click=begin_project_dialog, args=(workspace, project_id))
    except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
        st.error(str(exc))


@st.fragment
def _render_project_create_action(workspace: ProjectWorkspace) -> None:
    """Keep opening creation independent from the portfolio grid and selection."""
    try:
        if workspace.projects.permissions().allows(Permission.CREATE):
            st.button("Create new project", icon=":material/add:", type="primary", key="btn_create_project_from_portfolio",
                      on_click=begin_project_dialog, args=(workspace,))
    except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
        st.error(str(exc))


@st.fragment
def _render_project_detail_sections(proj_id: int, workspace: ProjectWorkspace) -> None:
    """Switch lazy sections without rebuilding the summary or master list."""
    try:
        _project_detail_sections(proj_id, workspace)
    except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
        st.error(str(exc))


def _project_detail_sections(proj_id: int, workspace: ProjectWorkspace) -> None:
    """Read the current authorized project before displaying a retained tab."""
    content = _load_detail_content(proj_id, workspace)
    if content is None:
        st.info("The selected project no longer exists.")
        return
    field_groups = content.field_groups
    labels = [t("portfolio.tab_details_links") if label.casefold() == "useful links" else label
              for label, _ in field_groups]
    labels += [t("wbs.title", default="WBS"), t("project_collaboration.contacts", default="Project Contacts"),
               t("project_collaboration.log", default="Project log")]
    tabs = st.tabs(labels, key=f"project_details_tabs_{proj_id}", on_change="rerun")
    for tab, (group_label, fields) in zip(tabs, field_groups):
        if tab.open:
            with tab:
                rows = []
                for _, prop in fields.iterrows():
                    value = content.project.dynamic_attributes.get(prop["param_id"])
                    display = ", ".join(map(str, value)) if isinstance(value, list) else str(value) if value is not None else "—"
                    label = property_label(prop.to_dict(), {})
                    value_html = _property_value_html(display, prop["param_type"], label)
                    rows.append(
                        '<div style="display:grid;grid-template-columns:minmax(10rem,25%) minmax(0,1fr);'
                        'column-gap:2rem;padding:.25rem 0;overflow-wrap:anywhere">'
                        f'<span>{html.escape(label)}{" *" if prop["mandatory"] else ""}:</span>'
                        f'<span>{value_html}</span></div>'
                    )
                if rows:
                    st.html('<div style="display:flex;flex-direction:column;gap:1rem">' + ''.join(rows) + '</div>')
                if group_label.casefold() == "useful links" and workspace.render_links:
                    workspace.render_links(int(proj_id))
    if tabs[-3].open:
        from app.presentation.components.wbs_editor import render_wbs_rows
        with tabs[-3]:
            render_wbs_rows(workspace.projects.get_wbs_allocations(proj_id), workspace.projects.get_wbs_options(proj_id))
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
    return _service.get_page(columns, query, offset, include_allocations=False)


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


def _render_portfolio_browser(workspace: ProjectWorkspace) -> None:
    """Compose controls, the independent scrolling grid, and selected-project panel."""
    st.html("""<style>
        .stVerticalBlock[class*="st-key-project_details_panel_"]:not([data-eppm-details-ready]) {
            visibility: hidden;
        }
        [data-testid="stMainBlockContainer"]:has(.st-key-portfolio_master_table) {
            padding-top: 0 !important;
        }
        /* Style-only shell elements must not reserve empty rows above the page. */
        [data-testid="stMainBlockContainer"]:has(.st-key-portfolio_master_table)
        > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has(style) {
            display: none;
        }
    </style>""")
    params = pd.DataFrame(workspace.portfolio.get_catalog(include_managers=False).parameters)
    columns = _portfolio_columns(localize_parameters(params, workspace.schema.alias_references(get_current_locale())))
    search = st.text_input(t("portfolio.filter_search"), placeholder=t("portfolio.filter_search_placeholder"))
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.subheader(t("portfolio.table_header"))
        _render_project_create_action(workspace)
    st.caption("Click a project to see its details. Scroll to load more projects automatically.")

    _render_portfolio_grid(workspace, columns, search)
    _render_portfolio_selection(workspace, params)
    render_project_modal(workspace)


@st.fragment(key="portfolio_grid")
def _render_portfolio_grid(workspace: ProjectWorkspace, columns: list[dict], search: str) -> None:
    """Load scrolling pages without rebuilding controls, permissions UI, or details."""
    try:
        _portfolio_grid(workspace, columns, search)
    except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
        st.error(str(exc))


def _portfolio_grid(workspace: ProjectWorkspace, columns: list[dict], search: str) -> None:
    """Serve a bounded row page under the current display and permission revision."""
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
    gantt_project = (component_state.get("gantt_click") if isinstance(component_state, dict)
                     else getattr(component_state, "gantt_click", None))
    if (type(gantt_project) is int and gantt_project > 0
            and workspace.projects.get_project_by_id(gantt_project) is not None):
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
                   "allocation_endpoint": "/api/portfolio/allocations",
                   "revision": portfolio_revision_token(revision),
                   "request_id": request.get("nonce") if current_request else None,
                   "preserve_position": st.session_state.pop("portfolio_preserve_grid_position", False),
                   "facet": facet},
        on_selection_change=_select_portfolio_project,
    )


@st.fragment(key="portfolio_selection")
def _render_portfolio_selection(workspace: ProjectWorkspace, params: pd.DataFrame) -> None:
    """Resolve the current selected row independently from master-list paging."""
    try:
        _portfolio_selection(workspace, params)
    except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
        st.error(str(exc))


def _portfolio_selection(workspace: ProjectWorkspace, params: pd.DataFrame) -> None:
    if "portfolio_selection_override" in st.session_state:
        st.session_state[_SELECTED_PROJECT_KEY] = st.session_state.pop("portfolio_selection_override")
    else:
        _sync_portfolio_project_selection()
    selected_id = st.session_state.get(_SELECTED_PROJECT_KEY)
    if selected_id is not None:
        detail = workspace.portfolio.get_detail(int(selected_id))
        if detail is not None:
            selected = pd.Series({**detail, "id": detail["project_id"]})
            for key in ("project_manager", "level_3_manager_name"):
                selected[key] = selected.get(key) or "—"
            _render_project_details_panel(selected, params, workspace)


@st.fragment
def render_portfolio_overview(workspace: ProjectWorkspace) -> None:
    """Handle safe failures inside each fragment run of the compact project list."""
    try:
        _render_portfolio_browser(workspace)
    except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
        st.error(str(exc))
