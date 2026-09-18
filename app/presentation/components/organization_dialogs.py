"""Organization controls using injected application services."""

import datetime
from collections.abc import Callable
from functools import wraps

import pandas as pd
import streamlit as st

from app.presentation.components.dialog import dialog
from app.presentation.components.hierarchy import hierarchy_type_selector

from app.application.exceptions import OrganizationStorageError
from app.application.services.organization import OrganizationService
from app.domain.organization.models import Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team
from app.domain.organization.rules import (
    validate_employee, validate_employee_calendar_exception, validate_function, validate_team,
)
from app.presentation.components.organization_frames import exceptions_frame
from app.presentation.i18n import t


def organization_errors[**P](render: Callable[P, None]) -> Callable[P, None]:
    """Display safe application errors, including reads and dialog reruns."""
    @wraps(render)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            render(*args, **kwargs)
        except (ValueError, OrganizationStorageError) as exc:
            st.error(str(exc))
    return guarded


def require_change(changed: bool) -> None:
    """Keep concurrent deletion from being reported as a successful edit."""
    if not changed:
        raise ValueError("This record no longer exists. Please refresh and try again.")


@dialog(t("settings.dialog_add_func", default="Create Job Function"))
@organization_errors
def _open_add_function_dialog(
    service: OrganizationService,
    df_funcs: pd.DataFrame,
    df_types: pd.DataFrame,
    parent_function_id: int | None = None,
) -> None:
    """Modal dialog to create a new job function."""
    new_name = st.text_input(t("settings.field_func_name", default="Function Title *"), placeholder="e.g. Solution Architect")

    type_opts = [None] + (df_types["function_type_id"].tolist() if not df_types.empty else [])
    type_map = dict(zip(df_types["function_type_id"], df_types["function_type"])) if not df_types.empty else {}
    new_type = st.selectbox(
        t("settings.field_type", default="Function Type"),
        options=type_opts,
        format_func=lambda x: type_map.get(x, "— None") if x is not None else "— None",
    )

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    new_mgr = st.selectbox(
        t("settings.field_primary_mgr", default="Primary Manager Function (Optional)"),
        options=func_opts,
        index=func_opts.index(parent_function_id) if parent_function_id in func_opts else 0,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )
    new_dual = st.selectbox(
        t("settings.field_dual_mgr", default="Dual / Matrix Manager Function (Optional)"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )
    new_fte = st.number_input(
        t("settings.field_fte_pct", default="FTE Workload % (0-100)"),
        min_value=0,
        max_value=100,
        value=100,
        step=5,
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="Save Function"), type="primary", width="stretch"):
        try:
            validate_function(new_name, int(new_fte))
            new_fid = service.create_function(
                OrgFunction(
                    name=new_name,
                    function_type_id=new_type,
                    manager_function_id=new_mgr,
                    dual_manager_function_id=new_dual,
                    fte_percentage=int(new_fte),
                )
            )
            st.toast(t("settings.msg_func_created", name=new_name, default=f"Function '{new_name}' created (ID: {new_fid})!"))
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except OrganizationStorageError as e:
            st.error(str(e))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.dialog_edit_func", default="Edit Job Function"))
