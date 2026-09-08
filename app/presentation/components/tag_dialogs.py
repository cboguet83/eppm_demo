"""Tag dialogs using an injected application service."""

from collections.abc import Callable
from dataclasses import asdict
from functools import wraps
import pandas as pd
import streamlit as st

from app.application.exceptions import TagStorageError
from app.application.services.tags import TagService
from app.domain.tags.models import ProjectTag, TagDictionary, TagGroup, TaskTag
from app.presentation.components.tag_frames import get_task_tag_group_tags_frame
from app.presentation.i18n import t


def tag_errors[**P](render: Callable[P, None]) -> Callable[P, None]:
    """Render safe application failures, including dialog reads and reruns."""

    @wraps(render)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            render(*args, **kwargs)
        except (ValueError, TagStorageError) as exc:
            st.error(str(exc))

    return guarded


def require_change(changed: bool) -> None:
    """Do not report an edit or deletion of a missing record as successful."""
    if not changed:
        raise ValueError("This record no longer exists. Please refresh and try again.")


@st.dialog(t("settings.dialog_add_tag_group", default="➕ Create Tag Group"))
@tag_errors
def _open_add_tag_group_dialog(service: TagService) -> None:
    """Modal dialog to create a new tag group."""
    new_name = st.text_input(
        t("settings.field_group_name", default="Tag Group Name *"), placeholder="e.g. Architecture"
    )
    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save", default="💾 Save Group"), type="primary", width="stretch"
    ):
        new_id = service.create_tag_group(TagGroup(tag_group_name=new_name.strip()))
        st.toast(f"Tag Group '{new_name}' created (ID: {new_id})!", icon="✅")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_edit_tag_group", default="✏️ Edit Tag Group"))
@tag_errors
def _open_edit_tag_group_dialog(service: TagService, group_id: int, current_name: str) -> None:
    """Modal dialog to edit a tag group."""
    st.caption(f"ID: #{group_id}")
    edit_name = st.text_input(
        t("settings.field_group_name", default="Tag Group Name *"), value=current_name
    )
    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"
    ):
        require_change(
            service.update_tag_group(TagGroup(id=group_id, tag_group_name=edit_name.strip()))
        )
        st.toast("Tag Group updated successfully!", icon="✏️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
@tag_errors
def _open_delete_tag_group_dialog(service: TagService, group_id: int, group_name: str) -> None:
    """Modal dialog to confirm deletion of a tag group."""
    usage_count = service.count_tags_by_group(group_id)
    if usage_count > 0:
        st.error(
            f"⚠️ Cannot delete Tag Group **{group_name}** (ID: {group_id}) because {usage_count} dictionary tags belong to it."
        )
        if st.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
            st.rerun()
        return
    st.warning(
        f"⚠️ {t('settings.delete_confirm_msg', name=group_name, default=f'Are you sure you want to delete Tag Group **{group_name}** (ID: {group_id})?')}"
    )
    st.caption("This action cannot be undone.")
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(
        t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"
    ):
        require_change(service.delete_tag_group(group_id))
        st.toast(f"Tag Group '{group_name}' deleted.", icon="🗑️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_add_tag", default="➕ Create Tag"))
@tag_errors
def _open_add_tag_dialog(service: TagService, df_groups: pd.DataFrame) -> None:
    """Modal dialog to create a new tag in the dictionary."""
    new_tag = st.text_input(
        t("settings.field_tag_name", default="Tag Label *"), placeholder="e.g. Cloud Native"
    )
    group_opts = [None] + (df_groups["id"].tolist() if not df_groups.empty else [])
    group_map = (
        dict(zip(df_groups["id"], df_groups["tag_group_name"])) if not df_groups.empty else {}
    )
    new_group = st.selectbox(
        t("settings.field_tag_group", default="Tag Group (Optional)"),
        options=group_opts,
        format_func=lambda x: f"📁 {group_map.get(x, '')}" if x is not None else "— None",
    )
    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save", default="💾 Save Tag"), type="primary", width="stretch"
    ):
        new_id = service.create_tag(TagDictionary(tag=new_tag.strip(), tag_group_id=new_group))
        st.toast(f"Tag '{new_tag}' created (ID: {new_id})!", icon="✅")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_edit_tag", default="✏️ Edit Tag"))
