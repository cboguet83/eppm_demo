"""Screen 5: Organization Structure & Settings Management View with Contextual Menus and Dialogs."""

import os
from typing import Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.i18n import t
from src.models.organization import Employee, FunctionType, OrgFunction, Team
from src.repositories.organization_repo import OrganizationRepository
from src.services.organization_service import OrganizationService

# Declare Interactive Table Custom Components
_COMPONENTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "components",
)
_interactive_function_table = components.declare_component(
    "interactive_function_table",
    path=os.path.join(_COMPONENTS_DIR, "function_table"),
)
_interactive_function_type_table = components.declare_component(
    "interactive_function_type_table",
    path=os.path.join(_COMPONENTS_DIR, "function_type_table"),
)
_interactive_team_table = components.declare_component(
    "interactive_team_table",
    path=os.path.join(_COMPONENTS_DIR, "team_table"),
)
_interactive_employee_table = components.declare_component(
    "interactive_employee_table",
    path=os.path.join(_COMPONENTS_DIR, "employee_table"),
)


# =============================================================================
# 1. FUNCTION DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_func", default="➕ Create Job Function"))
def _open_add_function_dialog(
    org_repo: OrganizationRepository,
    df_funcs: pd.DataFrame,
    df_types: pd.DataFrame,
) -> None:
    """Modal dialog to create a new job function."""
    new_name = st.text_input(t("settings.field_func_name", default="Function Title *"), placeholder="e.g. Solution Architect")
    new_level = st.number_input(
        t("settings.field_func_level", default="Hierarchy Level (Integer) *"),
        min_value=1,
        value=1,
        step=1,
    )

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
    new_has_reports = st.checkbox(
        t("settings.field_has_reports", default="Has Reports / Subordinates"),
        value=False,
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Function"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_function(new_name, int(new_level), int(new_fte))
            new_fid = org_repo.create_function(
                OrgFunction(
                    name=new_name,
                    hierarchy_level=int(new_level),
                    function_type_id=new_type,
                    manager_function_id=new_mgr,
                    dual_manager_function_id=new_dual,
                    fte_percentage=int(new_fte),
                    has_reports=new_has_reports,
                )
            )
            st.toast(t("settings.msg_func_created", name=new_name, default=f"Function '{new_name}' created (ID: {new_fid})!"), icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating function: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_func", default="✏️ Edit Job Function"))
def _open_edit_function_dialog(
    org_repo: OrganizationRepository,
    func_id: int,
    df_funcs: pd.DataFrame,
    df_types: pd.DataFrame,
) -> None:
    """Modal dialog to edit an existing job function."""
    fn_obj = org_repo.get_function_by_id(func_id)
    if not fn_obj:
        st.error("Function not found.")
        return

    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    type_map = dict(zip(df_types["function_type_id"], df_types["function_type"])) if not df_types.empty else {}

    edit_name = st.text_input(t("settings.field_func_name", default="Function Title *"), value=fn_obj.name)
    edit_level = st.number_input(
        t("settings.field_func_level", default="Hierarchy Level (Integer) *"),
        min_value=1,
        value=fn_obj.hierarchy_level,
        step=1,
    )

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
    edit_has_reports = st.checkbox(
        t("settings.field_has_reports", default="Has Reports / Subordinates"),
        value=fn_obj.has_reports,
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_function(edit_name, int(edit_level), int(edit_fte))
            org_repo.update_function(
                OrgFunction(
                    function_id=func_id,
                    name=edit_name,
                    hierarchy_level=int(edit_level),
                    function_type_id=edit_type,
                    manager_function_id=edit_mgr,
                    dual_manager_function_id=edit_dual,
                    fte_percentage=int(edit_fte),
                    has_reports=edit_has_reports,
                )
            )
            st.toast(t("settings.msg_func_updated", default="Function updated successfully!"), icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating function: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_function_dialog(
    org_repo: OrganizationRepository,
    func_id: int,
    func_name: str,
) -> None:
    """Modal dialog to confirm deletion of a job function."""
    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=func_name, default=f'Are you sure you want to delete Function **{func_name}** (ID: {func_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        org_repo.delete_function(func_id)
        st.toast(t("settings.msg_func_deleted", default=f"Function '{func_name}' deleted."), icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 3. TEAM DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_team", default="➕ Create Team"))
def _open_add_team_dialog(
    org_repo: OrganizationRepository,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to create a new team."""
    new_name = st.text_input(t("settings.field_team_name", default="Team Name *"), placeholder="e.g. Equipe BIM")

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}

    new_mgr = st.selectbox(
        t("settings.field_team_mgr", default="Manager Function (Optional)"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )
    new_leader = st.selectbox(
        t("settings.field_team_leader", default="Team Leader Function (Optional)"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Team"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_team(new_name)
            new_tid = org_repo.create_team(
                Team(
                    team_name=new_name,
                    manager_function_id=new_mgr,
                    leader_function_id=new_leader,
                )
            )
            st.toast(t("settings.msg_team_created", name=new_name, default=f"Team '{new_name}' created (ID: {new_tid})!"), icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating team: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_team", default="✏️ Edit Team"))
def _open_edit_team_dialog(
    org_repo: OrganizationRepository,
    team_id: int,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to edit an existing team."""
    team_obj = org_repo.get_team_by_id(team_id)
    if not team_obj:
        st.error("Team not found.")
        return

    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    edit_name = st.text_input(t("settings.field_team_name", default="Team Name *"), value=team_obj.team_name)

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    mgr_idx = func_opts.index(team_obj.manager_function_id) if team_obj.manager_function_id in func_opts else 0
    edit_mgr = st.selectbox(
        t("settings.field_team_mgr", default="Manager Function"),
        options=func_opts,
        index=mgr_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    ldr_idx = func_opts.index(team_obj.leader_function_id) if team_obj.leader_function_id in func_opts else 0
    edit_leader = st.selectbox(
        t("settings.field_team_leader", default="Team Leader Function"),
        options=func_opts,
        index=ldr_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_team(edit_name)
            org_repo.update_team(
                Team(
                    team_id=team_id,
                    team_name=edit_name,
                    manager_function_id=edit_mgr,
                    leader_function_id=edit_leader,
                )
            )
            st.toast(t("settings.msg_team_updated", default="Team updated successfully!"), icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating team: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_team_dialog(
    org_repo: OrganizationRepository,
    team_id: int,
    team_name: str,
) -> None:
    """Modal dialog to confirm deletion of a team."""
    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=team_name, default=f'Are you sure you want to delete Team **{team_name}** (ID: {team_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        org_repo.delete_team(team_id)
        st.toast(t("settings.msg_team_deleted", default=f"Team '{team_name}' deleted."), icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()



# =============================================================================
# 3. FUNCTION TYPE DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_type", default="➕ Create Function Type"))
def _open_add_function_type_dialog(org_repo: OrganizationRepository) -> None:
    """Modal dialog to create a new function type."""
    new_name = st.text_input(t("settings.field_type_name", default="Function Type *"), placeholder="e.g. Contractor")

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Type"), type="primary", use_container_width=True):
        clean_name = new_name.strip()
        if clean_name:
            try:
                new_tid = org_repo.create_function_type(FunctionType(function_type=clean_name))
                st.toast(t("settings.msg_type_created", name=clean_name, default=f"Function Type '{clean_name}' created (ID: {new_tid})!"), icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"Error creating type: {e}")
        else:
            st.error(t("settings.err_type_name_empty", default="Function type name cannot be empty."))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_type", default="✏️ Edit Function Type"))
def _open_edit_function_type_dialog(
    org_repo: OrganizationRepository,
    type_id: int,
    current_name: str,
) -> None:
    """Modal dialog to edit an existing function type."""
    edit_name = st.text_input(t("settings.field_type_name", default="Function Type *"), value=current_name)

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        clean_name = edit_name.strip()
        if clean_name:
            try:
                org_repo.update_function_type(FunctionType(function_type_id=type_id, function_type=clean_name))
                st.toast(t("settings.msg_type_updated", default="Function Type updated successfully!"), icon="✏️")
                st.rerun()
            except Exception as e:
                st.error(f"Error updating type: {e}")
        else:
            st.error(t("settings.err_type_name_empty", default="Function type name cannot be empty."))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_function_type_dialog(
    org_repo: OrganizationRepository,
    type_id: int,
    type_name: str,
) -> None:
    """Modal dialog to confirm deletion of a function type."""
    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=type_name, default=f'Are you sure you want to delete Function Type **{type_name}** (ID: {type_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        org_repo.delete_function_type(type_id)
        st.toast(t("settings.msg_type_deleted", default=f"Function Type '{type_name}' deleted."), icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 4. EMPLOYEE DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_emp", default="➕ Add New Employee"))
def _open_add_employee_dialog(
    org_repo: OrganizationRepository,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to create a new employee profile."""
    auto_code = org_repo.generate_next_employee_code()
    c_c1, c_c2 = st.columns(2)
    new_code = c_c1.text_input(t("settings.field_emp_code", default="Employee Code *"), value=auto_code)
    new_sigle = c_c2.text_input(t("settings.field_sigle", default="Sigle / Trigram"), placeholder="e.g. SCO")

    c_n1, c_n2 = st.columns(2)
    new_first = c_n1.text_input(t("settings.field_firstname", default="First Name *"), placeholder="Sarah")
    new_last = c_n2.text_input(t("settings.field_lastname", default="Last Name *"), placeholder="Connor")

    c_m1, c_m2 = st.columns(2)
    new_email = c_m1.text_input(t("settings.field_email", default="Email *"), placeholder="sconnor@enterprise.com")
    new_mobile = c_m2.text_input(t("settings.field_mobile", default="Mobile / Phone"), placeholder="+1-555-0101")

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    new_func = st.selectbox(
        t("settings.field_function", default="Function Role"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Employee"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_employee(new_first, new_last, new_email, new_code)
            if org_repo.check_email_exists(new_email):
                st.error(t("settings.err_email_taken", email=new_email, default=f"Email '{new_email}' is already registered."))
            elif org_repo.check_code_exists(new_code):
                st.error(t("settings.err_code_taken", code=new_code, default=f"Employee code '{new_code}' is already taken."))
            else:
                new_eid = org_repo.create_employee(
                    Employee(
                        firstname=new_first,
                        lastname=new_last,
                        email=new_email,
                        mobile=new_mobile,
                        sigle=new_sigle,
                        employee_code=new_code,
                        function_id=new_func,
                    )
                )
                st.toast(t("settings.msg_emp_created", name=f"{new_first} {new_last}", default=f"Employee '{new_first} {new_last}' added (ID: {new_eid})!"), icon="✅")
                st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error adding employee: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_emp", default="✏️ Edit Employee Profile"))
def _open_edit_employee_dialog(
    org_repo: OrganizationRepository,
    emp_id: int,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to edit an existing employee profile."""
    emp_obj = org_repo.get_employee_by_id(emp_id)
    if not emp_obj:
        st.error("Employee not found.")
        return

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}

    c_c1, c_c2 = st.columns(2)
    edit_code = c_c1.text_input(t("settings.field_emp_code", default="Employee Code *"), value=emp_obj.employee_code)
    edit_sigle = c_c2.text_input(t("settings.field_sigle", default="Sigle / Trigram"), value=emp_obj.sigle)

    c_n1, c_n2 = st.columns(2)
    edit_first = c_n1.text_input(t("settings.field_firstname", default="First Name *"), value=emp_obj.firstname)
    edit_last = c_n2.text_input(t("settings.field_lastname", default="Last Name *"), value=emp_obj.lastname)

    c_m1, c_m2 = st.columns(2)
    edit_email = c_m1.text_input(t("settings.field_email", default="Email *"), value=emp_obj.email)
    edit_mobile = c_m2.text_input(t("settings.field_mobile", default="Mobile / Phone"), value=emp_obj.mobile)

    emp_f_idx = func_opts.index(emp_obj.function_id) if emp_obj.function_id in func_opts else 0
    edit_func = st.selectbox(
        t("settings.field_function", default="Function Role"),
        options=func_opts,
        index=emp_f_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_employee(edit_first, edit_last, edit_email, edit_code)
            if org_repo.check_email_exists(edit_email, exclude_id=emp_id):
                st.error(t("settings.err_email_taken", email=edit_email, default=f"Email '{edit_email}' is already registered."))
            elif org_repo.check_code_exists(edit_code, exclude_id=emp_id):
                st.error(t("settings.err_code_taken", code=edit_code, default=f"Employee code '{edit_code}' is already taken."))
            else:
                org_repo.update_employee(
                    Employee(
                        employee_id=emp_id,
                        firstname=edit_first,
                        lastname=edit_last,
                        email=edit_email,
                        mobile=edit_mobile,
                        sigle=edit_sigle,
                        employee_code=edit_code,
                        function_id=edit_func,
                    )
                )
                st.toast(t("settings.msg_emp_updated", default="Employee profile updated successfully!"), icon="✏️")
                st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating employee: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_employee_dialog(
    org_repo: OrganizationRepository,
    emp_id: int,
    emp_name: str,
) -> None:
    """Modal dialog to confirm deletion of an employee profile."""
    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=emp_name, default=f'Are you sure you want to delete Employee profile **{emp_name}** (ID: {emp_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        org_repo.delete_employee(emp_id)
        st.toast(t("settings.msg_emp_deleted", default=f"Employee '{emp_name}' deleted."), icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# MAIN SETTINGS VIEW ENTRYPOINT
# =============================================================================
def render_settings_view(org_repo: OrganizationRepository) -> None:
    """Renders the Organization & Settings screen with tabbed contextual management."""
    st.header(f"⚙️ {t('settings.title', default='Organization Structure & Settings')}")

    tab_funcs, tab_types, tab_teams, tab_emps = st.tabs([
        f"💼 {t('settings.tab_functions', default='Functions')}",
        f"🏷️ {t('settings.tab_types', default='Function Types')}",
        f"🛡️ {t('settings.tab_teams', default='Teams')}",
        f"👥 {t('settings.tab_employees', default='Employees')}",
    ])

    df_types = org_repo.get_all_function_types()
    df_funcs = org_repo.get_all_functions()
    df_teams = org_repo.get_all_teams()
    df_emps = org_repo.get_all_employees()

    # =========================================================================
    # TAB 1: FUNCTIONS
    # =========================================================================
    with tab_funcs:
        total_funcs = len(df_funcs)
        total_fte = (df_funcs["fte_percentage"].sum() / 100.0) if not df_funcs.empty and "fte_percentage" in df_funcs.columns else 0.0

        st.subheader(f"{t('settings.functions_title', default='Job Functions Management')} ({total_funcs} {t('settings.stat_functions', default='Functions')} • {total_fte:.2f} {t('settings.stat_fte', default='FTE')})")

        # Interactive Overview Table with Column Filtering & Right-Click Context Menu
        enriched_funcs = OrganizationService.enrich_functions(df_funcs, df_types)
        functions_payload = []
        if not enriched_funcs.empty:
            for row in enriched_funcs.to_dict(orient="records"):
                functions_payload.append({
                    "function_id": int(row["function_id"]),
                    "name": str(row["name"]),
                    "hierarchy_level": int(row["hierarchy_level"]) if pd.notna(row.get("hierarchy_level")) else 1,
                    "has_reports": bool(row.get("has_reports", False)),
                    "function_type_id": int(row["function_type_id"]) if pd.notna(row.get("function_type_id")) else None,
                    "function_type_name": str(row["function_type_name"]) if pd.notna(row.get("function_type_name")) else "—",
                    "manager_function_id": int(row["manager_function_id"]) if pd.notna(row.get("manager_function_id")) else None,
                    "manager_function_name": str(row["manager_function_name"]) if pd.notna(row.get("manager_function_name")) else "—",
                    "dual_manager_function_id": int(row["dual_manager_function_id"]) if pd.notna(row.get("dual_manager_function_id")) else None,
                    "dual_manager_function_name": str(row["dual_manager_function_name"]) if pd.notna(row.get("dual_manager_function_name")) else "—",
                    "fte_percentage": int(row["fte_percentage"]) if pd.notna(row.get("fte_percentage")) else 100,
                })

        table_event = _interactive_function_table(
            functions=functions_payload,
            translations={
                "col_id": "ID",
                "col_func_name": t("settings.col_func_name", default="Function Title"),
                "col_level": t("settings.col_level", default="Hierarchy Level"),
                "col_has_reports": t("settings.col_has_reports", default="Has Reports"),
                "col_type": t("settings.col_type", default="Function Type"),
                "col_primary_mgr": t("settings.col_primary_mgr", default="Primary Manager"),
                "col_dual_mgr": t("settings.col_dual_mgr", default="Dual Manager"),
                "col_fte_pct": t("settings.col_fte_pct", default="FTE %"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "no_functions": t("settings.no_functions", default="No job functions registered."),
                "hint_right_click": t("settings.hint_right_click", default="💡 Right-click any row to Add, Edit, or Delete"),
                "badge_yes": t("settings.badge_yes", default="Yes"),
                "badge_no": t("settings.badge_no", default="No"),
                "stat_functions": t("settings.stat_functions", default="Functions"),
                "stat_fte": t("settings.stat_fte", default="FTE"),
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
            key="func_interactive_table",
            default=None,
        )

        # Handle context menu trigger events
        if table_event and isinstance(table_event, dict):
            nonce = table_event.get("nonce")
            last_nonce = st.session_state.get("_last_func_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_func_table_nonce"] = nonce
                action = table_event.get("action")
                if action == "add_function":
                    _open_add_function_dialog(org_repo, df_funcs, df_types)
                elif action == "edit_function":
                    fn_id = table_event.get("function_id")
                    if fn_id is not None:
                        _open_edit_function_dialog(org_repo, int(fn_id), df_funcs, df_types)
                elif action == "delete_function":
                    fn_id = table_event.get("function_id")
                    fn_name = table_event.get("function_name", f"ID {fn_id}")
                    if fn_id is not None:
                        _open_delete_function_dialog(org_repo, int(fn_id), str(fn_name))

    # =========================================================================
    # TAB 3: FUNCTION TYPES
    # =========================================================================
    with tab_types:
        total_types = len(df_types)
        st.subheader(f"{t('settings.types_title', default='Function Types Management')} ({total_types} {t('settings.stat_types', default='Types')})")

        types_payload = []
        if not df_types.empty:
            for row in df_types.to_dict(orient="records"):
                types_payload.append({
                    "function_type_id": int(row["function_type_id"]),
                    "function_type": str(row["function_type"]),
                })

        type_table_event = _interactive_function_type_table(
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
                    _open_add_function_type_dialog(org_repo)
                elif action == "edit_function_type":
                    ft_id = type_table_event.get("function_type_id")
                    ft_name = type_table_event.get("function_type_name", "")
                    if ft_id is not None:
                        _open_edit_function_type_dialog(org_repo, int(ft_id), str(ft_name))
                elif action == "delete_function_type":
                    ft_id = type_table_event.get("function_type_id")
                    ft_name = type_table_event.get("function_type_name", f"ID {ft_id}")
                    if ft_id is not None:
                        _open_delete_function_type_dialog(org_repo, int(ft_id), str(ft_name))

    # =========================================================================
    # TAB 4: TEAMS
    # =========================================================================
    with tab_teams:
        total_teams = len(df_teams)
        st.subheader(f"{t('settings.teams_title', default='Teams Management')} ({total_teams} {t('settings.stat_teams', default='Teams')})")

        enriched_teams = OrganizationService.enrich_teams(df_teams, df_funcs)
        teams_payload = []
        if not enriched_teams.empty:
            for row in enriched_teams.to_dict(orient="records"):
                teams_payload.append({
                    "team_id": int(row["team_id"]),
                    "team_name": str(row["team_name"]),
                    "manager_function_id": int(row["manager_function_id"]) if pd.notna(row.get("manager_function_id")) else None,
                    "manager_function_name": str(row["manager_function_name"]) if pd.notna(row.get("manager_function_name")) else "—",
                    "leader_function_id": int(row["leader_function_id"]) if pd.notna(row.get("leader_function_id")) else None,
                    "leader_function_name": str(row["leader_function_name"]) if pd.notna(row.get("leader_function_name")) else "—",
                })

        team_table_event = _interactive_team_table(
            teams=teams_payload,
            translations={
                "col_id": "ID",
                "col_team_name": t("settings.col_team_name", default="Team Name"),
                "col_team_mgr": t("settings.col_team_mgr", default="Manager Function"),
                "col_team_leader": t("settings.col_team_leader", default="Team Leader"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "no_teams": t("settings.no_teams", default="No teams registered."),
                "stat_teams": t("settings.stat_teams", default="Teams"),
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
            key="team_interactive_table",
            default=None,
        )

        if team_table_event and isinstance(team_table_event, dict):
            nonce = team_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_team_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_team_table_nonce"] = nonce
                action = team_table_event.get("action")
                if action == "add_team":
                    _open_add_team_dialog(org_repo, df_funcs)
                elif action == "edit_team":
                    tm_id = team_table_event.get("team_id")
                    if tm_id is not None:
                        _open_edit_team_dialog(org_repo, int(tm_id), df_funcs)
                elif action == "delete_team":
                    tm_id = team_table_event.get("team_id")
                    tm_name = team_table_event.get("team_name", f"ID {tm_id}")
                    if tm_id is not None:
                        _open_delete_team_dialog(org_repo, int(tm_id), str(tm_name))

    # =========================================================================
    # TAB 5: EMPLOYEES
    # =========================================================================
    with tab_emps:
        total_emps = len(df_emps)
        st.subheader(f"{t('settings.employees_title', default='Employee Directory & Profile Management')} ({total_emps} {t('settings.stat_employees', default='Employees')})")

        enriched_emps = OrganizationService.enrich_employees(df_emps, df_funcs, df_types)
        emps_payload = []
        if not enriched_emps.empty:
            for row in enriched_emps.to_dict(orient="records"):
                emps_payload.append({
                    "employee_id": int(row["employee_id"]),
                    "employee_code": str(row.get("employee_code") or ""),
                    "full_name": str(row.get("full_name") or ""),
                    "email": str(row.get("email") or ""),
                    "mobile": str(row.get("mobile") or ""),
                    "sigle": str(row.get("sigle") or ""),
                    "function_id": int(row["function_id"]) if pd.notna(row.get("function_id")) else None,
                    "function_name": str(row.get("function_name") or "—"),
                    "function_type_name": str(row.get("function_type_name") or "—"),
                })

        emp_table_event = _interactive_employee_table(
            employees=emps_payload,
            translations={
                "col_emp_code": t("settings.col_emp_code", default="Code"),
                "col_full_name": t("settings.col_full_name", default="Full Name"),
                "col_mobile": t("settings.col_mobile", default="Mobile"),
                "col_sigle": t("settings.col_sigle", default="Sigle"),
                "col_function": t("settings.col_function", default="Function"),
                "col_type": t("settings.col_type", default="Function Type"),
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
                    _open_add_employee_dialog(org_repo, df_funcs)
                elif action == "edit_employee":
                    e_id = emp_table_event.get("employee_id")
                    if e_id is not None:
                        _open_edit_employee_dialog(org_repo, int(e_id), df_funcs)
                elif action == "delete_employee":
                    e_id = emp_table_event.get("employee_id")
                    e_name = emp_table_event.get("full_name", f"ID {e_id}")
                    if e_id is not None:
                        _open_delete_employee_dialog(org_repo, int(e_id), str(e_name))
