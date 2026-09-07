"""Screen 1: Portfolio Overview View with Interactive Master List and Details Inspection."""

import json
from typing import Any, Optional

import pandas as pd
import streamlit as st

from src.i18n import t
from src.models.constants import (
    PARAM_TYPE_HYPERLINK,
    PARAM_TYPE_NUMBER,
    PARAM_TYPE_TEXT,
    PARAM_TYPE_URL,
    STATUS_LIST,
)
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository
from src.repositories.tag_repo import TagRepository
from src.services.organization_service import OrganizationService
from src.services.portfolio_service import PortfolioService
from src.services.schema_service import SchemaService
from src.views.portfolio_table_component import portfolio_project_table
from src.views.project_master_view import _render_dynamic_field

ALLOWED_DYNAMIC_PARAMS: set[str] = {
    "phase",
    "code_line",
    "strategic_priority",
    "category",
    "category_tags",
    "complexity",
}


def _normalise_flex_filter_values(value: Any) -> list[str]:
    """Convert scalar, list, and JSON-list cells into comparable display values."""
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except (json.JSONDecodeError, TypeError):
                decoded = None
            if isinstance(decoded, list):
                return [str(item).strip() for item in decoded if str(item).strip()]
        return [stripped]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    return [str(value).strip()]


def _unique_flex_filter_options(series: pd.Series) -> list[str]:
    """Return sorted unique values from scalar or multi-valued DataFrame cells."""
    values = {
        item
        for value in series.tolist()
        for item in _normalise_flex_filter_values(value)
        if item
    }
    return sorted(values, key=str.casefold)


def _apply_portfolio_flex_filters(
    frame: pd.DataFrame,
    filters: dict[str, list[str]],
    match_all_values: bool = False,
) -> pd.DataFrame:
    """Apply flexible field filters with AND across fields and configurable value matching."""
    filtered = frame.copy()
    for column, selected_values in filters.items():
        if column not in filtered.columns or not selected_values:
            continue
        wanted = {str(value).casefold() for value in selected_values}

        def cell_matches(value: Any) -> bool:
            actual = {
                item.casefold()
                for item in _normalise_flex_filter_values(value)
            }
            return wanted.issubset(actual) if match_all_values else bool(wanted & actual)

        filtered = filtered[filtered[column].apply(cell_matches)]
    return filtered


def _project_tag_map(tag_repo: TagRepository) -> dict[int, list[str]]:
    """Return project tags grouped by project ID for flexible filtering."""
    assignments = tag_repo.get_all_project_tags()
    tags_by_project: dict[int, list[str]] = {}
    for _, row in assignments.iterrows():
        project_id = int(row["project_id"])
        labels = tags_by_project.setdefault(project_id, [])
        if pd.notna(row.get("tag_name")):
            tag_name = str(row["tag_name"])
            group_name = row.get("tag_group_name")
            label = (
                f"{group_name} · {tag_name}"
                if pd.notna(group_name) and str(group_name).strip()
                else tag_name
            )
            if label not in labels:
                labels.append(label)
        if pd.notna(row.get("free_tag")) and str(row["free_tag"]).strip():
            free_label = str(row["free_tag"]).strip()
            if free_label not in labels:
                labels.append(free_label)
    return tags_by_project


def _clear_portfolio_flex_filter_state() -> None:
    """Clear only session-state keys owned by the portfolio flexible filter."""
    for key in list(st.session_state):
        if str(key).startswith("portfolio_flex_"):
            del st.session_state[key]


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


def _dynamic_project_value(attributes: dict[str, Any], parameter: pd.Series) -> Any:
    """Find an existing dynamic value by ID, name, or alias."""
    param_id = str(parameter["param_id"])
    param_name = str(parameter.get("param_name", ""))
    alias = str(parameter.get("alias", "")).strip() if pd.notna(parameter.get("alias")) else ""
    value = attributes.get(param_id)
    if value is None and param_name:
        value = attributes.get(param_name)
    if value is None and alias:
        value = attributes.get(alias)
    return value


