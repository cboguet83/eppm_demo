"""Screen 5: Organization Structure & Settings Management View with Contextual Menus and Dialogs."""

import os
from typing import Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.i18n import t
from src.models.organization import Employee, FunctionType, OrgFunction, Team
from src.models.tag import ProjectTag, TagDictionary, TagGroup, TaskTag
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.tag_repo import TagRepository
from src.services.organization_service import OrganizationService
from src.services.tag_service import TagService

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
_interactive_tag_group_table = components.declare_component(
    "interactive_tag_group_table",
    path=os.path.join(_COMPONENTS_DIR, "tag_group_table"),
)
_interactive_tag_dictionary_table = components.declare_component(
    "interactive_tag_dictionary_table",
    path=os.path.join(_COMPONENTS_DIR, "tag_dictionary_table"),
)
_interactive_project_tag_table = components.declare_component(
    "interactive_project_tag_table",
    path=os.path.join(_COMPONENTS_DIR, "project_tag_table"),
)
_interactive_task_tag_table = components.declare_component(
    "interactive_task_tag_table",
    path=os.path.join(_COMPONENTS_DIR, "task_tag_table"),
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
# 5. TAG GROUP DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_tag_group", default="➕ Create Tag Group"))
def _open_add_tag_group_dialog(tag_repo: TagRepository) -> None:
    """Modal dialog to create a new tag group."""
    new_name = st.text_input(t("settings.field_group_name", default="Tag Group Name *"), placeholder="e.g. Architecture")

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Group"), type="primary", use_container_width=True):
        try:
            TagService.validate_tag_group(new_name)
            new_id = tag_repo.create_tag_group(TagGroup(tag_group_name=new_name.strip()))
            st.toast(f"Tag Group '{new_name}' created (ID: {new_id})!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_tag_group", default="✏️ Edit Tag Group"))
def _open_edit_tag_group_dialog(tag_repo: TagRepository, group_id: int, current_name: str) -> None:
    """Modal dialog to edit a tag group."""
    st.caption(f"ID: #{group_id}")
    edit_name = st.text_input(t("settings.field_group_name", default="Tag Group Name *"), value=current_name)

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            TagService.validate_tag_group(edit_name)
            tag_repo.update_tag_group(TagGroup(id=group_id, tag_group_name=edit_name.strip()))
            st.toast("Tag Group updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_tag_group_dialog(tag_repo: TagRepository, group_id: int, group_name: str) -> None:
    """Modal dialog to confirm deletion of a tag group."""
    usage_count = tag_repo.count_tags_by_group(group_id)
    if usage_count > 0:
        st.error(f"⚠️ Cannot delete Tag Group **{group_name}** (ID: {group_id}) because {usage_count} dictionary tags belong to it.")
        if st.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
            st.rerun()
        return

    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=group_name, default=f'Are you sure you want to delete Tag Group **{group_name}** (ID: {group_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        try:
            tag_repo.delete_tag_group(group_id)
            st.toast(f"Tag Group '{group_name}' deleted.", icon="🗑️")
            st.rerun()
        except Exception as e:
            st.error(f"Error deleting tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 6. TAG DICTIONARY DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_tag", default="➕ Create Tag"))
def _open_add_tag_dialog(tag_repo: TagRepository, df_groups: pd.DataFrame) -> None:
    """Modal dialog to create a new tag in the dictionary."""
    new_tag = st.text_input(t("settings.field_tag_name", default="Tag Label *"), placeholder="e.g. Cloud Native")

    group_opts = [None] + (df_groups["id"].tolist() if not df_groups.empty else [])
    group_map = dict(zip(df_groups["id"], df_groups["tag_group_name"])) if not df_groups.empty else {}
    new_group = st.selectbox(
        t("settings.field_tag_group", default="Tag Group (Optional)"),
        options=group_opts,
        format_func=lambda x: f"📁 {group_map.get(x, '')}" if x is not None else "— None",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Tag"), type="primary", use_container_width=True):
        try:
            TagService.validate_tag(new_tag)
            new_id = tag_repo.create_tag(TagDictionary(tag=new_tag.strip(), tag_group_id=new_group))
            st.toast(f"Tag '{new_tag}' created (ID: {new_id})!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_tag", default="✏️ Edit Tag"))
