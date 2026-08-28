"""Screen 4: Planning & Step Loader View (Interactive Drag & Drop Gantt and Plotly Roadmap)."""

import datetime
import os
from typing import Any, Optional, Union

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from src.i18n import get_current_locale, get_section_catalog, t
from src.models.constants import PAGE_PROJECT_MASTER
from src.models.tag import ProjectTag, TaskTag
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.tag_repo import TagRepository
from src.services.milestone_service import MilestoneService

# Declare Frappe Gantt Custom Component
_COMPONENT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "components",
    "gantt",
)
_interactive_gantt = components.declare_component("interactive_gantt", path=_COMPONENT_PATH)


@st.dialog(t("planning.dialog_project_tags_title", default="🏷️ Manage Project Tags"))
def _manage_project_tags_dialog(project_id: int, project_name: str, tag_repo: TagRepository) -> None:
    """Modal dialog for attaching, editing, and deleting tags on a project."""
    st.markdown(f"#### 📁 {project_name} `[#{project_id}]`")

    # 1. Existing Tags on Project
    df_current_tags = tag_repo.get_project_tags_by_project(project_id)
    st.markdown(f"##### {t('planning.current_tags', default='Current Assigned Tags')}")
    if df_current_tags.empty:
        st.info(t("planning.no_tags_assigned", default="No tags currently attached to this project."))
    else:
        for _, row in df_current_tags.iterrows():
            pt_id = int(row["id"])
            t_name = row.get("tag_name")
            g_name = row.get("tag_group_name")
            f_name = row.get("free_tag")
            display_label = f"🏷️ {t_name}" if pd.notna(t_name) and str(t_name).strip() else f"🏷️ {f_name}"
            if pd.notna(g_name) and str(g_name).strip():
                display_label = f"[{g_name}] {display_label}"

            c_tag, c_del = st.columns([4, 1])
            c_tag.markdown(f"**{display_label}**")
            if c_del.button("🗑️", key=f"btn_del_pt_{pt_id}", help="Remove tag from project"):
                tag_repo.delete_project_tag(pt_id)
                st.toast(t("planning.toast_tag_removed", default="Tag removed!"), icon="🗑️")
                st.rerun()

    st.divider()
    # 2. Attach New Tag
    st.markdown(f"##### ➕ {t('planning.attach_new_tag', default='Attach New Tag')}")
    df_tags = tag_repo.get_project_tag_group_tags()
    tag_options = [(None, t("planning.select_dict_tag_placeholder", default="-- Select from Tag Dictionary (Optional) --"))] + [
        (int(r["id"]), str(r["tag"]))
        for _, r in df_tags.iterrows()
    ]
    selected_tag_tuple = st.selectbox(
        t("planning.select_dict_tag", default="Dictionary Tag"),
        options=tag_options,
        format_func=lambda x: x[1],
        key="sb_attach_proj_tag",
    )
    selected_tag_id = selected_tag_tuple[0] if selected_tag_tuple else None

    free_tag_input = st.text_input(
        t("planning.free_tag_optional", default="Custom / Free Tag (Optional)"),
        placeholder="e.g. Q3-Priority, Pilot-Launch",
        key="ti_attach_proj_free_tag",
    )

    col_btn_save, col_btn_close = st.columns([3, 1])
    with col_btn_save:
        if st.button(t("planning.btn_attach_tag", default="Attach Tag"), type="primary", key="btn_confirm_attach_proj_tag"):
            if selected_tag_id is None and not free_tag_input.strip():
                st.error(t("planning.tag_required_error", default="Please select a dictionary tag or enter a custom tag."))
            else:
                tag_repo.create_project_tag(
                    ProjectTag(
                        project_id=project_id,
                        tag_id=selected_tag_id,
                        free_tag=free_tag_input.strip() if free_tag_input.strip() else None,
                    )
                )
                st.toast(t("planning.toast_tag_attached", default="Tag attached to project!"), icon="🏷️")
                st.rerun()

    with col_btn_close:
        if st.button(t("planning.btn_close_dialog", default="Close"), key="btn_close_proj_dialog"):
            st.rerun()


