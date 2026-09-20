"""Lazy organization catalog sections for the existing Settings navigation."""

from app.presentation.assets import component_path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from app.application.services.organization import OrganizationService
from app.presentation.components.organization_dialogs import (
    organization_errors,
    _open_add_function_dialog,
    _open_edit_function_dialog,
    _open_delete_function_dialog,
    _open_add_function_type_dialog,
    _open_edit_function_type_dialog,
    _open_delete_function_type_dialog,
    _open_add_employee_dialog,
    _open_edit_employee_dialog,
    _open_delete_employee_dialog,
)
from app.presentation.components.organization_frames import (
    employees_frame, function_types_frame, functions_frame,
    enrich_employees,
)
from app.presentation.components.function_csv import function_csv_controls
from app.presentation.components.function_tree import function_tree
from app.presentation.i18n import t


def _table(name: str, **kwargs: object) -> dict[str, object] | None:
    """Bind an existing table asset in the active Streamlit runtime.

    Args:
        name: Internal component name; not supplied by the browser.
        **kwargs: Dynamic JSON payload at the custom-component boundary.

    Returns:
        The component's event object, or None when there is no event.
    """
    asset = component_path(name)
    component = components.declare_component("interactive_" + name, path=str(asset))
    event = component(**kwargs)
    return event if isinstance(event, dict) else None


@organization_errors
def render_functions(service: OrganizationService) -> None:
    """Manage reporting hierarchies, deleted functions and atomic CSV imports."""
    show_deleted = st.checkbox('Show deleted functions', value=False, key='function_show_deleted')
    function_csv_controls(service, show_deleted=show_deleted)
    records = service.get_all_functions(include_deleted=show_deleted)
    types = service.get_all_function_types()
    active = [item for item in records if not item.deleted_flag]
    total, capacity = st.columns(2)
    total.metric('Total Functions', len(active))
    capacity.metric('FTE', f'{sum(item.fte_percentage for item in active) / 100:.2f}')
    selected = st.session_state.get('selected_function_id', 0)
    event = function_tree(records, selected, {item.function_type_id: item.function_type for item in types})
    if not event:
        return
    identity, action = event['id'], event['action']
    frame, type_frame = functions_frame(active), function_types_frame(types)
    if action in {'create', 'create_root'}:
        _open_add_function_dialog(service, frame, type_frame,
                                  parent_function_id=identity if action == 'create' else None)
    elif action == 'edit':
        _open_edit_function_dialog(service, identity, frame, type_frame)
    elif action == 'delete':
        name = next(item.name for item in records if item.function_id == identity)
        _open_delete_function_dialog(service, identity, name)
    elif action == 'undelete' and service.undelete_function(identity):
        st.toast('Function restored.')
        st.rerun()


@organization_errors
def render_function_types(service: OrganizationService) -> None:
    """Render the function types catalog only when its tab is open."""
    st.link_button(t('settings.export_csv'), '/downloads/organization/function_types.csv')
    df_types = function_types_frame(service.get_all_function_types())
    total_types = len(df_types)
    st.subheader(f"{t('settings.types_title', default='Function Types Management')} ({total_types} {t('settings.stat_types', default='Types')})")

    types_payload = []
    if not df_types.empty:
        for row in df_types.to_dict(orient="records"):
            types_payload.append({
                "function_type_id": int(row["function_type_id"]),
                "function_type": str(row["function_type"]),
            })

    type_table_event = _table("function_type_table",
        types=types_payload,
        translations={
            "col_id": "ID",
            "col_type_name": t("settings.col_type_name", default="Function Type Name"),
            "action_add": t("settings.action_add", default="Add New"),
            "action_edit": t("settings.action_edit", default="Edit"),
            "action_delete": t("settings.action_delete", default="Delete"),
            "no_types": t("settings.no_types", default="No function types registered."),
            "stat_types": t("settings.stat_types", default="Types"),
            "filter_all": t("settings.filter_all", default="All"),
            "filter_clear": t("settings.filter_clear", default="Clear Filters"),
            "col_filter_ph": t("settings.col_filter_ph", default="Filter..."),
            "search_values": t("settings.search_values", default="Search values..."),
            "select_all": t("settings.select_all", default="Select All"),
            "clear": t("settings.clear", default="Clear"),
            "apply": t("settings.apply", default="Apply"),
            "selected_count": t("settings.selected_count", default="{count} selected"),
            "blanks": t("settings.blanks", default="(Blanks / None)"),
        },
        key="type_interactive_table",
        default=None,
    )

    if type_table_event and isinstance(type_table_event, dict):
        nonce = type_table_event.get("nonce")
        last_nonce = st.session_state.get("_last_type_table_nonce")
        if nonce and nonce != last_nonce:
            st.session_state["_last_type_table_nonce"] = nonce
            action = type_table_event.get("action")
            if action == "add_function_type":
                _open_add_function_type_dialog(service)
            elif action == "edit_function_type":
                ft_id = type_table_event.get("function_type_id")
                ft_name = type_table_event.get("function_type_name", "")
                if ft_id is not None:
                    _open_edit_function_type_dialog(service, int(ft_id), str(ft_name))
            elif action == "delete_function_type":
                ft_id = type_table_event.get("function_type_id")
                ft_name = type_table_event.get("function_type_name", f"ID {ft_id}")
                if ft_id is not None:
                    _open_delete_function_type_dialog(service, int(ft_id), str(ft_name))