@tag_errors
def _open_edit_tag_dialog(
    service: TagService,
    tag_id: int,
    current_tag: str,
    current_group_id: int | None,
    df_groups: pd.DataFrame,
) -> None:
    """Modal dialog to edit a tag in the dictionary."""
    st.caption(f"ID: #{tag_id}")
    edit_tag = st.text_input(
        t("settings.field_tag_name", default="Tag Label *"), value=current_tag
    )
    group_opts = [None] + (df_groups["id"].tolist() if not df_groups.empty else [])
    group_map = (
        dict(zip(df_groups["id"], df_groups["tag_group_name"])) if not df_groups.empty else {}
    )
    idx = group_opts.index(current_group_id) if current_group_id in group_opts else 0
    edit_group = st.selectbox(
        t("settings.field_tag_group", default="Tag Group (Optional)"),
        options=group_opts,
        index=idx,
        format_func=lambda x: f"📁 {group_map.get(x, '')}" if x is not None else "— None",
    )
    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"
    ):
        require_change(
            service.update_tag(
                TagDictionary(id=tag_id, tag=edit_tag.strip(), tag_group_id=edit_group)
            )
        )
        st.toast("Tag updated successfully!", icon="✏️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
@tag_errors
def _open_delete_tag_dialog(service: TagService, tag_id: int, tag_name: str) -> None:
    """Modal dialog to confirm deletion of a dictionary tag."""
    usages = service.count_tag_usages(tag_id)
    if usages > 0:
        st.warning(
            f"⚠️ Tag **{tag_name}** currently has {usages} project, task, or resource-pool assignment(s). Deleting it will also remove those assignments."
        )
    else:
        st.warning(
            f"⚠️ {t('settings.delete_confirm_msg', name=tag_name, default=f'Are you sure you want to delete Tag **{tag_name}** (ID: {tag_id})?')}"
        )
    st.caption("This action cannot be undone.")
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(
        t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"
    ):
        require_change(service.delete_tag(tag_id))
        st.toast(f"Tag '{tag_name}' deleted.", icon="🗑️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_add_proj_tag", default="➕ Assign Project Tag"))
@tag_errors
def _open_add_project_tag_dialog(
    service: TagService, df_projects: pd.DataFrame, df_tags: pd.DataFrame
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
        format_func=lambda x: f"🏷️ {tag_map[x]}" if x is not None else "— None (Use Free Tag)",
    )
    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        placeholder="e.g. Q3-Urgent",
    )
    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save", default="💾 Assign Tag"), type="primary", width="stretch"
    ):
        pt_id = service.create_project_tag(
            ProjectTag(project_id=selected_proj, tag_id=selected_tag, free_tag=free_tag_val)
        )
        st.toast(f"Project tag assignment #{pt_id} created!", icon="✅")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_edit_proj_tag", default="✏️ Edit Project Tag Assignment"))