@organization_errors
def _open_edit_function_dialog(
    service: OrganizationService,
    func_id: int,
    df_funcs: pd.DataFrame,
    df_types: pd.DataFrame,
) -> None:
    """Modal dialog to edit an existing job function."""
    fn_obj = service.get_function_by_id(func_id)
    if not fn_obj:
        st.error("Function not found.")
        return

    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    type_map = dict(zip(df_types["function_type_id"], df_types["function_type"])) if not df_types.empty else {}

    edit_name = st.text_input(t("settings.field_func_name", default="Function Title *"), value=fn_obj.name)

    type_opts = [None] + (df_types["function_type_id"].tolist() if not df_types.empty else [])
    edit_type_idx = type_opts.index(fn_obj.function_type_id) if fn_obj.function_type_id in type_opts else 0
    edit_type = st.selectbox(
        t("settings.field_type", default="Function Type"),
        options=type_opts,
        index=edit_type_idx,
        format_func=lambda x: type_map.get(x, "— None") if x is not None else "— None",
    )

    mgr_opts = [None] + [fid for fid in df_funcs["function_id"].tolist() if fid != func_id]
    mgr_idx = mgr_opts.index(fn_obj.manager_function_id) if fn_obj.manager_function_id in mgr_opts else 0
    edit_mgr = st.selectbox(
        t("settings.field_primary_mgr", default="Primary Manager Function"),
        options=mgr_opts,
        index=mgr_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    dual_idx = mgr_opts.index(fn_obj.dual_manager_function_id) if fn_obj.dual_manager_function_id in mgr_opts else 0
    edit_dual = st.selectbox(
        t("settings.field_dual_mgr", default="Dual / Matrix Manager Function"),
        options=mgr_opts,
        index=dual_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    edit_fte = st.number_input(
        t("settings.field_fte_pct", default="FTE Workload % (0-100)"),
        min_value=0,
        max_value=100,
        value=fn_obj.fte_percentage if fn_obj.fte_percentage is not None else 100,
        step=5,
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="Save Changes"), type="primary", width="stretch"):
        try:
            validate_function(edit_name, int(edit_fte))
            require_change(service.update_function(
                OrgFunction(
                    function_id=func_id,
                    name=edit_name,
                    function_type_id=edit_type,
                    manager_function_id=edit_mgr,
                    dual_manager_function_id=edit_dual,
                    fte_percentage=int(edit_fte),
                )
            ))
            st.toast(t("settings.msg_func_updated", default="Function updated successfully!"))
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except OrganizationStorageError as e:
            st.error(str(e))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.delete_confirm_title", default="Confirm Deletion"))
@organization_errors
def _open_delete_function_dialog(
    service: OrganizationService,
    func_id: int,
    func_name: str,
) -> None:
    """Modal dialog to confirm deletion of a job function."""
    st.warning(f"{t('settings.delete_confirm_msg', name=func_name, default=f'Are you sure you want to delete Function **{func_name}** (ID: {func_id})?')}")
    st.caption("The record will be marked as deleted. Its history and mappings will be retained.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="Yes, Delete"), type="primary", width="stretch"):
        require_change(service.delete_function(func_id))
        st.toast(t("settings.msg_func_deleted", default=f"Function '{func_name}' deleted."))
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


def _parent_team_selector(service: OrganizationService, team: Team | None = None,
                          *, default_parent: int | None = None) -> int | None:
    """Offer an optional parent, excluding the edited team and its descendants."""
    teams = service.get_all_teams()
    blocked = {team.team_id} if team else set()
    while True:
        descendants = {item.team_id for item in teams if item.parent_team_id in blocked}
        if descendants <= blocked:
            break
        blocked |= descendants
    labels = {item.team_id: f'{item.team_name} (#{item.team_id})'
              for item in teams if item.team_id not in blocked}
    # None also represents an empty Streamlit widget state; use an explicit option.
    options = [0, *labels]
    current = team.parent_team_id if team else default_parent
    unassigned_label = t('settings.no_parent_team')
    value = st.selectbox(
        t('settings.field_parent_team'), options,
        index=options.index(current) if current in options else 0,
        format_func=lambda value: labels[value] if value else unassigned_label,
        key=f'parent_team_{team.team_id if team else "new"}',
    )
    return value or None


@dialog(t("settings.dialog_add_team", default="Create Team"))
@organization_errors
def _open_add_team_dialog(
    service: OrganizationService,
    df_funcs: pd.DataFrame,
    *, parent_team_id: int | None = None,
) -> None:
    """Modal dialog to create a new team."""
    new_name = st.text_input(t("settings.field_team_name", default="Team Name *"), placeholder="e.g. Equipe BIM")
    hierarchy_type_id = hierarchy_type_selector(service.get_all_hierarchy_types())
    parent_team_id = _parent_team_selector(service, default_parent=parent_team_id)

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}

    new_mgr = st.selectbox(
        t("settings.field_team_mgr", default="Manager Function (Optional)"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )
    member_opts = df_funcs["function_id"].tolist() if not df_funcs.empty else []
    from app.presentation.components.employee_editors import team_member_labels
    member_labels = team_member_labels(service, func_map)
    new_members = st.multiselect(
        t("settings.field_team_members", default="Team Member Functions"),
        options=member_opts,
        format_func=lambda x: member_labels.get(x, f"Function #{x}"),
        help="Select functions belonging to this team.",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="Save Team"), type="primary", width="stretch"):
        try:
            validate_team(new_name)
            new_tid = service.create_team(
                Team(
                    team_name=new_name,
                    manager_function_id=new_mgr,
                    hierarchy_type_id=hierarchy_type_id,
                    parent_team_id=parent_team_id,
                ), function_ids=new_members,
            )
            st.toast(t("settings.msg_team_created", name=new_name, default=f"Team '{new_name}' created (ID: {new_tid})!"))
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except OrganizationStorageError as e:
            st.error(str(e))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.dialog_edit_team", default="Edit Team"))
@organization_errors
def _open_edit_team_dialog(
    service: OrganizationService,
    team_id: int,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to edit an existing team."""
    team_obj = service.get_team_by_id(team_id)
    if not team_obj:
        st.error("Team not found.")
        return

    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    edit_name = st.text_input(t("settings.field_team_name", default="Team Name *"), value=team_obj.team_name)
    hierarchy_type_id = hierarchy_type_selector(service.get_all_hierarchy_types(), team_obj.hierarchy_type_id)
    parent_team_id = _parent_team_selector(service, team_obj)

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    mgr_idx = func_opts.index(team_obj.manager_function_id) if team_obj.manager_function_id in func_opts else 0
    edit_mgr = st.selectbox(
        t("settings.field_team_mgr", default="Manager Function"),
        options=func_opts,
        index=mgr_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    current_members = service.get_team_functions(team_id)
    from app.presentation.components.employee_editors import team_member_labels
    member_labels = team_member_labels(service, func_map)
    member_opts = df_funcs["function_id"].tolist() if not df_funcs.empty else []
    edit_members = st.multiselect(
        t("settings.field_team_members", default="Team Member Functions"),
        options=member_opts,
        default=[fid for fid in current_members if fid in member_opts],
        format_func=lambda x: member_labels.get(x, f"Function #{x}"),
        help="Select functions belonging to this team.",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="Save Changes"), type="primary", width="stretch"):
        try:
            validate_team(edit_name)
            require_change(service.update_team(
                Team(
                    team_id=team_id,
                    team_name=edit_name,
                    manager_function_id=edit_mgr,
                    hierarchy_type_id=hierarchy_type_id,
                    parent_team_id=parent_team_id,
                ), function_ids=edit_members,
            ))
            st.toast(t("settings.msg_team_updated", default="Team updated successfully!"))
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except OrganizationStorageError as e:
            st.error(str(e))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.delete_confirm_title", default="Confirm Deletion"))
@organization_errors
def _open_delete_team_dialog(
    service: OrganizationService,
    team_id: int,
    team_name: str,
) -> None:
    """Modal dialog to confirm deletion of a team."""
    st.warning(f"{t('settings.delete_confirm_msg', name=team_name, default=f'Are you sure you want to delete Team **{team_name}** (ID: {team_id})?')}")
    st.caption("The record will be marked as deleted. Its history and mappings will be retained.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="Yes, Delete"), type="primary", width="stretch"):
        require_change(service.delete_team(team_id))
        st.toast(t("settings.msg_team_deleted", default=f"Team '{team_name}' deleted."))
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.dialog_add_type", default="Create Function Type"))
@organization_errors
def _open_add_function_type_dialog(service: OrganizationService) -> None:
    """Modal dialog to create a new function type."""
    new_name = st.text_input(t("settings.field_type_name", default="Function Type *"), placeholder="e.g. Contractor")

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="Save Type"), type="primary", width="stretch"):
        clean_name = new_name.strip()
        if clean_name:
            try:
                new_tid = service.create_function_type(FunctionType(function_type=clean_name))
                st.toast(t("settings.msg_type_created", name=clean_name, default=f"Function Type '{clean_name}' created (ID: {new_tid})!"))
                st.rerun()
            except OrganizationStorageError as e:
                st.error(str(e))
        else:
            st.error(t("settings.err_type_name_empty", default="Function type name cannot be empty."))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.dialog_edit_type", default="Edit Function Type"))
@organization_errors
def _open_edit_function_type_dialog(
    service: OrganizationService,
    type_id: int,
    current_name: str,
) -> None:
    """Modal dialog to edit an existing function type."""
    edit_name = st.text_input(t("settings.field_type_name", default="Function Type *"), value=current_name)

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="Save Changes"), type="primary", width="stretch"):
        clean_name = edit_name.strip()
        if clean_name:
            try:
                require_change(service.update_function_type(FunctionType(function_type_id=type_id, function_type=clean_name)))
                st.toast(t("settings.msg_type_updated", default="Function Type updated successfully!"))
                st.rerun()
            except OrganizationStorageError as e:
                st.error(str(e))
        else:
            st.error(t("settings.err_type_name_empty", default="Function type name cannot be empty."))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.delete_confirm_title", default="Confirm Deletion"))
@organization_errors
def _open_delete_function_type_dialog(
    service: OrganizationService,
    type_id: int,
    type_name: str,
) -> None:
    """Modal dialog to confirm deletion of a function type."""
    st.warning(f"{t('settings.delete_confirm_msg', name=type_name, default=f'Are you sure you want to delete Function Type **{type_name}** (ID: {type_id})?')}")
    st.caption("The record will be marked as deleted. Its history and mappings will be retained.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="Yes, Delete"), type="primary", width="stretch"):
        require_change(service.delete_function_type(type_id))
        st.toast(t("settings.msg_type_deleted", default=f"Function Type '{type_name}' deleted."))
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.dialog_add_emp", default="Add New Employee"))
@organization_errors
def _open_add_employee_dialog(
    service: OrganizationService,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to create a new employee profile."""
    new_sigle = st.text_input(t("settings.field_sigle", default="Sigle / Trigram"), placeholder="e.g. SCO")

    c_n1, c_n2 = st.columns(2)
    new_first = c_n1.text_input(t("settings.field_firstname", default="First Name *"), placeholder="Sarah")
    new_last = c_n2.text_input(t("settings.field_lastname", default="Last Name *"), placeholder="Connor")

    c_m1, c_m2 = st.columns(2)
    new_email = c_m1.text_input(t("settings.field_email", default="Email *"), placeholder="sconnor@enterprise.com")
    new_mobile = c_m2.text_input(t("settings.field_mobile", default="Mobile / Phone"), placeholder="+1-555-0101")
    new_landline = st.text_input(t("settings.field_landline", default="Landline"), placeholder="+352 27 000 001")

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    c_role, c_occupation = st.columns([2, 1])
    new_func = c_role.selectbox(
        t("settings.field_function", default="Function Role"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )
    new_occupation = c_occupation.number_input(
        t("settings.field_occupation_percentage", default="Occupation %"),
        min_value=0.0,
        max_value=100.0,
        value=100.0,
        step=5.0, format="%.0f",
    )

    st.divider()
    with st.expander(
        t(
            "settings.calendar_exceptions_title",
            default="Employee Calendar Exceptions",
        )
    ):
        add_initial_exception = st.checkbox(
            t(
                "settings.add_initial_calendar_exception",
                default="Add an initial calendar exception",
            ),
            key="new_employee_add_initial_exception",
        )
        initial_exception_start = datetime.date.today()
        initial_exception_end = datetime.date.today()
        initial_exception_percentage = 0.0
        initial_exception_reason = ""
        if add_initial_exception:
            exc_start_col, exc_end_col = st.columns(2)
            initial_exception_start = exc_start_col.date_input(
                t("settings.field_start_date", default="Start date"),
                value=datetime.date.today(),
                key="new_employee_exception_start",
            )
            initial_exception_end = exc_end_col.date_input(
                t("settings.field_end_date", default="End date"),
                value=datetime.date.today(),
                key="new_employee_exception_end",
            )
            initial_exception_percentage = st.number_input(
                t(
                    "settings.field_exception_percentage",
                    default="Working percentage during period",
                ),
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=5.0, format="%.0f",
                key="new_employee_exception_percentage",
            )
            initial_exception_reason = st.text_input(
                t("settings.field_exception_reason", default="Reason (optional)"),
                placeholder=t(
                    "settings.exception_reason_placeholder",
                    default="e.g. Maternity leave",
                ),
                key="new_employee_exception_reason",
            )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="Save Employee"), type="primary", width="stretch"):
        try:
            validate_employee(
                new_first, new_last, new_email, new_occupation
            )
            if add_initial_exception:
                validate_employee_calendar_exception(
                    initial_exception_start,
                    initial_exception_end,
                    initial_exception_percentage,
                )
            if service.check_email_exists(new_email):
                st.error(t("settings.err_email_taken", email=new_email, default=f"Email '{new_email}' is already registered."))
            else:
                initial_exception = (
                    EmployeeCalendarException(
                        employee_id=0, start_date=initial_exception_start,
                        end_date=initial_exception_end,
                        occupation_percentage=initial_exception_percentage,
                        reason=initial_exception_reason,
                    ) if add_initial_exception else None
                )
                new_eid = service.create_employee(
                    Employee(
                        firstname=new_first, lastname=new_last, email=new_email,
                        mobile=new_mobile, landline=new_landline, sigle=new_sigle,
                        function_id=new_func, occupation_percentage=new_occupation,
                    ), initial_exception=initial_exception,
                )
                st.toast(t("settings.msg_emp_created", name=f"{new_first} {new_last}", default=f"Employee '{new_first} {new_last}' added (ID: {new_eid})!"))
                st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except OrganizationStorageError as e:
            st.error(str(e))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


def _render_employee_calendar_exception_editor(service: OrganizationService, employee_id: int,
                                                normal_occupation_percentage: float) -> list[EmployeeCalendarException]:
    """Render the employee's editable calendar grid."""
    from app.presentation.components.employee_editors import employee_exception_editor
    return employee_exception_editor(service, employee_id, normal_occupation_percentage)


@dialog(t("settings.dialog_edit_emp", default="Edit Employee Profile"), width="large", on_dismiss="rerun")
@organization_errors
def _open_edit_employee_dialog(
    service: OrganizationService,
    emp_id: int,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to edit an existing employee profile."""
    emp_obj = service.get_employee_by_id(emp_id)
    if not emp_obj:
        st.error("Employee not found.")
        return


    edit_sigle = st.text_input(t("settings.field_sigle", default="Sigle / Trigram"), value=emp_obj.sigle)

    c_n1, c_n2 = st.columns(2)
    edit_first = c_n1.text_input(t("settings.field_firstname", default="First Name *"), value=emp_obj.firstname)
    edit_last = c_n2.text_input(t("settings.field_lastname", default="Last Name *"), value=emp_obj.lastname)

    c_m1, c_m2 = st.columns(2)
    edit_email = c_m1.text_input(t("settings.field_email", default="Email *"), value=emp_obj.email)
    edit_mobile = c_m2.text_input(t("settings.field_mobile", default="Mobile / Phone"), value=emp_obj.mobile)
    edit_landline = st.text_input(t("settings.field_landline", default="Landline"), value=emp_obj.landline)

    c_occupation = st.container()
    edit_occupation = c_occupation.number_input(
        "Employee Overall occupation",
        min_value=0.0,
        max_value=100.0,
        value=float(emp_obj.occupation_percentage),
        step=5.0, format="%.0f",
        help='Full time employee has an occupation of 100%, half time employee has an occupation of 50%.',
    )

    from app.presentation.components.employee_editors import employee_function_editor
    assignments = employee_function_editor(emp_obj, df_funcs)

    exceptions = _render_employee_calendar_exception_editor(
        service,
        emp_id,
        edit_occupation,
    )

    col_cancel, col_save = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="Save Changes"), type="primary", width="stretch"):
        try:
            validate_employee(
                edit_first, edit_last, edit_email, edit_occupation
            )
            if service.check_email_exists(edit_email, exclude_id=emp_id):
                st.error(t("settings.err_email_taken", email=edit_email, default=f"Email '{edit_email}' is already registered."))
            else:
                require_change(service.update_employee(
                    Employee(
                        employee_id=emp_id,
                        firstname=edit_first,
                        lastname=edit_last,
                        email=edit_email,
                        mobile=edit_mobile,
                        landline=edit_landline,
                        sigle=edit_sigle,
                        function_assignments=assignments,
                        occupation_percentage=edit_occupation,
                    ), exceptions=exceptions
                ))
                st.toast(t("settings.msg_emp_updated", default="Employee profile updated successfully!"))
                st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except OrganizationStorageError as e:
            st.error(str(e))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.delete_confirm_title", default="Confirm Deletion"))
@organization_errors
def _open_delete_employee_dialog(
    service: OrganizationService,
    emp_id: int,
    emp_name: str,
) -> None:
    """Modal dialog to confirm deletion of an employee profile."""
    st.warning(f"{t('settings.delete_confirm_msg', name=emp_name, default=f'Are you sure you want to delete Employee profile **{emp_name}** (ID: {emp_id})?')}")
    st.caption("The record will be marked as deleted. Its history and mappings will be retained.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="Yes, Delete"), type="primary", width="stretch"):
        require_change(service.delete_employee(emp_id))
        st.toast(t("settings.msg_emp_deleted", default=f"Employee '{emp_name}' deleted."))
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