def render_teams(service: OrganizationService) -> None:
    """Render the shared hierarchy-based team administration page."""
    from app.presentation.pages.teams import render_teams as render_team_hierarchy

    render_team_hierarchy(service)


@organization_errors
def render_employees(service: OrganizationService) -> None:
    """Render the employees catalog only when its tab is open."""
    from app.presentation.components.employee_csv import employee_csv_controls

    employee_csv_controls(service, show_deleted=False)
    df_types = function_types_frame(service.get_all_function_types())
    df_funcs = functions_frame(service.get_all_functions())
    employee_records = service.get_all_employees()
    df_emps = employees_frame(employee_records)
    total_emps = len(df_emps)
    st.subheader(f"{t('settings.employees_title', default='Employee Directory & Profile Management')} ({total_emps} {t('settings.stat_employees', default='Employees')})")

    enriched_emps = enrich_employees(df_emps, df_funcs, df_types)
    function_names = dict(zip(df_funcs['function_id'], df_funcs['name']))
    people = {person.employee_id: person for person in employee_records}
    emps_payload = []
    if not enriched_emps.empty:
        for row in enriched_emps.to_dict(orient="records"):
            assignments = [item for item in people[int(row['employee_id'])].assignments() if item.function_id in function_names]
            assigned = sum(item.allocation_pct for item in assignments)
            description = ', '.join(f'{function_names[item.function_id]}: {item.allocation_pct:.0f}%' for item in assignments)
            emps_payload.append({
                'overallocated': assigned > 100,
                'allocation_warning': f'{assigned:.0f}% allocated across active functions. {description}' if assigned > 100 else '',
                "employee_id": int(row["employee_id"]),
                "full_name": str(row.get("full_name") or ""),
                "email": str(row.get("email") or ""),
                "mobile": str(row.get("mobile") or ""),
                "landline": str(row.get("landline") or ""),
                "sigle": str(row.get("sigle") or ""),
                "function_id": int(row["function_id"]) if pd.notna(row.get("function_id")) else None,
                "function_name": description or '—',
                "function_type_name": str(row.get("function_type_name") or "—"),
                "occupation_percentage": float(row.get("occupation_percentage", 100.0)),
            })

    emp_table_event = _table("employee_table",
        employees=emps_payload,
        translations={
            "col_full_name": t("settings.col_full_name", default="Full Name"),
            "col_mobile": t("settings.col_mobile", default="Mobile"),
            "col_landline": t("settings.col_landline", default="Landline"),
            "col_sigle": t("settings.col_sigle", default="Sigle"),
            "col_function": t("settings.col_function", default="Function"),
            "col_type": t("settings.col_type", default="Function Type"),
            "col_occupation_percentage": t("settings.col_occupation_percentage", default="Occupation %"),
            "action_add": t("settings.action_add", default="Add New"),
            "action_edit": t("settings.action_edit", default="Edit"),
            "action_delete": t("settings.action_delete", default="Delete"),
            "no_employees": t("settings.no_employees", default="No employees registered."),
            "stat_employees": t("settings.stat_employees", default="Employees"),
            "filter_all": t("settings.filter_all", default="All"),
            "filter_clear": t("settings.filter_clear", default="Clear Filters"),
            "col_filter_ph": t("settings.col_filter_ph", default="Filter..."),
            "search_values": t("settings.search_values", default="Search values..."),
            "select_all": t("settings.select_all", default="Select All"),
            "clear": t("settings.clear", default="Clear"),
            "apply": t("settings.apply", default="Apply"),
            "selected_count": t("settings.selected_count", default="{count} selected"),
            "blanks": t("settings.blanks", default="(Blanks / None)"),
        },
        key="emp_interactive_table",
        default=None,
    )

    if emp_table_event and isinstance(emp_table_event, dict):
        nonce = emp_table_event.get("nonce")
        last_nonce = st.session_state.get("_last_emp_table_nonce")
        if nonce and nonce != last_nonce:
            st.session_state["_last_emp_table_nonce"] = nonce
            action = emp_table_event.get("action")
            if action == "add_employee":
                _open_add_employee_dialog(service, df_funcs)
            elif action == "edit_employee":
                e_id = emp_table_event.get("employee_id")
                if e_id is not None:
                    _open_edit_employee_dialog(service, int(e_id), df_funcs)
            elif action == "delete_employee":
                e_id = emp_table_event.get("employee_id")
                e_name = emp_table_event.get("full_name", f"ID {e_id}")
                if e_id is not None:
                    _open_delete_employee_dialog(service, int(e_id), str(e_name))

    st.caption(
        t(
            "settings.calendar_exceptions_in_profile_help",
            default="Add or edit an employee profile to manage that employee's calendar exceptions.",
        )
    )


