"""Screen 5: Organization Structure & Settings Management View with Contextual Menus and Dialogs."""

from typing import Optional

import pandas as pd
import streamlit as st

from src.i18n import t
from src.models.organization import Employee, FunctionType, HierarchyLevel, OrgFunction
from src.repositories.organization_repo import OrganizationRepository
from src.services.organization_service import OrganizationService


# =============================================================================
# 1. HIERARCHY LEVEL DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_level", default="➕ Create Hierarchy Level"))
def _open_add_hierarchy_level_dialog(
    org_repo: OrganizationRepository,
    df_levels: pd.DataFrame,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to create a new hierarchy level."""
    new_name = st.text_input(t("settings.field_level_name", default="Level Name *"), placeholder="e.g. Director")
    new_rank = st.number_input(
        t("settings.field_level_tier", default="Tier Level (Integer) *"),
        min_value=1,
        value=len(df_levels) + 1,
        step=1,
    )

    parent_opts = [None] + (df_levels["hierarchy_level_id"].tolist() if not df_levels.empty else [])
    level_map = dict(zip(df_levels["hierarchy_level_id"], df_levels["name"])) if not df_levels.empty else {}
    new_parent = st.selectbox(
        t("settings.field_parent_level", default="Parent Hierarchy Level"),
        options=parent_opts,
        format_func=lambda x: f"Lvl {x} - {level_map.get(x, '')}" if x is not None else "— None (Top Level)",
    )

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    new_mgr_func = st.selectbox(
        t("settings.field_manager_func", default="Manager Function (Optional)"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Level"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_hierarchy_level(new_name, int(new_rank))
            new_id = org_repo.create_hierarchy_level(
                HierarchyLevel(
                    name=new_name,
                    level=int(new_rank),
                    parent_hierarchy_level_id=new_parent,
                    manager_function_id=new_mgr_func,
                )
            )
            st.toast(t("settings.msg_level_created", name=new_name, default=f"Level '{new_name}' created (ID: {new_id})!"), icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating level: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_level", default="✏️ Edit Hierarchy Level"))
def _open_edit_hierarchy_level_dialog(
    org_repo: OrganizationRepository,
    level_id: int,
    df_levels: pd.DataFrame,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to edit an existing hierarchy level."""
    hl_obj = org_repo.get_hierarchy_level_by_id(level_id)
    if not hl_obj:
        st.error("Hierarchy level not found.")
        return

    level_map = dict(zip(df_levels["hierarchy_level_id"], df_levels["name"])) if not df_levels.empty else {}
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}

    edit_name = st.text_input(t("settings.field_level_name", default="Level Name *"), value=hl_obj.name)
    edit_rank = st.number_input(t("settings.field_level_tier", default="Tier Level *"), min_value=1, value=hl_obj.level, step=1)

    edit_parent_opts = [None] + [pid for pid in df_levels["hierarchy_level_id"].tolist() if pid != level_id]
    edit_parent_idx = edit_parent_opts.index(hl_obj.parent_hierarchy_level_id) if hl_obj.parent_hierarchy_level_id in edit_parent_opts else 0
    edit_parent = st.selectbox(
        t("settings.field_parent_level", default="Parent Hierarchy Level"),
        options=edit_parent_opts,
        index=edit_parent_idx,
        format_func=lambda x: f"Lvl {x} - {level_map.get(x, '')}" if x is not None else "— None (Top Level)",
    )

    edit_func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    edit_func_idx = edit_func_opts.index(hl_obj.manager_function_id) if hl_obj.manager_function_id in edit_func_opts else 0
    edit_mgr_func = st.selectbox(
        t("settings.field_manager_func", default="Manager Function"),
        options=edit_func_opts,
        index=edit_func_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_hierarchy_level(edit_name, int(edit_rank))
            org_repo.update_hierarchy_level(
                HierarchyLevel(
                    hierarchy_level_id=level_id,
                    name=edit_name,
                    level=int(edit_rank),
                    parent_hierarchy_level_id=edit_parent,
                    manager_function_id=edit_mgr_func,
                )
            )
            st.toast(t("settings.msg_level_updated", default="Hierarchy Level updated successfully!"), icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating level: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_hierarchy_level_dialog(
    org_repo: OrganizationRepository,
    level_id: int,
    level_name: str,
) -> None:
    """Modal dialog to confirm deletion of a hierarchy level."""
    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=level_name, default=f'Are you sure you want to delete Hierarchy Level **{level_name}** (ID: {level_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        org_repo.delete_hierarchy_level(level_id)
        st.toast(t("settings.msg_level_deleted", default=f"Level '{level_name}' deleted."), icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 2. FUNCTION DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_func", default="➕ Create Job Function"))
def _open_add_function_dialog(
    org_repo: OrganizationRepository,
    df_levels: pd.DataFrame,
    df_funcs: pd.DataFrame,
    df_types: pd.DataFrame,
) -> None:
    """Modal dialog to create a new job function."""
    if df_levels.empty:
        st.warning(t("settings.warn_need_levels", default="Please create Hierarchy Levels before creating Functions."))
        if st.button(t("settings.btn_cancel", default="Close")):
            st.rerun()
        return

    new_name = st.text_input(t("settings.field_func_name", default="Function Title *"), placeholder="e.g. Solution Architect")
    level_opts = df_levels["hierarchy_level_id"].tolist()
    level_map = dict(zip(df_levels["hierarchy_level_id"], df_levels["name"]))
    new_level = st.selectbox(
        t("settings.field_func_level", default="Hierarchy Level *"),
        options=level_opts,
        format_func=lambda x: f"Lvl {x} - {level_map.get(x, '')}",
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

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Function"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_function(new_name, new_level)
            new_fid = org_repo.create_function(
                OrgFunction(
                    name=new_name,
                    hierarchy_level_id=new_level,
                    function_type_id=new_type,
                    manager_function_id=new_mgr,
                    dual_manager_function_id=new_dual,
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
    df_levels: pd.DataFrame,
    df_funcs: pd.DataFrame,
    df_types: pd.DataFrame,
) -> None:
    """Modal dialog to edit an existing job function."""
    fn_obj = org_repo.get_function_by_id(func_id)
    if not fn_obj:
        st.error("Function not found.")
        return

    level_map = dict(zip(df_levels["hierarchy_level_id"], df_levels["name"])) if not df_levels.empty else {}
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    type_map = dict(zip(df_types["function_type_id"], df_types["function_type"])) if not df_types.empty else {}

    edit_name = st.text_input(t("settings.field_func_name", default="Function Title *"), value=fn_obj.name)
    edit_level_opts = df_levels["hierarchy_level_id"].tolist() if not df_levels.empty else [fn_obj.hierarchy_level_id]
    edit_level_idx = edit_level_opts.index(fn_obj.hierarchy_level_id) if fn_obj.hierarchy_level_id in edit_level_opts else 0
    edit_level = st.selectbox(
        t("settings.field_func_level", default="Hierarchy Level *"),
        options=edit_level_opts,
        index=edit_level_idx,
        format_func=lambda x: f"Lvl {x} - {level_map.get(x, '')}",
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

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_function(edit_name, edit_level)
            org_repo.update_function(
                OrgFunction(
                    function_id=func_id,
                    name=edit_name,
                    hierarchy_level_id=edit_level,
                    function_type_id=edit_type,
                    manager_function_id=edit_mgr,
                    dual_manager_function_id=edit_dual,
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

    tab_levels, tab_funcs, tab_types, tab_emps = st.tabs([
        f"🏗️ {t('settings.tab_hierarchy', default='Hierarchy Levels')}",
        f"💼 {t('settings.tab_functions', default='Functions')}",
        f"🏷️ {t('settings.tab_types', default='Function Types')}",
        f"👥 {t('settings.tab_employees', default='Employees')}",
    ])

    df_levels = org_repo.get_all_hierarchy_levels()
    df_types = org_repo.get_all_function_types()
    df_funcs = org_repo.get_all_functions()
    df_emps = org_repo.get_all_employees()

    # =========================================================================
    # TAB 1: HIERARCHY LEVELS
    # =========================================================================
    with tab_levels:
        st.subheader(t("settings.hierarchy_title", default="Hierarchy Levels Management"))

        # Contextual Action Toolbar
        col_sel, col_add, col_edit, col_del = st.columns([3, 1, 1, 1], vertical_alignment="bottom")

        hl_opts = df_levels["hierarchy_level_id"].tolist() if not df_levels.empty else []
        level_map = dict(zip(df_levels["hierarchy_level_id"], df_levels["name"])) if not df_levels.empty else {}
        sel_hl_id = col_sel.selectbox(
            t("settings.selected_item", default="Selected Item"),
            options=hl_opts,
            format_func=lambda x: f"Lvl {x}: {level_map.get(x, '')}",
            key="sb_ctx_hl",
            disabled=df_levels.empty,
        )

        if col_add.button(f"➕ {t('settings.action_add', default='Add New')}", type="primary", use_container_width=True, key="btn_add_hl"):
            _open_add_hierarchy_level_dialog(org_repo, df_levels, df_funcs)

        if col_edit.button(f"✏️ {t('settings.action_edit', default='Edit')}", disabled=df_levels.empty, use_container_width=True, key="btn_edit_hl"):
            if sel_hl_id is not None:
                _open_edit_hierarchy_level_dialog(org_repo, sel_hl_id, df_levels, df_funcs)

        if col_del.button(f"🗑️ {t('settings.action_delete', default='Delete')}", disabled=df_levels.empty, use_container_width=True, key="btn_del_hl"):
            if sel_hl_id is not None:
                _open_delete_hierarchy_level_dialog(org_repo, sel_hl_id, level_map.get(sel_hl_id, f"ID {sel_hl_id}"))

        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

        # Overview Table
        enriched_levels = OrganizationService.enrich_hierarchy_levels(df_levels, df_funcs)
        if not enriched_levels.empty:
            st.dataframe(
                enriched_levels[["hierarchy_level_id", "name", "level", "parent_name", "manager_function_name"]],
                column_config={
                    "hierarchy_level_id": st.column_config.NumberColumn("ID", width="small"),
                    "name": st.column_config.TextColumn(t("settings.col_level_name", default="Level Name"), width="medium"),
                    "level": st.column_config.NumberColumn(t("settings.col_level_tier", default="Tier Level"), width="small"),
                    "parent_name": st.column_config.TextColumn(t("settings.col_parent_level", default="Parent Level"), width="medium"),
                    "manager_function_name": st.column_config.TextColumn(t("settings.col_manager_func", default="Manager Function"), width="medium"),
                },
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(t("settings.no_levels", default="No hierarchy levels registered."))

    # =========================================================================
    # TAB 2: FUNCTIONS
    # =========================================================================
    with tab_funcs:
        st.subheader(t("settings.functions_title", default="Job Functions Management"))

        # Contextual Action Toolbar
        col_f_sel, col_f_add, col_f_edit, col_f_del = st.columns([3, 1, 1, 1], vertical_alignment="bottom")

        fn_opts = df_funcs["function_id"].tolist() if not df_funcs.empty else []
        func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
        sel_fn_id = col_f_sel.selectbox(
            t("settings.selected_item", default="Selected Item"),
            options=fn_opts,
            format_func=lambda x: f"ID {x}: {func_map.get(x, '')}",
            key="sb_ctx_fn",
            disabled=df_funcs.empty,
        )

        if col_f_add.button(f"➕ {t('settings.action_add', default='Add New')}", type="primary", use_container_width=True, key="btn_add_fn"):
            _open_add_function_dialog(org_repo, df_levels, df_funcs, df_types)

        if col_f_edit.button(f"✏️ {t('settings.action_edit', default='Edit')}", disabled=df_funcs.empty, use_container_width=True, key="btn_edit_fn"):
            if sel_fn_id is not None:
                _open_edit_function_dialog(org_repo, sel_fn_id, df_levels, df_funcs, df_types)

        if col_f_del.button(f"🗑️ {t('settings.action_delete', default='Delete')}", disabled=df_funcs.empty, use_container_width=True, key="btn_del_fn"):
            if sel_fn_id is not None:
                _open_delete_function_dialog(org_repo, sel_fn_id, func_map.get(sel_fn_id, f"ID {sel_fn_id}"))

        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

        # Overview Table
        enriched_funcs = OrganizationService.enrich_functions(df_funcs, df_levels, df_types)
        if not enriched_funcs.empty:
            st.dataframe(
                enriched_funcs[["function_id", "name", "hierarchy_level_name", "function_type_name", "manager_function_name", "dual_manager_function_name"]],
                column_config={
                    "function_id": st.column_config.NumberColumn("ID", width="small"),
                    "name": st.column_config.TextColumn(t("settings.col_func_name", default="Function Title"), width="large"),
                    "hierarchy_level_name": st.column_config.TextColumn(t("settings.col_level_name", default="Hierarchy Level"), width="medium"),
                    "function_type_name": st.column_config.TextColumn(t("settings.col_type", default="Function Type"), width="medium"),
                    "manager_function_name": st.column_config.TextColumn(t("settings.col_primary_mgr", default="Primary Manager"), width="medium"),
                    "dual_manager_function_name": st.column_config.TextColumn(t("settings.col_dual_mgr", default="Dual Manager"), width="medium"),
                },
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(t("settings.no_functions", default="No job functions registered."))

    # =========================================================================
    # TAB 3: FUNCTION TYPES
    # =========================================================================
    with tab_types:
        st.subheader(t("settings.types_title", default="Function Types Management"))

        # Contextual Action Toolbar
        col_t_sel, col_t_add, col_t_edit, col_t_del = st.columns([3, 1, 1, 1], vertical_alignment="bottom")

        ft_opts = df_types["function_type_id"].tolist() if not df_types.empty else []
        type_map = dict(zip(df_types["function_type_id"], df_types["function_type"])) if not df_types.empty else {}
        sel_ft_id = col_t_sel.selectbox(
            t("settings.selected_item", default="Selected Item"),
            options=ft_opts,
            format_func=lambda x: f"ID {x}: {type_map.get(x, '')}",
            key="sb_ctx_ft",
            disabled=df_types.empty,
        )

        if col_t_add.button(f"➕ {t('settings.action_add', default='Add New')}", type="primary", use_container_width=True, key="btn_add_ft"):
            _open_add_function_type_dialog(org_repo)

        if col_t_edit.button(f"✏️ {t('settings.action_edit', default='Edit')}", disabled=df_types.empty, use_container_width=True, key="btn_edit_ft"):
            if sel_ft_id is not None:
                _open_edit_function_type_dialog(org_repo, sel_ft_id, type_map.get(sel_ft_id, ""))

        if col_t_del.button(f"🗑️ {t('settings.action_delete', default='Delete')}", disabled=df_types.empty, use_container_width=True, key="btn_del_ft"):
            if sel_ft_id is not None:
                _open_delete_function_type_dialog(org_repo, sel_ft_id, type_map.get(sel_ft_id, f"ID {sel_ft_id}"))

        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

        # Overview Table
        if not df_types.empty:
            st.dataframe(
                df_types[["function_type_id", "function_type"]],
                column_config={
                    "function_type_id": st.column_config.NumberColumn("ID", width="small"),
                    "function_type": st.column_config.TextColumn(t("settings.col_type_name", default="Function Type Name"), width="large"),
                },
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(t("settings.no_types", default="No function types registered."))

    # =========================================================================
    # TAB 4: EMPLOYEES
    # =========================================================================
    with tab_emps:
        st.subheader(t("settings.employees_title", default="Employee Directory & Profile Management"))

        enriched_emps = OrganizationService.enrich_employees(df_emps, df_funcs, df_types)

        # Search & Filter Bar
        col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
        search_emp = col_s1.text_input(t("settings.filter_search_emp", default="🔍 Search Employee"), placeholder="e.g. Sarah or EMP-001")
        all_funcs_list = df_funcs["name"].tolist() if not df_funcs.empty else []
        filter_func = col_s2.selectbox(t("settings.filter_by_func", default="Filter by Function"), options=["All"] + all_funcs_list)
        all_types_list = df_types["function_type"].tolist() if not df_types.empty else []
        filter_type = col_s3.selectbox(t("settings.filter_by_type", default="Filter by Type"), options=["All"] + all_types_list)

        filtered_emps = enriched_emps.copy() if not enriched_emps.empty else pd.DataFrame()
        if not filtered_emps.empty:
            if filter_func != "All":
                filtered_emps = filtered_emps[filtered_emps["function_name"] == filter_func]
            if filter_type != "All":
                filtered_emps = filtered_emps[filtered_emps["function_type_name"] == filter_type]
            if search_emp.strip():
                sterm = search_emp.strip().lower()
                filtered_emps = filtered_emps[
                    filtered_emps["full_name"].astype(str).str.lower().str.contains(sterm, na=False)
                    | filtered_emps["email"].astype(str).str.lower().str.contains(sterm, na=False)
                    | filtered_emps["employee_code"].astype(str).str.lower().str.contains(sterm, na=False)
                    | filtered_emps["sigle"].astype(str).str.lower().str.contains(sterm, na=False)
                ]

        # Contextual Action Toolbar
        col_e_sel, col_e_add, col_e_edit, col_e_del = st.columns([3, 1, 1, 1], vertical_alignment="bottom")

        emp_opts = filtered_emps["employee_id"].tolist() if not filtered_emps.empty else (df_emps["employee_id"].tolist() if not df_emps.empty else [])
        emp_display_map = {
            int(r["employee_id"]): f"{r['employee_code']} - {str(r['lastname']).upper()} {r['firstname']}"
            for _, r in df_emps.iterrows()
        } if not df_emps.empty else {}

        sel_emp_id = col_e_sel.selectbox(
            t("settings.selected_item", default="Selected Item"),
            options=emp_opts,
            format_func=lambda x: emp_display_map.get(x, f"ID {x}"),
            key="sb_ctx_emp",
            disabled=not emp_opts,
        )

        if col_e_add.button(f"➕ {t('settings.action_add', default='Add New')}", type="primary", use_container_width=True, key="btn_add_emp"):
            _open_add_employee_dialog(org_repo, df_funcs)

        if col_e_edit.button(f"✏️ {t('settings.action_edit', default='Edit')}", disabled=not emp_opts, use_container_width=True, key="btn_edit_emp"):
            if sel_emp_id is not None:
                _open_edit_employee_dialog(org_repo, sel_emp_id, df_funcs)

        if col_e_del.button(f"🗑️ {t('settings.action_delete', default='Delete')}", disabled=not emp_opts, use_container_width=True, key="btn_del_emp"):
            if sel_emp_id is not None:
                _open_delete_employee_dialog(org_repo, sel_emp_id, emp_display_map.get(sel_emp_id, f"ID {sel_emp_id}"))

        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

        # Overview Table
        if not filtered_emps.empty:
            st.dataframe(
                filtered_emps[["employee_code", "full_name", "email", "mobile", "sigle", "function_name", "function_type_name"]],
                column_config={
                    "employee_code": st.column_config.TextColumn(t("settings.col_emp_code", default="Code"), width="small"),
                    "full_name": st.column_config.TextColumn(t("settings.col_full_name", default="Full Name"), width="medium"),
                    "email": st.column_config.TextColumn("Email", width="medium"),
                    "mobile": st.column_config.TextColumn(t("settings.col_mobile", default="Mobile"), width="small"),
                    "sigle": st.column_config.TextColumn(t("settings.col_sigle", default="Sigle"), width="small"),
                    "function_name": st.column_config.TextColumn(t("settings.col_function", default="Function"), width="medium"),
                    "function_type_name": st.column_config.TextColumn(t("settings.col_type", default="Type"), width="small"),
                },
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(t("settings.no_employees", default="No employees registered."))
