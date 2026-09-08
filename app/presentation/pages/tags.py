"""Independent tag Settings sections using application services."""

from dataclasses import asdict
import pandas as pd
import streamlit as st
from app.application.services.tags import TagService
from app.presentation.components.tag_frames import (
    get_all_tag_groups_frame,
    get_all_tags_frame,
    get_all_project_tags_frame,
    get_project_tag_group_tags_frame,
    page_frame,
)
from app.presentation.components.tag_tables import (
    interactive_tag_group_table as _interactive_tag_group_table,
    interactive_tag_dictionary_table as _interactive_tag_dictionary_table,
    interactive_project_tag_table as _interactive_project_tag_table,
    interactive_task_tag_table as _interactive_task_tag_table,
)
from app.presentation.components.tag_dialogs import (
    tag_errors,
    _handle_task_tag_query_change,
    _open_add_tag_group_dialog,
    _open_edit_tag_group_dialog,
    _open_delete_tag_group_dialog,
    _open_add_tag_dialog,
    _open_edit_tag_dialog,
    _open_delete_tag_dialog,
    _open_add_project_tag_dialog,
    _open_edit_project_tag_dialog,
    _open_delete_project_tag_dialog,
    _open_add_task_tag_dialog,
    _open_edit_task_tag_dialog,
    _open_delete_task_tag_dialog,
)
from app.presentation.i18n import t


@tag_errors
def render_tag_groups(service: TagService) -> None:
    """Render the active tag groups section."""
    groups = service.get_all_tag_groups()
    df_groups = get_all_tag_groups_frame(groups)
    counts = {row.id: row.tag_count for row in groups}
    total_groups = len(df_groups)
    st.subheader(
        f"{t('settings.tag_groups_title', default='Tag Groups Taxonomy')} ({total_groups} {t('settings.stat_tag_groups', default='Tag Groups')})"
    )
    groups_payload = []
    if not df_groups.empty:
        for row in df_groups.to_dict(orient="records"):
            gid = int(row["id"])
            count = counts[gid]
            groups_payload.append(
                {
                    "id": gid,
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "tag_count": count,
                }
            )
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
                _open_add_tag_group_dialog(service)
            elif action == "edit_tag_group":
                gid = group_table_event.get("group_id")
                gname = group_table_event.get("tag_group_name", "")
                if gid is not None:
                    _open_edit_tag_group_dialog(service, int(gid), str(gname))
            elif action == "delete_tag_group":
                gid = group_table_event.get("group_id")
                gname = group_table_event.get("tag_group_name", f"ID {gid}")
                if gid is not None:
                    _open_delete_tag_group_dialog(service, int(gid), str(gname))


@tag_errors
def render_tag_dictionary(service: TagService) -> None:
    """Render the active tag dictionary section."""
    df_groups = get_all_tag_groups_frame(service.get_all_tag_groups())
    tags = service.get_all_tags()
    df_tags = get_all_tags_frame(tags)
    counts = {row.id: row.usage_count for row in tags}
    total_tags = len(df_tags)
    st.subheader(
        f"{t('settings.tag_dict_title', default='Tag Dictionary Taxonomy')} ({total_tags} {t('settings.stat_tags', default='Tags')})"
    )
    tags_payload = []
    if not df_tags.empty:
        for row in df_tags.to_dict(orient="records"):
            tid = int(row["id"])
            usages = counts[tid]
            tags_payload.append(
                {
                    "id": tid,
                    "tag": str(row.get("tag") or ""),
                    "tag_group_id": (
                        int(row["tag_group_id"]) if pd.notna(row.get("tag_group_id")) else None
                    ),
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "usage_count": usages,
                }
            )
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
                _open_add_tag_dialog(service, df_groups)
            elif action == "edit_tag":
                tid = tag_table_event.get("tag_id")
                tname = tag_table_event.get("tag", "")
                tg_id = tag_table_event.get("tag_group_id")
                if tid is not None:
                    _open_edit_tag_dialog(
                        service,
                        int(tid),
                        str(tname),
                        int(tg_id) if tg_id is not None else None,
                        df_groups,
                    )
            elif action == "delete_tag":
                tid = tag_table_event.get("tag_id")
                tname = tag_table_event.get("tag", f"ID {tid}")
                if tid is not None:
                    _open_delete_tag_dialog(service, int(tid), str(tname))


