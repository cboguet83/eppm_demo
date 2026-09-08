"""Screen 5: Organization Structure & Settings Management View with Contextual Menus and Dialogs."""

import datetime
import os
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.i18n import t
from src.models.constants import PAGE_PLANNING
from src.models.tag import ProjectTag, TagDictionary, TagGroup, TaskTag
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.repositories.schema_repo import SchemaRepository
from src.repositories.tag_repo import TagRepository
from src.services.tag_service import TagService
from app.main import (
    create_schema_service, create_project_type_service, create_organization_service,
    create_resource_pool_service, create_pool_capacity_service,
)
from app.presentation.pages.resource_pools import render_resource_pools
from app.presentation.pages.organization import (
    render_functions, render_function_types, render_teams, render_employees,
)
from app.presentation.pages.schema import render_schema_definition


# Declare Interactive Table Custom Components
_COMPONENTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "components",
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
# 5. TAG GROUP DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_tag_group", default="➕ Create Tag Group"))
def _open_add_tag_group_dialog(tag_repo: TagRepository) -> None:
    """Modal dialog to create a new tag group."""
    new_name = st.text_input(t("settings.field_group_name", default="Tag Group Name *"), placeholder="e.g. Architecture")

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Group"), type="primary", width="stretch"):
        try:
            TagService.validate_tag_group(new_name)
            new_id = tag_repo.create_tag_group(TagGroup(tag_group_name=new_name.strip()))
            st.toast(f"Tag Group '{new_name}' created (ID: {new_id})!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_edit_tag_group", default="✏️ Edit Tag Group"))