def _open_edit_tag_dialog(
    tag_repo: TagRepository,
    tag_id: int,
    current_tag: str,
    current_group_id: Optional[int],
    df_groups: pd.DataFrame,
) -> None:
    """Modal dialog to edit a tag in the dictionary."""
    st.caption(f"ID: #{tag_id}")
    edit_tag = st.text_input(t("settings.field_tag_name", default="Tag Label *"), value=current_tag)

    group_opts = [None] + (df_groups["id"].tolist() if not df_groups.empty else [])
    group_map = dict(zip(df_groups["id"], df_groups["tag_group_name"])) if not df_groups.empty else {}
    idx = group_opts.index(current_group_id) if current_group_id in group_opts else 0

    edit_group = st.selectbox(
        t("settings.field_tag_group", default="Tag Group (Optional)"),
        options=group_opts,
        index=idx,
        format_func=lambda x: f"📁 {group_map.get(x, '')}" if x is not None else "— None",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            TagService.validate_tag(edit_tag)
            tag_repo.update_tag(TagDictionary(id=tag_id, tag=edit_tag.strip(), tag_group_id=edit_group))
            st.toast("Tag updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_tag_dialog(tag_repo: TagRepository, tag_id: int, tag_name: str) -> None:
    """Modal dialog to confirm deletion of a dictionary tag."""
    usages = tag_repo.count_tag_usages(tag_id)
    if usages > 0:
        st.warning(f"⚠️ Tag **{tag_name}** is currently assigned to {usages} project(s) or task(s). Deleting it will also remove those tag assignments.")
    else:
        st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=tag_name, default=f'Are you sure you want to delete Tag **{tag_name}** (ID: {tag_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        try:
            tag_repo.delete_tag(tag_id)
            st.toast(f"Tag '{tag_name}' deleted.", icon="🗑️")
            st.rerun()
        except Exception as e:
            st.error(f"Error deleting tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 7. PROJECT TAG DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_proj_tag", default="➕ Assign Project Tag"))
def _open_add_project_tag_dialog(
    tag_repo: TagRepository,
    df_projects: pd.DataFrame,
    df_tags: pd.DataFrame,
) -> None:
    """Modal dialog to assign a tag to a project."""
    if df_projects.empty:
        st.warning("No projects available.")
        return

    proj_opts = df_projects["id"].tolist()
    proj_map = dict(zip(df_projects["id"], df_projects["name"]))
    selected_proj = st.selectbox(
        t("settings.field_project", default="Project *"),
        options=proj_opts,
        format_func=lambda x: f"#{x} - {proj_map.get(x, '')}",
    )

    tag_opts = [None] + (df_tags["id"].tolist() if not df_tags.empty else [])
    tag_map = dict(zip(df_tags["id"], df_tags["tag"])) if not df_tags.empty else {}
    selected_tag = st.selectbox(
        t("settings.field_dict_tag", default="Dictionary Tag (Optional)"),
        options=tag_opts,
        format_func=lambda x: f"🏷️ {tag_map.get(x, '')}" if x is not None else "— None (Use Free Tag)",
    )

    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        placeholder="e.g. Q3-Urgent",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Assign Tag"), type="primary", use_container_width=True):
        try:
            TagService.validate_project_tag(selected_proj, selected_tag, free_tag_val)
            pt_id = tag_repo.create_project_tag(
                ProjectTag(project_id=selected_proj, tag_id=selected_tag, free_tag=free_tag_val)
            )
            st.toast(f"Project tag assignment #{pt_id} created!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating project tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_proj_tag", default="✏️ Edit Project Tag Assignment"))