@st.dialog(t("planning.dialog_task_tags_title", default="🏷️ Manage Task Tags"))
def _manage_task_tags_dialog(task_id: int, task_name: str, tag_repo: TagRepository) -> None:
    """Modal dialog for adding, editing, and deleting tags on a task."""
    st.markdown(f"#### 📋 {task_name} `[Task #{task_id}]`")

    # 1. Existing Task Tags
    df_current_tags = tag_repo.get_task_tags_by_task(task_id)
    st.markdown(f"##### {t('planning.current_tags', default='Current Assigned Tags')}")
    if df_current_tags.empty:
        st.info(t("planning.no_task_tags_assigned", default="No tags currently attached to this task."))
    else:
        for _, row in df_current_tags.iterrows():
            tt_id = int(row["id"])
            t_name = row.get("tag_name")
            g_name = row.get("tag_group_name")
            f_name = row.get("free_tag")
            display_label = f"🏷️ {t_name}" if pd.notna(t_name) and str(t_name).strip() else f"🏷️ {f_name}"
            if pd.notna(g_name) and str(g_name).strip():
                display_label = f"[{g_name}] {display_label}"

            c_tag, c_del = st.columns([4, 1])
            c_tag.markdown(f"**{display_label}**")
            if c_del.button("🗑️", key=f"btn_del_tt_{tt_id}", help="Remove tag from task"):
                tag_repo.delete_task_tag(tt_id)
                st.toast(t("planning.toast_task_tag_removed", default="Task tag removed!"), icon="🗑️")
                st.rerun()

    st.divider()
    # 2. Attach New Tag to Task
    st.markdown(f"##### ➕ {t('planning.attach_new_task_tag', default='Attach New Tag to Task')}")
    df_tags = tag_repo.get_task_tag_group_tags()
    tag_options = [(None, t("planning.select_dict_tag_placeholder", default="-- Select from Tag Dictionary (Optional) --"))] + [
        (int(r["id"]), str(r["tag"]))
        for _, r in df_tags.iterrows()
    ]
    selected_tag_tuple = st.selectbox(
        t("planning.select_dict_tag", default="Dictionary Tag"),
        options=tag_options,
        format_func=lambda x: x[1],
        key="sb_attach_task_tag",
    )
    selected_tag_id = selected_tag_tuple[0] if selected_tag_tuple else None

    free_tag_input = st.text_input(
        t("planning.free_tag_optional", default="Custom / Free Tag (Optional)"),
        placeholder="e.g. Critical-Path, Security-Review",
        key="ti_attach_task_free_tag",
    )

    col_btn_save, col_btn_close = st.columns([3, 1])
    with col_btn_save:
        if st.button(t("planning.btn_attach_tag", default="Attach Tag"), type="primary", key="btn_confirm_attach_task_tag"):
            if selected_tag_id is None and not free_tag_input.strip():
                st.error(t("planning.tag_required_error", default="Please select a dictionary tag or enter a custom tag."))
            else:
                tag_repo.create_task_tag(
                    TaskTag(
                        task_id=task_id,
                        tag_id=selected_tag_id,
                        free_tag=free_tag_input.strip() if free_tag_input.strip() else None,
                    )
                )
                st.toast(t("planning.toast_task_tag_attached", default="Tag attached to task!"), icon="🏷️")
                st.rerun()

    with col_btn_close:
        if st.button(t("planning.btn_close_dialog", default="Close"), key="btn_close_task_dialog"):
            st.session_state["modal_manage_task_tag"] = None
            st.rerun()