@st.dialog("Edit project details", width="large")
def _edit_project_details_dialog(
    project_id: int,
    project_repo: ProjectRepository,
    schema_repo: SchemaRepository,
) -> None:
    """Edit the selected project without navigating away from the portfolio."""
    project = project_repo.get_project_by_id(project_id)
    if project is None:
        st.error("The selected project no longer exists.")
        return

    groups = schema_repo.get_all_groups()
    params = schema_repo.get_all_parameters()
    options = schema_repo.get_all_options()
    org_repo = OrganizationRepository(project_repo.db_path)
    functions = org_repo.get_all_functions()
    employees = org_repo.get_all_employees()
    manager_names = OrganizationService.get_function_occupant_names(functions, employees)
    manager_options: list[Optional[int]] = [None]
    if not functions.empty:
        manager_options.extend(int(value) for value in functions["function_id"].tolist())
    manager_labels: dict[Optional[int], str] = {None: "— None —", **manager_names}

    current_manager = int(project.function_id) if project.function_id is not None else None
    manager_index = manager_options.index(current_manager) if current_manager in manager_options else 0
    attributes = dict(project.dynamic_attributes or {})

    with st.form(f"portfolio_edit_project_{project_id}"):
        id_col, name_col, status_col = st.columns([1, 2, 1])
        id_col.text_input(t("master_data.field_id"), value=str(project_id), disabled=True)
        edit_name = name_col.text_input(t("master_data.field_name"), value=project.name)
        status_index = STATUS_LIST.index(project.status) if project.status in STATUS_LIST else 0
        edit_status = status_col.selectbox(
            t("master_data.field_status"),
            options=STATUS_LIST,
            index=status_index,
        )

        planned_col, actual_col, manager_col = st.columns(3)
        edit_planned = planned_col.number_input(
            t("master_data.field_planned"),
            min_value=0.0,
            value=float(project.planned_budget),
            step=5000.0,
        )
        edit_actual = actual_col.number_input(
            t("master_data.field_actual"),
            min_value=0.0,
            value=float(project.actual_budget),
            step=5000.0,
        )
        edit_manager = manager_col.selectbox(
            t("master_data.field_project_manager", default="Project Manager"),
            options=manager_options,
            index=manager_index,
            format_func=lambda value: manager_labels.get(value, str(value)),
            key=f"portfolio_edit_manager_{project_id}",
        )

        st.write(f"#### {t('master_data.dynamic_section')}")
        dynamic_values: dict[str, Any] = {}
        grouped_ids: set[Any] = set()
        if not groups.empty and not params.empty:
            for _, group in groups.iterrows():
                group_id = group["id"]
                group_params = params[params["group_id"] == group_id]
                if group_params.empty:
                    continue
                grouped_ids.add(group_id)
                with st.expander(f"📁 {group['group_name']}", expanded=True):
                    for _, parameter in group_params.iterrows():
                        param_id = str(parameter["param_id"])
                        dynamic_values[param_id] = _render_dynamic_field(
                            parameter,
                            options,
                            _dynamic_project_value(attributes, parameter),
                            f"portfolio_edit_{project_id}",
                        )

        if not params.empty:
            ungrouped = params[params["group_id"].isna() | ~params["group_id"].isin(grouped_ids)]
            if not ungrouped.empty:
                with st.expander(f"📌 {t('schema.param_group_none')}", expanded=True):
                    for _, parameter in ungrouped.iterrows():
                        param_id = str(parameter["param_id"])
                        dynamic_values[param_id] = _render_dynamic_field(
                            parameter,
                            options,
                            _dynamic_project_value(attributes, parameter),
                            f"portfolio_edit_{project_id}",
                        )

        if st.form_submit_button(t("master_data.btn_update"), width="stretch"):
            clean_name = edit_name.strip()
            missing = SchemaService.validate_project_dynamic_attributes(dynamic_values, params)
            if not clean_name:
                st.error(t("master_data.err_required_fields"))
            elif missing:
                st.error(
                    "Cannot update project: The following mandatory attributes are required: "
                    + ", ".join(missing)
                )
            else:
                project_repo.update_project(
                    project_id=project_id,
                    name=clean_name,
                    status=edit_status,
                    planned_budget=edit_planned,
                    actual_budget=edit_actual,
                    dynamic_attributes=dynamic_values,
                    function_id=edit_manager,
                )
                st.toast("Project details updated.", icon="✅")
                st.rerun()


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
            _edit_project_details_dialog(int(proj_id), project_repo, schema_repo)

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
    tag_repo: Optional[TagRepository] = None,
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
    df_employees = org_repo.get_all_employees()
    df_merged = OrganizationService.enrich_projects_with_organization(
        df_merged,
        df_funcs,
        df_employees,
    )
    if tag_repo is not None:
        tags_by_project = _project_tag_map(tag_repo)
        df_merged["_project_tags"] = df_merged["id"].map(
            lambda project_id: tags_by_project.get(int(project_id), [])
        )
    else:
        df_merged["_project_tags"] = [[] for _ in range(len(df_merged))]

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
    flex_filter_fields: dict[str, str] = {
        "Status": "status",
        "Project Manager": "project_manager",
        "Managing Function (Level 3)": "level_3_manager_name",
        "Project Tags": "_project_tags",
    }

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
            flex_filter_fields[pname] = target_col

            value_format = "url" if ptype in (PARAM_TYPE_URL, PARAM_TYPE_HYPERLINK) else "text"
            if ptype == PARAM_TYPE_NUMBER:
                value_format = "number"
            table_columns.append({"key": target_col, "label": pname, "format": value_format})

    # 4. Search and reusable multi-criteria flexible filter
    search_col, flex_col = st.columns([4, 1])
    with search_col:
        search_term = st.text_input(
            t("portfolio.filter_search"),
            placeholder=t("portfolio.filter_search_placeholder"),
        )
    active_filters: dict[str, list[str]] = {}
    with flex_col:
        with st.popover("⚙️ Flexible filters", width="stretch"):
            selected_fields = st.multiselect(
                "Filter fields",
                options=list(flex_filter_fields),
                placeholder="Choose one or more fields",
                key="portfolio_flex_fields",
            )
            match_mode = st.segmented_control(
                "When several values are selected",
                options=["Any", "All"],
                default="Any",
                key="portfolio_flex_match_mode",
                help="Fields use AND. This controls matching within each field.",
            )
            for field_label in selected_fields:
                target_column = flex_filter_fields[field_label]
                options = _unique_flex_filter_options(df_merged[target_column])
                selected_values = st.multiselect(
                    field_label,
                    options=options,
                    placeholder="All values",
                    key=f"portfolio_flex_values::{target_column}",
                )
                if selected_values:
                    active_filters[target_column] = selected_values
            st.button(
                "Clear filters",
                on_click=_clear_portfolio_flex_filter_state,
                width="stretch",
                disabled=not selected_fields,
            )

    filtered_df = _apply_portfolio_flex_filters(
        df_merged,
        active_filters,
        match_all_values=match_mode == "All",
    )
    if search_term.strip():
        term = search_term.lower()
        filtered_df = filtered_df[
            filtered_df["id"].astype(str).str.lower().str.contains(term, na=False)
            | filtered_df["name"].astype(str).str.lower().str.contains(term, na=False)
        ]
    if active_filters:
        st.caption(
            f"{len(active_filters)} active flexible filter"
            f"{'s' if len(active_filters) != 1 else ''} · {len(filtered_df)} matching projects"
        )

    # 5. Render Data Grid with direct row selection and per-column filters
    st.subheader(t("portfolio.table_header", count=len(filtered_df)))
    st.caption(
        t(
            "portfolio.details_hint",
            default="💡 Click on any project in the table above to display its details below.",
        )
    )

    available_cols = [c for c in display_cols if c in filtered_df.columns]
    filtered_df_reset = filtered_df.reset_index(drop=True)
    available_column_specs = [column for column in table_columns if column["key"] in available_cols]
    clicked_project_id = portfolio_project_table(
        _build_portfolio_table_rows(filtered_df_reset, available_cols),
        available_column_specs,
        st.session_state.get("selected_portfolio_project_id"),
        key="portfolio_master_table",
    )

    # 6. Render Project Details Below the Master List
    if clicked_project_id is not None:
        st.session_state["selected_portfolio_project_id"] = clicked_project_id

    selected_pid = st.session_state.get("selected_portfolio_project_id")
    if selected_pid is not None:
        matching = df_merged[df_merged["id"].astype(str) == str(selected_pid)]
        if not matching.empty:
            selected_proj = matching.iloc[0]
            _render_project_details_panel(selected_proj, params, project_repo, schema_repo)