def _open_edit_project_tag_dialog(
    tag_repo: TagRepository,
    pt_id: int,
    current_project_id: int,
    current_tag_id: Optional[int],
    current_free_tag: Optional[str],
    df_projects: pd.DataFrame,
    df_tags: pd.DataFrame,
) -> None:
    """Modal dialog to edit a project tag assignment."""
    st.caption(f"Assignment ID: #{pt_id}")
    proj_opts = df_projects["id"].tolist() if not df_projects.empty else [current_project_id]
    proj_map = dict(zip(df_projects["id"], df_projects["name"])) if not df_projects.empty else {}
    p_idx = proj_opts.index(current_project_id) if current_project_id in proj_opts else 0

    selected_proj = st.selectbox(
        t("settings.field_project", default="Project *"),
        options=proj_opts,
        index=p_idx,
        format_func=lambda x: f"#{x} - {proj_map.get(x, '')}",
    )

    tag_opts = [None] + (df_tags["id"].tolist() if not df_tags.empty else [])
    tag_map = dict(zip(df_tags["id"], df_tags["tag"])) if not df_tags.empty else {}
    t_idx = tag_opts.index(current_tag_id) if current_tag_id in tag_opts else 0

    selected_tag = st.selectbox(
        t("settings.field_dict_tag", default="Dictionary Tag (Optional)"),
        options=tag_opts,
        index=t_idx,
        format_func=lambda x: f"🏷️ {tag_map.get(x, '')}" if x is not None else "— None (Use Free Tag)",
    )

    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        value=current_free_tag or "",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            TagService.validate_project_tag(selected_proj, selected_tag, free_tag_val)
            tag_repo.update_project_tag(
                ProjectTag(id=pt_id, project_id=selected_proj, tag_id=selected_tag, free_tag=free_tag_val)
            )
            st.toast("Project tag updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating project tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_project_tag_dialog(tag_repo: TagRepository, pt_id: int, tag_label: str) -> None:
    """Modal dialog to confirm deletion of a project tag assignment."""
    st.warning(f"⚠️ Are you sure you want to remove project tag assignment **{tag_label}** (ID: #{pt_id})?")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        tag_repo.delete_project_tag(pt_id)
        st.toast(f"Project tag #{pt_id} deleted.", icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 8. TASK TAG DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_task_tag", default="➕ Assign Task Tag"))
def _open_add_task_tag_dialog(
    tag_repo: TagRepository,
    df_tasks: pd.DataFrame,
    df_tags: pd.DataFrame,
) -> None:
    """Modal dialog to assign a tag to a task."""
    if df_tasks.empty:
        st.warning("No tasks available.")
        return

    task_opts = df_tasks["id"].tolist()
    task_map = dict(zip(df_tasks["id"], df_tasks["task_name"]))
    selected_task = st.selectbox(
        t("settings.field_task", default="Task *"),
        options=task_opts,
        format_func=lambda x: f"#{x} - {task_map.get(x, '')}",
    )

    tag_opts = [None] + (df_tags["id"].tolist() if not df_tags.empty else [])
    tag_map = dict(zip(df_tags["id"], df_tags["tag"])) if not df_tags.empty else {}
    selected_tag = st.selectbox(
        t("settings.field_dict_tag", default="Dictionary Tag (Optional)"),
        options=tag_opts,
        format_func=lambda x: f"🏷️ {tag_map.get(x, '')}" if x is not None else "— None (Use Free Tag)",
    )

    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        placeholder="e.g. Needs-Refinement",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Assign Tag"), type="primary", use_container_width=True):
        try:
            TagService.validate_task_tag(selected_task, selected_tag, free_tag_val)
            tt_id = tag_repo.create_task_tag(
                TaskTag(task_id=selected_task, tag_id=selected_tag, free_tag=free_tag_val)
            )
            st.toast(f"Task tag assignment #{tt_id} created!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating task tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_task_tag", default="✏️ Edit Task Tag Assignment"))
def _open_edit_task_tag_dialog(
    tag_repo: TagRepository,
    tt_id: int,
    current_task_id: int,
    current_tag_id: Optional[int],
    current_free_tag: Optional[str],
    df_tasks: pd.DataFrame,
    df_tags: pd.DataFrame,
) -> None:
    """Modal dialog to edit a task tag assignment."""
    st.caption(f"Assignment ID: #{tt_id}")
    task_opts = df_tasks["id"].tolist() if not df_tasks.empty else [current_task_id]
    task_map = dict(zip(df_tasks["id"], df_tasks["task_name"])) if not df_tasks.empty else {}
    t_idx = task_opts.index(current_task_id) if current_task_id in task_opts else 0

    selected_task = st.selectbox(
        t("settings.field_task", default="Task *"),
        options=task_opts,
        index=t_idx,
        format_func=lambda x: f"#{x} - {task_map.get(x, '')}",
    )

    tag_opts = [None] + (df_tags["id"].tolist() if not df_tags.empty else [])
    tag_map = dict(zip(df_tags["id"], df_tags["tag"])) if not df_tags.empty else {}
    tg_idx = tag_opts.index(current_tag_id) if current_tag_id in tag_opts else 0

    selected_tag = st.selectbox(
        t("settings.field_dict_tag", default="Dictionary Tag (Optional)"),
        options=tag_opts,
        index=tg_idx,
        format_func=lambda x: f"🏷️ {tag_map.get(x, '')}" if x is not None else "— None (Use Free Tag)",
    )

    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        value=current_free_tag or "",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            TagService.validate_task_tag(selected_task, selected_tag, free_tag_val)
            tag_repo.update_task_tag(
                TaskTag(id=tt_id, task_id=selected_task, tag_id=selected_tag, free_tag=free_tag_val)
            )
            st.toast("Task tag updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating task tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_task_tag_dialog(tag_repo: TagRepository, tt_id: int, tag_label: str) -> None:
    """Modal dialog to confirm deletion of a task tag assignment."""
    st.warning(f"⚠️ Are you sure you want to remove task tag assignment **{tag_label}** (ID: #{tt_id})?")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        tag_repo.delete_task_tag(tt_id)
        st.toast(f"Task tag #{tt_id} deleted.", icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# MAIN SETTINGS VIEW ENTRYPOINT
# =============================================================================
def render_settings_view(
    org_repo: OrganizationRepository,
    tag_repo: Optional[TagRepository] = None,
    project_repo: Optional[ProjectRepository] = None,
    milestone_repo: Optional[MilestoneRepository] = None,
) -> None:
    """Renders the Organization & Settings screen with tabbed contextual management."""
    st.header(f"⚙️ {t('settings.title', default='Organization Structure & Settings')}")

    tag_repo = tag_repo or TagRepository(org_repo.db_path)
    project_repo = project_repo or ProjectRepository(org_repo.db_path)
    milestone_repo = milestone_repo or MilestoneRepository(org_repo.db_path)

    (
        tab_funcs,
        tab_types,
        tab_teams,
        tab_emps,
        tab_tag_groups,
        tab_tag_dict,
        tab_proj_tags,
        tab_task_tags,
    ) = st.tabs([
        f"💼 {t('settings.tab_functions', default='Functions')}",
        f"🏷️ {t('settings.tab_types', default='Function Types')}",
        f"🛡️ {t('settings.tab_teams', default='Teams')}",
        f"👥 {t('settings.tab_employees', default='Employees')}",
        f"📁 {t('settings.tab_tag_groups', default='Tag Groups')}",
        f"📚 {t('settings.tab_tag_dict', default='Tag Dictionary')}",
        f"📌 {t('settings.tab_proj_tags', default='Project Tags')}",
        f"📋 {t('settings.tab_task_tags', default='Task Tags')}",
    ])

    df_types = org_repo.get_all_function_types()
    df_funcs = org_repo.get_all_functions()
    df_teams = org_repo.get_all_teams()
    df_emps = org_repo.get_all_employees()

    df_groups = tag_repo.get_all_tag_groups()
    df_tags = tag_repo.get_all_tags()
    df_proj_tags = tag_repo.get_all_project_tags()
    df_task_tags = tag_repo.get_all_task_tags()
    df_projects = project_repo.get_all_projects()
    df_tasks = milestone_repo.get_all_milestones()

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

    # =========================================================================
    # TAB 5: TAG GROUPS
    # =========================================================================
    with tab_tag_groups:
        total_groups = len(df_groups)
        st.subheader(f"{t('settings.tag_groups_title', default='Tag Groups Taxonomy')} ({total_groups} {t('settings.stat_tag_groups', default='Tag Groups')})")

        groups_payload = []
        if not df_groups.empty:
            for row in df_groups.to_dict(orient="records"):
                gid = int(row["id"])
                count = tag_repo.count_tags_by_group(gid)
                groups_payload.append({
                    "id": gid,
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "tag_count": count,
                })

        group_table_event = _interactive_tag_group_table(
            tag_groups=groups_payload,
            translations={
                "col_group_name": t("settings.col_group_name", default="Tag Group Name"),
                "col_tag_count": t("settings.col_tag_count", default="Tags Count"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "stat_tag_groups": t("settings.stat_tag_groups", default="Tag Groups"),
            },
            key="tag_group_interactive_table",
            default=None,
        )

        if group_table_event and isinstance(group_table_event, dict):
            nonce = group_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_tag_group_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_tag_group_table_nonce"] = nonce
                action = group_table_event.get("action")
                if action == "add_tag_group":
                    _open_add_tag_group_dialog(tag_repo)
                elif action == "edit_tag_group":
                    gid = group_table_event.get("group_id")
                    gname = group_table_event.get("tag_group_name", "")
                    if gid is not None:
                        _open_edit_tag_group_dialog(tag_repo, int(gid), str(gname))
                elif action == "delete_tag_group":
                    gid = group_table_event.get("group_id")
                    gname = group_table_event.get("tag_group_name", f"ID {gid}")
                    if gid is not None:
                        _open_delete_tag_group_dialog(tag_repo, int(gid), str(gname))

    # =========================================================================
    # TAB 6: TAG DICTIONARY
    # =========================================================================
    with tab_tag_dict:
        total_tags = len(df_tags)
        st.subheader(f"{t('settings.tag_dict_title', default='Tag Dictionary Taxonomy')} ({total_tags} {t('settings.stat_tags', default='Tags')})")

        tags_payload = []
        if not df_tags.empty:
            for row in df_tags.to_dict(orient="records"):
                tid = int(row["id"])
                usages = tag_repo.count_tag_usages(tid)
                tags_payload.append({
                    "id": tid,
                    "tag": str(row.get("tag") or ""),
                    "tag_group_id": int(row["tag_group_id"]) if pd.notna(row.get("tag_group_id")) else None,
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "usage_count": usages,
                })

        tag_table_event = _interactive_tag_dictionary_table(
            tags=tags_payload,
            translations={
                "col_tag": t("settings.col_tag", default="Tag"),
                "col_group_name": t("settings.col_group_name", default="Tag Group Name"),
                "col_usages": t("settings.col_usages", default="Usages"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "stat_tags": t("settings.stat_tags", default="Tags"),
            },
            key="tag_dict_interactive_table",
            default=None,
        )

        if tag_table_event and isinstance(tag_table_event, dict):
            nonce = tag_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_tag_dict_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_tag_dict_table_nonce"] = nonce
                action = tag_table_event.get("action")
                if action == "add_tag":
                    _open_add_tag_dialog(tag_repo, df_groups)
                elif action == "edit_tag":
                    tid = tag_table_event.get("tag_id")
                    tname = tag_table_event.get("tag", "")
                    tg_id = tag_table_event.get("tag_group_id")
                    if tid is not None:
                        _open_edit_tag_dialog(
                            tag_repo,
                            int(tid),
                            str(tname),
                            int(tg_id) if tg_id is not None else None,
                            df_groups,
                        )
                elif action == "delete_tag":
                    tid = tag_table_event.get("tag_id")
                    tname = tag_table_event.get("tag", f"ID {tid}")
                    if tid is not None:
                        _open_delete_tag_dialog(tag_repo, int(tid), str(tname))

    # =========================================================================
    # TAB 7: PROJECT TAGS
    # =========================================================================
    with tab_proj_tags:
        total_proj_tags = len(df_proj_tags)
        st.subheader(f"{t('settings.proj_tags_title', default='Project Tag Assignments')} ({total_proj_tags} {t('settings.stat_project_tags', default='Project Tags')})")

        proj_tags_payload = []
        if not df_proj_tags.empty:
            for row in df_proj_tags.to_dict(orient="records"):
                proj_tags_payload.append({
                    "id": int(row["id"]),
                    "project_id": int(row["project_id"]),
                    "project_name": str(row.get("project_name") or f"Project #{row['project_id']}"),
                    "tag_id": int(row["tag_id"]) if pd.notna(row.get("tag_id")) else None,
                    "tag_name": str(row.get("tag_name") or ""),
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "free_tag": str(row.get("free_tag") or ""),
                })

        proj_tag_table_event = _interactive_project_tag_table(
            project_tags=proj_tags_payload,
            translations={
                "col_project": t("settings.col_project", default="Project"),
                "col_tag": t("settings.col_tag", default="Dictionary Tag"),
                "col_group_name": t("settings.col_group_name", default="Tag Group"),
                "col_free_tag": t("settings.col_free_tag", default="Free Tag"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "stat_project_tags": t("settings.stat_project_tags", default="Project Tags"),
            },
            key="proj_tag_interactive_table",
            default=None,
        )

        if proj_tag_table_event and isinstance(proj_tag_table_event, dict):
            nonce = proj_tag_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_proj_tag_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_proj_tag_table_nonce"] = nonce
                action = proj_tag_table_event.get("action")
                if action == "add_project_tag":
                    _open_add_project_tag_dialog(tag_repo, df_projects, df_tags)
                elif action == "edit_project_tag":
                    pt_id = proj_tag_table_event.get("pt_id")
                    p_id = proj_tag_table_event.get("project_id")
                    t_id = proj_tag_table_event.get("tag_id")
                    f_tag = proj_tag_table_event.get("free_tag")
                    if pt_id is not None and p_id is not None:
                        _open_edit_project_tag_dialog(
                            tag_repo,
                            int(pt_id),
                            int(p_id),
                            int(t_id) if t_id is not None else None,
                            str(f_tag) if f_tag else None,
                            df_projects,
                            df_tags,
                        )
                elif action == "delete_project_tag":
                    pt_id = proj_tag_table_event.get("pt_id")
                    t_label = proj_tag_table_event.get("tag_label", f"ID {pt_id}")
                    if pt_id is not None:
                        _open_delete_project_tag_dialog(tag_repo, int(pt_id), str(t_label))

    # =========================================================================
    # TAB 8: TASK TAGS
    # =========================================================================
    with tab_task_tags:
        total_task_tags = len(df_task_tags)
        st.subheader(f"{t('settings.task_tags_title', default='Task Tag Assignments')} ({total_task_tags} {t('settings.stat_task_tags', default='Task Tags')})")

        task_tags_payload = []
        if not df_task_tags.empty:
            for row in df_task_tags.to_dict(orient="records"):
                task_tags_payload.append({
                    "id": int(row["id"]),
                    "task_id": int(row["task_id"]),
                    "task_name": str(row.get("task_name") or f"Task #{row['task_id']}"),
                    "project_name": str(row.get("project_name") or ""),
                    "tag_id": int(row["tag_id"]) if pd.notna(row.get("tag_id")) else None,
                    "tag_name": str(row.get("tag_name") or ""),
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "free_tag": str(row.get("free_tag") or ""),
                })

        task_tag_table_event = _interactive_task_tag_table(
            task_tags=task_tags_payload,
            translations={
                "col_task": t("settings.col_task", default="Task"),
                "col_project": t("settings.col_project", default="Project"),
                "col_tag": t("settings.col_tag", default="Dictionary Tag"),
                "col_group_name": t("settings.col_group_name", default="Tag Group"),
                "col_free_tag": t("settings.col_free_tag", default="Free Tag"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "stat_task_tags": t("settings.stat_task_tags", default="Task Tags"),
            },
            key="task_tag_interactive_table",
            default=None,
        )

        if task_tag_table_event and isinstance(task_tag_table_event, dict):
            nonce = task_tag_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_task_tag_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_task_tag_table_nonce"] = nonce
                action = task_tag_table_event.get("action")
                if action == "add_task_tag":
                    _open_add_task_tag_dialog(tag_repo, df_tasks, df_tags)
                elif action == "edit_task_tag":
                    tt_id = task_tag_table_event.get("tt_id")
                    t_id = task_tag_table_event.get("task_id")
                    tag_id = task_tag_table_event.get("tag_id")
                    f_tag = task_tag_table_event.get("free_tag")
                    if tt_id is not None and t_id is not None:
                        _open_edit_task_tag_dialog(
                            tag_repo,
                            int(tt_id),
                            int(t_id),
                            int(tag_id) if tag_id is not None else None,
                            str(f_tag) if f_tag else None,
                            df_tasks,
                            df_tags,
                        )
                elif action == "delete_task_tag":
                    tt_id = task_tag_table_event.get("tt_id")
                    t_label = task_tag_table_event.get("tag_label", f"ID {tt_id}")
                    if tt_id is not None:
                        _open_delete_task_tag_dialog(tag_repo, int(tt_id), str(t_label))