@tag_errors
def render_project_tags(service: TagService) -> None:
    """Render the active project tags section."""
    df_proj_dict_tags = get_project_tag_group_tags_frame(service.get_project_tag_group_tags())
    df_proj_tags = get_all_project_tags_frame(service.get_all_project_tags())
    df_projects = pd.DataFrame(
        [asdict(row) for row in service.project_choices()], columns=["id", "name"]
    )
    total_proj_tags = len(df_proj_tags)
    st.subheader(
        f"{t('settings.proj_tags_title', default='Project Tag Assignments')} ({total_proj_tags} {t('settings.stat_project_tags', default='Project Tags')})"
    )
    proj_tags_payload = []
    if not df_proj_tags.empty:
        for row in df_proj_tags.to_dict(orient="records"):
            proj_tags_payload.append(
                {
                    "id": int(row["id"]),
                    "project_id": int(row["project_id"]),
                    "project_name": str(
                        row.get("project_name") or f"Project #{row['project_id']}"
                    ),
                    "tag_id": int(row["tag_id"]) if pd.notna(row.get("tag_id")) else None,
                    "tag_name": str(row.get("tag_name") or ""),
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "free_tag": str(row.get("free_tag") or ""),
                }
            )
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
                _open_add_project_tag_dialog(service, df_projects, df_proj_dict_tags)
            elif action == "edit_project_tag":
                pt_id = proj_tag_table_event.get("pt_id")
                p_id = proj_tag_table_event.get("project_id")
                t_id = proj_tag_table_event.get("tag_id")
                f_tag = proj_tag_table_event.get("free_tag")
                if pt_id is not None and p_id is not None:
                    _open_edit_project_tag_dialog(
                        service,
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
                    _open_delete_project_tag_dialog(service, int(pt_id), str(t_label))


@tag_errors
def render_task_tags(service: TagService) -> None:
    """Render the active task tags section."""
    query = st.session_state.get("task_tag_query", {})
    page_data = page_frame(service.get_task_tags_page(**query))
    df_task_tags = page_data.pop("rows")
    total_task_tags = page_data["total"]
    st.subheader(
        f"{t('settings.task_tags_title', default='Task Tag Assignments')} ({total_task_tags} {t('settings.stat_task_tags', default='Task Tags')})"
    )
    task_tags_payload = []
    if not df_task_tags.empty:
        for row in df_task_tags.to_dict(orient="records"):
            task_tags_payload.append(
                {
                    "id": int(row["id"]),
                    "task_id": int(row["task_id"]),
                    "task_name": str(row.get("task_name") or f"Task #{row['task_id']}"),
                    "project_name": str(row.get("project_name") or ""),
                    "tag_id": int(row["tag_id"]) if pd.notna(row.get("tag_id")) else None,
                    "tag_name": str(row.get("tag_name") or ""),
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "free_tag": str(row.get("free_tag") or ""),
                }
            )
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
                _open_add_task_tag_dialog(service)
            elif action == "edit_task_tag":
                tt_id = task_tag_table_event.get("tt_id")
                t_id = task_tag_table_event.get("task_id")
                tag_id = task_tag_table_event.get("tag_id")
                f_tag = task_tag_table_event.get("free_tag")
                if tt_id is not None and t_id is not None:
                    _open_edit_task_tag_dialog(
                        service,
                        int(tt_id),
                        int(t_id),
                        int(tag_id) if tag_id is not None else None,
                        str(f_tag) if f_tag else None,
                    )
            elif action == "delete_task_tag":
                tt_id = task_tag_table_event.get("tt_id")
                t_label = task_tag_table_event.get("tag_label", f"ID {tt_id}")
                if tt_id is not None:
                    _open_delete_task_tag_dialog(service, int(tt_id), str(t_label))