def render_planning_milestones(
    project_repo: ProjectRepository,
    milestone_repo: MilestoneRepository,
    tag_repo: Optional[TagRepository] = None,
) -> None:
    """Renders the Planning & Step Loader screen with interactive drag & drop and Plotly timeline."""
    if tag_repo is None:
        tag_repo = TagRepository(project_repo.db_path)

    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.2rem !important;
            padding-bottom: 1rem !important;
        }
        h1, h2, h3 {
            margin-top: 0 !important;
            margin-bottom: 0.25rem !important;
            padding-top: 0 !important;
        }
        div[data-testid="stVerticalBlock"] > div {
            margin-bottom: 0.25rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    df_projects = project_repo.get_all_projects()

    if df_projects.empty:
        st.info(t("master_data.dynamic_empty", default="No projects registered yet."))
        return

    proj_map = dict(zip(df_projects["id"], df_projects["name"]))

    # --------------------------------------------------------------------------
    # TOP CONTROL: Project Tag Filter & Projects Multi-Selector
    # --------------------------------------------------------------------------
    df_all_proj_tags = tag_repo.get_all_project_tags()
    available_tags_set: set[str] = set()
    if not df_all_proj_tags.empty:
        for _, r in df_all_proj_tags.iterrows():
            t_name = r.get("tag_name")
            f_name = r.get("free_tag")
            if pd.notna(t_name) and str(t_name).strip():
                available_tags_set.add(str(t_name).strip())
            if pd.notna(f_name) and str(f_name).strip():
                available_tags_set.add(str(f_name).strip())

    available_tags_list = sorted(list(available_tags_set))

    top_filter_col, top_sel_col = st.columns([2, 3])

    with top_filter_col:
        selected_tag_filters = st.multiselect(
            f"🏷️ {t('planning.filter_by_tags', default='Filter Projects by Tag')}",
            options=available_tags_list,
            default=[],
            help="Filter project list to projects assigned any of the chosen tags.",
            key="ms_planning_tag_filter",
        )

    # Filter projects based on tag selection if any
    if selected_tag_filters and not df_all_proj_tags.empty:
        matching_proj_ids = set()
        for _, r in df_all_proj_tags.iterrows():
            t_name = str(r.get("tag_name", "")).strip()
            f_name = str(r.get("free_tag", "")).strip()
            if (t_name and t_name in selected_tag_filters) or (f_name and f_name in selected_tag_filters):
                matching_proj_ids.add(int(r["project_id"]))

        df_filtered_projects = df_projects[df_projects["id"].isin(matching_proj_ids)]
        if df_filtered_projects.empty:
            st.warning(t("planning.no_projects_matching_tags", default="No projects match the selected tag filter."))
        else:
            df_projects = df_filtered_projects

    if df_projects.empty:
        st.info(t("planning.no_projects_available", default="No projects available with the current filter."))
        return

    all_proj_ids = df_projects["id"].tolist()

    with top_sel_col:
        multi_header_label = f"🔍 {t('planning.select_multi_proj', default='Select Projects to Display in Multi-Gantt')} ({len(df_projects)} projects found)"
        selected_projects = st.multiselect(
            multi_header_label,
            options=all_proj_ids,
            default=all_proj_ids[:10] if len(all_proj_ids) > 10 else all_proj_ids,
            format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
            key="ms_multi_projects",
        )
        if not selected_projects:
            selected_projects = all_proj_ids

    selected_id = selected_projects[0]

    # Modal Dialog triggers (Project Tags & Task Tags from contextual menus)
    proj_modal_id = st.session_state.pop("modal_manage_project_tag", None)
    if proj_modal_id:
        _manage_project_tags_dialog(int(proj_modal_id), proj_map.get(proj_modal_id, f"Project #{proj_modal_id}"), tag_repo)

    task_modal_info = st.session_state.pop("modal_manage_task_tag", None)
    if task_modal_info and isinstance(task_modal_info, dict):
        _manage_task_tags_dialog(int(task_modal_info["task_id"]), str(task_modal_info["task_name"]), tag_repo)

    # Fetch all project bounds and project tags for constraint evaluation and tooltips
    proj_tags_map = tag_repo.get_project_tags_by_project_ids([int(p) for p in selected_projects if str(p).isdigit()])
    all_projects_list = [
        {
            "id": str(r["id"]),
            "name": f"{r['name']}",
            "tags": proj_tags_map.get(int(r["id"]), []),
        }
        for _, r in df_projects.iterrows()
    ]
    project_bounds = milestone_repo.get_all_project_date_bounds()

    # Gather tasks and dependencies for active project(s) via batch queries
    combined_steps_df = milestone_repo.get_milestones_for_projects(selected_projects)
    if not combined_steps_df.empty:
        # In multi-project view, display strictly the clean project name without ID prefix
        combined_steps_df["project_name"] = combined_steps_df["project_id"].apply(
            lambda pid: proj_map.get(pid, str(pid))
        )
    raw_dependencies = milestone_repo.get_dependencies_for_projects(selected_projects)

    if combined_steps_df.empty:
        st.info(t("planning.no_steps_defined"))
    else:
        steps_records = combined_steps_df.to_dict(orient="records")
        raw_tasks = [
            {
                "id": int(row["id"]),
                "task_name": str(row["task_name"]),
                "start_date": str(row["start_date"]),
                "end_date": str(row["end_date"]),
                "phase": str(row.get("phase", "General")),
                "progress_pct": int(row.get("progress_pct", 0)),
                "description": str(row.get("description", "")) if pd.notna(row.get("description")) else "",
                "project_id": str(row.get("project_id", selected_id)),
                "project_name": str(row.get("project_name", "")),
            }
            for row in steps_records
        ]

        evaluated_deps, task_violations = MilestoneService.evaluate_constraints(
            raw_tasks, raw_dependencies, project_bounds
        )

        # Batch load tags for all tasks
        all_task_ids = [int(row["id"]) for row in steps_records]
        task_tags_map = tag_repo.get_task_tags_by_task_ids(all_task_ids)

        # Index evaluated dependencies by task_id in O(N)
        deps_by_task_id: dict[int, list[dict[str, Any]]] = {}
        for d in evaluated_deps:
            t_id = d.get("task_id")
            if t_id is not None:
                deps_by_task_id.setdefault(int(t_id), []).append(d)

        # Build gantt tasks payload in fast O(N)
        gantt_tasks = []
        for row in steps_records:
            tid = int(row["id"])
            task_deps = deps_by_task_id.get(tid, [])
            first_pred = task_deps[0]["predecessor_task_id"] if task_deps and task_deps[0].get("predecessor_task_id") else None
            dep_str = str(int(first_pred)) if first_pred is not None else ""

            gantt_tasks.append({
                "id": str(tid),
                "name": str(row["task_name"]),
                "start": str(row["start_date"]),
                "end": str(row["end_date"]),
                "progress": int(row.get("progress_pct", 0)),
                "description": str(row.get("description", "")) if pd.notna(row.get("description")) else "",
                "dependencies": dep_str,
                "dependenciesList": task_deps,
                "violations": task_violations.get(tid, []),
                "tags": task_tags_map.get(tid, []),
                "phase": str(row.get("phase", "General")),
                "project_id": str(row["project_id"]),
                "project_name": str(row["project_name"]),
                "custom_class": "bar-milestone" if row["start_date"] == row["end_date"] else "bar-step",
            })

        # Render custom drag-and-drop component with multi-dependency metadata and i18n
        cur_loc = get_current_locale()
        gantt_translations = get_section_catalog("gantt", cur_loc)
        widget_key = f"gantt_{len(selected_projects)}_{selected_id}_{cur_loc}"
        gantt_event = _interactive_gantt(
            tasks=gantt_tasks,
            all_projects=all_projects_list,
            project_id=selected_id,
            is_multi_project=True,
            translations=gantt_translations,
            key=widget_key,
        )

        # Handle bi-directional Drag & Drop changes from JS (deduplicated via nonce)
        if gantt_event and isinstance(gantt_event, dict):
            nonce = gantt_event.get("nonce")
            last_nonce = st.session_state.get("last_gantt_nonce")

            if nonce and nonce != last_nonce:
                st.session_state["last_gantt_nonce"] = nonce
                action = gantt_event.get("action")
                step_id = gantt_event.get("id")

                if action == "manage_project_tags":
                    p_id = gantt_event.get("project_id")
                    if p_id:
                        st.session_state["modal_manage_project_tag"] = int(p_id)
                        st.rerun()
                elif action == "edit_project_details":
                    p_id = gantt_event.get("project_id")
                    if p_id:
                        st.session_state["nav_redirect"] = PAGE_PROJECT_MASTER
                        st.session_state["target_edit_project_id"] = int(p_id)
                        st.rerun()
                elif action == "manage_task_tags" and step_id:
                    st.session_state["modal_manage_task_tag"] = {
                        "task_id": int(step_id),
                        "task_name": str(gantt_event.get("task_name", "")),
                        "project_id": str(gantt_event.get("project_id", "")),
                    }
                    st.rerun()
                elif action == "update_task_full" and step_id:
                    t_name = str(gantt_event.get("task_name", "")).strip()
                    t_phase = str(gantt_event.get("phase", "General")).strip()
                    t_start = str(gantt_event.get("start_date", "")).strip()
                    t_end = str(gantt_event.get("end_date", "")).strip()
                    t_prog = int(gantt_event.get("progress_pct", 0))
                    t_desc = str(gantt_event.get("description", "")).strip()
                    t_deps = gantt_event.get("dependencies")
                    if t_name and t_start and t_end:
                        milestone_repo.update_milestone(
                            milestone_id=int(step_id),
                            task_name=t_name,
                            phase=t_phase,
                            start_date=t_start,
                            end_date=t_end,
                            progress_pct=t_prog,
                            dependencies=t_deps,
                            description=t_desc,
                        )
                        st.toast(t("planning.toast_step_updated", name=t_name), icon="✏️")
                        st.rerun()
                elif action == "create_step_full":
                    t_proj = str(gantt_event.get("project_id", "")).strip() or selected_id
                    t_name = str(gantt_event.get("task_name", "")).strip()
                    t_phase = str(gantt_event.get("phase", "")).strip() or "General"
                    t_start = str(gantt_event.get("start_date", "")).strip()
                    t_end = str(gantt_event.get("end_date", "")).strip()
                    t_prog = int(gantt_event.get("progress_pct", 0))
                    t_desc = str(gantt_event.get("description", "")).strip()
                    t_deps = gantt_event.get("dependencies", [])

                    if t_name and t_start and t_end:
                        new_step_id = milestone_repo.create_milestone(
                            project_id=t_proj,
                            task_name=t_name,
                            phase=t_phase,
                            start_date=t_start,
                            end_date=t_end,
                            progress_pct=t_prog,
                            dependencies=t_deps,
                            description=t_desc,
                        )
                        st.toast(t("planning.toast_step_created", name=t_name, project_id=t_proj), icon="➕")
                        st.rerun()
                elif action == "update_dates" and step_id:
                    new_start = str(gantt_event.get("start_date", "")).strip()
                    new_end = str(gantt_event.get("end_date", "")).strip()
                    if new_start and new_end:
                        milestone_repo.update_dates(int(step_id), new_start, new_end)
                        st.toast(t("planning.toast_dates_updated", id=step_id, start=new_start, end=new_end), icon="📅")
                        st.rerun()
                elif action == "update_progress" and step_id:
                    new_prog = gantt_event.get("progress")
                    if new_prog is not None:
                        milestone_repo.update_progress(int(step_id), int(new_prog))
                        st.toast(t("planning.toast_progress_updated", id=step_id, progress=new_prog), icon="📊")
                        st.rerun()
                elif action == "delete_step" and step_id:
                    milestone_repo.delete_milestone(int(step_id))
                    st.toast(t("planning.toast_step_deleted", id=step_id), icon="🗑️")
                    st.rerun()

    # --------------------------------------------------------------------------
    # 2. CSV BULK STEP LOADER & EXPORTER
    # --------------------------------------------------------------------------
    st.divider()

    manage_project_id = st.selectbox(
        t("planning.csv_target_project", default="Select Target Project for CSV Bulk Loader"),
        options=df_projects["id"].tolist(),
        format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
        key="sb_manage_target_project",
    )

    df_steps = milestone_repo.get_milestones_by_project(manage_project_id)

    with st.expander(t("planning.csv_section_title"), expanded=False):
        st.subheader(f"{t('planning.csv_section_title')} ({manage_project_id})")
        col_exp, col_imp = st.columns(2)
        with col_exp:
            st.write(f"##### {t('planning.csv_export_title', default='Export Schedule Template')}")
            template_csv = MilestoneService.get_csv_template()
            st.download_button(
                label=t("planning.csv_download_template"),
                data=template_csv,
                file_name="steps_schedule_template.csv",
                mime="text/csv",
            )

        with col_imp:
            st.write(f"##### {t('planning.csv_import_title', default='Bulk Import Steps')}")
            uploaded_file = st.file_uploader(t("planning.csv_upload_label"), type=["csv"], key="uploader_steps")
            if uploaded_file is not None:
                try:
                    steps_payload = MilestoneService.parse_csv(uploaded_file, manage_project_id)
                    st.dataframe(pd.DataFrame(steps_payload).head(), width="stretch")
                    if st.button(t("planning.btn_import_csv")):
                        count = milestone_repo.bulk_create_milestones(steps_payload)
                        st.success(t("planning.csv_import_success", count=count, project_id=manage_project_id, default=f"Successfully imported {count} steps to {manage_project_id}!"))
                        st.rerun()
                except ValueError as val_err:
                    st.error(str(val_err))
                except Exception as e:
                    st.error(f"Error parsing CSV: {e}")