def _open_edit_tag_group_dialog(tag_repo: TagRepository, group_id: int, current_name: str) -> None:
    """Modal dialog to edit a tag group."""
    st.caption(f"ID: #{group_id}")
    edit_name = st.text_input(t("settings.field_group_name", default="Tag Group Name *"), value=current_name)

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"):
        try:
            TagService.validate_tag_group(edit_name)
            tag_repo.update_tag_group(TagGroup(id=group_id, tag_group_name=edit_name.strip()))
            st.toast("Tag Group updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_tag_group_dialog(tag_repo: TagRepository, group_id: int, group_name: str) -> None:
    """Modal dialog to confirm deletion of a tag group."""
    usage_count = tag_repo.count_tags_by_group(group_id)
    if usage_count > 0:
        st.error(f"⚠️ Cannot delete Tag Group **{group_name}** (ID: {group_id}) because {usage_count} dictionary tags belong to it.")
        if st.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
            st.rerun()
        return

    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=group_name, default=f'Are you sure you want to delete Tag Group **{group_name}** (ID: {group_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"):
        try:
            tag_repo.delete_tag_group(group_id)
            st.toast(f"Tag Group '{group_name}' deleted.", icon="🗑️")
            st.rerun()
        except Exception as e:
            st.error(f"Error deleting tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
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
    if col_save.button(t("settings.btn_save", default="💾 Save Tag"), type="primary", width="stretch"):
        try:
            TagService.validate_tag(new_tag)
            new_id = tag_repo.create_tag(TagDictionary(tag=new_tag.strip(), tag_group_id=new_group))
            st.toast(f"Tag '{new_tag}' created (ID: {new_id})!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
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
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"):
        try:
            TagService.validate_tag(edit_tag)
            tag_repo.update_tag(TagDictionary(id=tag_id, tag=edit_tag.strip(), tag_group_id=edit_group))
            st.toast("Tag updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_tag_dialog(tag_repo: TagRepository, tag_id: int, tag_name: str) -> None:
    """Modal dialog to confirm deletion of a dictionary tag."""
    usages = tag_repo.count_tag_usages(tag_id)
    if usages > 0:
        st.warning(
            f"⚠️ Tag **{tag_name}** currently has {usages} project, task, or "
            "resource-pool assignment(s). Deleting it will also remove those assignments."
        )
    else:
        st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=tag_name, default=f'Are you sure you want to delete Tag **{tag_name}** (ID: {tag_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"):
        try:
            tag_repo.delete_tag(tag_id)
            st.toast(f"Tag '{tag_name}' deleted.", icon="🗑️")
            st.rerun()
        except Exception as e:
            st.error(f"Error deleting tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
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
    if col_save.button(t("settings.btn_save", default="💾 Assign Tag"), type="primary", width="stretch"):
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

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
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
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"):
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

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_project_tag_dialog(tag_repo: TagRepository, pt_id: int, tag_label: str) -> None:
    """Modal dialog to confirm deletion of a project tag assignment."""
    st.warning(f"⚠️ Are you sure you want to remove project tag assignment **{tag_label}** (ID: #{pt_id})?")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"):
        tag_repo.delete_project_tag(pt_id)
        st.toast(f"Project tag #{pt_id} deleted.", icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


# =============================================================================
# 8. TASK TAG DIALOGS
# =============================================================================
def _select_task_for_tag(milestone_repo: MilestoneRepository, *, key: str,
                         current_task_id: Optional[int] = None) -> Optional[int]:
    search = st.text_input("Find task by name, project or #ID", key=f"{key}_search")
    choices = milestone_repo.search_task_choices(search)
    if current_task_id is not None and not any(row["id"] == current_task_id for row in choices):
        current = milestone_repo.get_milestone_by_id(current_task_id)
        if current:
            choices.insert(0, current)
    labels = {row["id"]: f"#{row['id']} — {row['task_name']} · {row.get('project_name', '')}" for row in choices}
    options = list(labels)
    st.caption("Up to 50 matching tasks. Refine the search or enter an exact task ID.")
    return st.selectbox(
        t("settings.field_task", default="Task *"), options=options,
        index=options.index(current_task_id) if current_task_id in options else None,
        format_func=lambda task_id: labels[task_id], key=f"{key}_task",
    )


def _handle_task_tag_query_change() -> None:
    event = st.session_state.get("task_tag_interactive_table")
    if isinstance(event, dict) and event.get("action") == "query_task_tags":
        query = event.get("query", {})
        if isinstance(query, dict):
            st.session_state["task_tag_query"] = {key: query[key] for key in
                ("page", "search", "filters", "sort", "ascending") if key in query}
            st.session_state["_last_task_tag_table_nonce"] = event.get("nonce")
            st.session_state["_last_task_tag_query_nonce"] = event.get("nonce")


@st.dialog(t("settings.dialog_add_task_tag", default="➕ Assign Task Tag"))
def _open_add_task_tag_dialog(
    tag_repo: TagRepository,
    milestone_repo: MilestoneRepository,
) -> None:
    """Modal dialog to assign a tag to a task."""
    selected_task = _select_task_for_tag(milestone_repo, key="add_task_tag")
    df_tags = tag_repo.get_task_tag_group_tags()

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
    if col_save.button(t("settings.btn_save", default="💾 Assign Tag"), type="primary", width="stretch", disabled=selected_task is None):
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

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_edit_task_tag", default="✏️ Edit Task Tag Assignment"))
def _open_edit_task_tag_dialog(
    tag_repo: TagRepository,
    tt_id: int,
    current_task_id: int,
    current_tag_id: Optional[int],
    current_free_tag: Optional[str],
    milestone_repo: MilestoneRepository,
) -> None:
    """Modal dialog to edit a task tag assignment."""
    st.caption(f"Assignment ID: #{tt_id}")
    selected_task = _select_task_for_tag(milestone_repo, key=f"edit_task_tag_{tt_id}", current_task_id=current_task_id)
    df_tags = tag_repo.get_task_tag_group_tags()

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
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch", disabled=selected_task is None):
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

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_task_tag_dialog(tag_repo: TagRepository, tt_id: int, tag_label: str) -> None:
    """Modal dialog to confirm deletion of a task tag assignment."""
    st.warning(f"⚠️ Are you sure you want to remove task tag assignment **{tag_label}** (ID: #{tt_id})?")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"):
        tag_repo.delete_task_tag(tt_id)
        st.toast(f"Task tag #{tt_id} deleted.", icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


# =============================================================================
# MAIN SETTINGS VIEW ENTRYPOINT
# =============================================================================
def render_settings_view(
    org_repo: OrganizationRepository,
    tag_repo: Optional[TagRepository] = None,
    project_repo: Optional[ProjectRepository] = None,
    milestone_repo: Optional[MilestoneRepository] = None,
    pool_repo: Optional[ResourcePoolRepository] = None,
    schema_repo: Optional[SchemaRepository] = None,
) -> None:
    """Renders the Settings screen with sections for Organization Structure and Parameter Definition."""
    st.header(f"⚙️ {t('settings.title', default='Settings')}")

    schema_repo = schema_repo or SchemaRepository(org_repo.db_path)

    # Project roles and event types are independent, lazily loaded catalogs.
    default_section_idx = 0
    if st.session_state.get("settings_active_section") == "parameters":
        default_section_idx = 1

    section_labels = {
        "org_structure": f"🏢 {t('settings.section_org_structure', default='Organization Structure')}",
        "param_def": f"🧩 {t('settings.section_param_definition', default='Parameter Definition')}",
        "project_configuration": t("project_collaboration.configuration", default="Project configuration"),
    }
    selected_section = st.radio(
        "Settings Section",
        options=list(section_labels),
        format_func=section_labels.get,
        index=default_section_idx,
        horizontal=True,
        label_visibility="collapsed",
        key="rb_settings_section",
    )

    if selected_section == "param_def":
        render_schema_definition(
            create_schema_service(schema_repo.db_path), create_project_type_service(schema_repo.db_path),
        )
        return

    if selected_section == "project_configuration":
        from src.views.project_collaboration_view import render_project_catalog
        roles_tab, events_tab = st.tabs([
            t("project_collaboration.roles", default="Project roles"),
            t("project_collaboration.types", default="Event types"),
        ], key="project_configuration_tab", on_change="rerun")
        if roles_tab.open:
            with roles_tab:
                render_project_catalog(org_repo.db_path, "role")
        if events_tab.open:
            with events_tab:
                render_project_catalog(org_repo.db_path, "event_type")
        return

    tag_repo = tag_repo or TagRepository(org_repo.db_path)
    project_repo = project_repo or ProjectRepository(org_repo.db_path)
    milestone_repo = milestone_repo or MilestoneRepository(org_repo.db_path)
    pool_repo = pool_repo or ResourcePoolRepository(org_repo.db_path)

    settings_tab_labels = [
        f"💼 {t('settings.tab_functions', default='Functions')}",
        f"🏷️ {t('settings.tab_types', default='Function Types')}",
        f"🛡️ {t('settings.tab_teams', default='Teams')}",
        f"👥 {t('settings.tab_employees', default='Employees')}",
        f"📁 {t('settings.tab_tag_groups', default='Tag Groups')}",
        f"📚 {t('settings.tab_tag_dict', default='Tag Dictionary')}",
        f"📌 {t('settings.tab_proj_tags', default='Project Tags')}",
        f"📋 {t('settings.tab_task_tags', default='Task Tags')}",
        f"🏊 {t('settings.tab_resource_pools', default='Resource Pools')}",
    ]
    requested_tab = st.session_state.pop("settings_active_tab", None)
    if requested_tab == "resource_pools":
        st.session_state["settings_tab_selection"] = settings_tab_labels[-1]
    (
        tab_funcs,
        tab_types,
        tab_teams,
        tab_emps,
        tab_tag_groups,
        tab_tag_dict,
        tab_proj_tags,
        tab_task_tags,
        tab_pools,
    ) = st.tabs(settings_tab_labels, key="settings_tab_selection", on_change="rerun")


    # =========================================================================
    # TAB 1: FUNCTIONS
    # =========================================================================
    if tab_funcs.open:
        with tab_funcs:
            render_functions(create_organization_service(org_repo.db_path))

    # =========================================================================
    # TAB 3: FUNCTION TYPES
    # =========================================================================
    if tab_types.open:
        with tab_types:
            render_function_types(create_organization_service(org_repo.db_path))

    # =========================================================================
    # TAB 4: TEAMS
    # =========================================================================
    if tab_teams.open:
        with tab_teams:
            render_teams(create_organization_service(org_repo.db_path))

    # =========================================================================
    # TAB 5: EMPLOYEES
    # =========================================================================
    if tab_emps.open:
        with tab_emps:
            render_employees(create_organization_service(org_repo.db_path))

    # =========================================================================
    # TAB 5: TAG GROUPS
    # =========================================================================
    if tab_tag_groups.open:
        with tab_tag_groups:
            df_groups = tag_repo.get_all_tag_groups()
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
    if tab_tag_dict.open:
        with tab_tag_dict:
            df_groups = tag_repo.get_all_tag_groups()
            df_tags = tag_repo.get_all_tags()
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
    if tab_proj_tags.open:
        with tab_proj_tags:
            df_proj_dict_tags = tag_repo.get_project_tag_group_tags()
            df_proj_tags = tag_repo.get_all_project_tags()
            df_projects = project_repo.get_all_projects()
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
                        _open_add_project_tag_dialog(tag_repo, df_projects, df_proj_dict_tags)
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
                                df_proj_dict_tags,
                            )
                    elif action == "delete_project_tag":
                        pt_id = proj_tag_table_event.get("pt_id")
                        t_label = proj_tag_table_event.get("tag_label", f"ID {pt_id}")
                        if pt_id is not None:
                            _open_delete_project_tag_dialog(tag_repo, int(pt_id), str(t_label))

    # =========================================================================
    # TAB 8: TASK TAGS
    # =========================================================================
    if tab_task_tags.open:
        with tab_task_tags:
            query = st.session_state.get("task_tag_query", {})
            page_data = tag_repo.get_task_tags_page(**query)
            df_task_tags = page_data.pop("rows")
            total_task_tags = page_data["total"]
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
                page_info=page_data,
                query=query,
                query_nonce=st.session_state.get("_last_task_tag_query_nonce"),
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
                on_change=_handle_task_tag_query_change,
            )

            if task_tag_table_event and isinstance(task_tag_table_event, dict):
                nonce = task_tag_table_event.get("nonce")
                last_nonce = st.session_state.get("_last_task_tag_table_nonce")
                if nonce and nonce != last_nonce:
                    st.session_state["_last_task_tag_table_nonce"] = nonce
                    action = task_tag_table_event.get("action")
                    if action == "add_task_tag":
                        _open_add_task_tag_dialog(tag_repo, milestone_repo)
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
                                milestone_repo,
                            )
                    elif action == "delete_task_tag":
                        tt_id = task_tag_table_event.get("tt_id")
                        t_label = task_tag_table_event.get("tag_label", f"ID {tt_id}")
                        if tt_id is not None:
                            _open_delete_task_tag_dialog(tag_repo, int(tt_id), str(t_label))

    # =========================================================================
    # TAB 9: RESOURCE POOLS
    # =========================================================================
    if tab_pools.open:
        with tab_pools:
            render_resource_pools(
                create_resource_pool_service(pool_repo.db_path),
                create_pool_capacity_service(pool_repo.db_path),
                create_organization_service(org_repo.db_path), PAGE_PLANNING,
            )