@tag_errors
def _open_edit_project_tag_dialog(
    service: TagService,
    pt_id: int,
    current_project_id: int,
    current_tag_id: int | None,
    current_free_tag: str | None,
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
        format_func=lambda x: f"🏷️ {tag_map[x]}" if x is not None else "— None (Use Free Tag)",
    )
    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        value=current_free_tag or "",
    )
    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"
    ):
        require_change(
            service.update_project_tag(
                ProjectTag(
                    id=pt_id, project_id=selected_proj, tag_id=selected_tag, free_tag=free_tag_val
                )
            )
        )
        st.toast("Project tag updated successfully!", icon="✏️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
@tag_errors
def _open_delete_project_tag_dialog(service: TagService, pt_id: int, tag_label: str) -> None:
    """Modal dialog to confirm deletion of a project tag assignment."""
    st.warning(
        f"⚠️ Are you sure you want to remove project tag assignment **{tag_label}** (ID: #{pt_id})?"
    )
    st.caption("This action cannot be undone.")
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(
        t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"
    ):
        require_change(service.delete_project_tag(pt_id))
        st.toast(f"Project tag #{pt_id} deleted.", icon="🗑️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


def _select_task_for_tag(
    service: TagService, *, key: str, current_task_id: int | None = None
) -> int | None:
    search = st.text_input("Find task by name, project or #ID", key=f"{key}_search")
    choices = [asdict(row) for row in service.search_task_choices(search)]
    if current_task_id is not None and (
        not any((row["id"] == current_task_id for row in choices))
    ):
        current = service.get_task_choice(current_task_id)
        if current:
            choices.insert(0, asdict(current))
    labels = {
        row["id"]: f"#{row['id']} — {row['task_name']} · {row.get('project_name', '')}"
        for row in choices
    }
    options = list(labels)
    st.caption("Up to 50 matching tasks. Refine the search or enter an exact task ID.")
    return st.selectbox(
        t("settings.field_task", default="Task *"),
        options=options,
        index=options.index(current_task_id) if current_task_id in options else None,
        format_func=lambda task_id: labels[task_id],
        key=f"{key}_task",
    )


def _handle_task_tag_query_change() -> None:
    event = st.session_state.get("task_tag_interactive_table")
    if isinstance(event, dict) and event.get("action") == "query_task_tags":
        query = event.get("query", {})
        if isinstance(query, dict):
            st.session_state["task_tag_query"] = {
                key: query[key]
                for key in ("page", "search", "filters", "sort", "ascending")
                if key in query
            }
            st.session_state["_last_task_tag_table_nonce"] = event.get("nonce")
            st.session_state["_last_task_tag_query_nonce"] = event.get("nonce")


@st.dialog(t("settings.dialog_add_task_tag", default="➕ Assign Task Tag"))
@tag_errors
def _open_add_task_tag_dialog(service: TagService) -> None:
    """Modal dialog to assign a tag to a task."""
    selected_task = _select_task_for_tag(service, key="add_task_tag")
    df_tags = get_task_tag_group_tags_frame(service.get_task_tag_group_tags())
    tag_opts = [None] + (df_tags["id"].tolist() if not df_tags.empty else [])
    tag_map = dict(zip(df_tags["id"], df_tags["tag"])) if not df_tags.empty else {}
    selected_tag = st.selectbox(
        t("settings.field_dict_tag", default="Dictionary Tag (Optional)"),
        options=tag_opts,
        format_func=lambda x: f"🏷️ {tag_map[x]}" if x is not None else "— None (Use Free Tag)",
    )
    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        placeholder="e.g. Needs-Refinement",
    )
    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save", default="💾 Assign Tag"),
        type="primary",
        width="stretch",
        disabled=selected_task is None,
    ):
        tt_id = service.create_task_tag(
            TaskTag(task_id=selected_task, tag_id=selected_tag, free_tag=free_tag_val)
        )
        st.toast(f"Task tag assignment #{tt_id} created!", icon="✅")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_edit_task_tag", default="✏️ Edit Task Tag Assignment"))
@tag_errors
def _open_edit_task_tag_dialog(
    service: TagService,
    tt_id: int,
    current_task_id: int,
    current_tag_id: int | None,
    current_free_tag: str | None,
) -> None:
    """Modal dialog to edit a task tag assignment."""
    st.caption(f"Assignment ID: #{tt_id}")
    selected_task = _select_task_for_tag(
        service, key=f"edit_task_tag_{tt_id}", current_task_id=current_task_id
    )
    df_tags = get_task_tag_group_tags_frame(service.get_task_tag_group_tags())
    tag_opts = [None] + (df_tags["id"].tolist() if not df_tags.empty else [])
    tag_map = dict(zip(df_tags["id"], df_tags["tag"])) if not df_tags.empty else {}
    tg_idx = tag_opts.index(current_tag_id) if current_tag_id in tag_opts else 0
    selected_tag = st.selectbox(
        t("settings.field_dict_tag", default="Dictionary Tag (Optional)"),
        options=tag_opts,
        index=tg_idx,
        format_func=lambda x: f"🏷️ {tag_map[x]}" if x is not None else "— None (Use Free Tag)",
    )
    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        value=current_free_tag or "",
    )
    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save_changes", default="💾 Save Changes"),
        type="primary",
        width="stretch",
        disabled=selected_task is None,
    ):
        require_change(
            service.update_task_tag(
                TaskTag(
                    id=tt_id, task_id=selected_task, tag_id=selected_tag, free_tag=free_tag_val
                )
            )
        )
        st.toast("Task tag updated successfully!", icon="✏️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
@tag_errors
def _open_delete_task_tag_dialog(service: TagService, tt_id: int, tag_label: str) -> None:
    """Modal dialog to confirm deletion of a task tag assignment."""
    st.warning(
        f"⚠️ Are you sure you want to remove task tag assignment **{tag_label}** (ID: #{tt_id})?"
    )
    st.caption("This action cannot be undone.")
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(
        t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"
    ):
        require_change(service.delete_task_tag(tt_id))
        st.toast(f"Task tag #{tt_id} deleted.", icon="🗑️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()
