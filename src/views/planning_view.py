"""Screen 4: Planning & Step Loader View (Interactive Drag & Drop Gantt and Plotly Roadmap)."""

import datetime
import os
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.project_repo import ProjectRepository
from src.services.milestone_service import MilestoneService

# Declare Frappe Gantt Custom Component
_COMPONENT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "components",
    "gantt",
)
_interactive_gantt = components.declare_component("interactive_gantt", path=_COMPONENT_PATH)


def render_planning_milestones(
    project_repo: ProjectRepository,
    milestone_repo: MilestoneRepository,
) -> None:
    """Renders the Planning & Step Loader screen with interactive drag & drop and Plotly timeline."""
    st.header("📅 Planning & Step Loader")

    df_projects = project_repo.get_all_projects()

    if df_projects.empty:
        st.info("No projects registered yet. Please create a project first in 'Project Master Data'.")
        return

    proj_map = dict(zip(df_projects["id"], df_projects["name"]))

    # Top Control: Project Selection & Multi-Project View Toggle
    top_col1, top_col2 = st.columns([3, 2])
    enable_multi_project = top_col2.checkbox(
        "🌐 Multi-Project Display",
        value=False,
        help="View all projects in a unified timeline with tasks grouped under their respective project.",
        key="chk_multi_project_display",
    )

    if enable_multi_project:
        all_proj_ids = df_projects["id"].tolist()
        filter_mode = top_col1.radio(
            "Filter Scope",
            options=["🌐 All Projects", "🔍 Select Specific Projects"],
            horizontal=True,
            key="rg_multi_filter_mode",
        )
        if filter_mode == "🔍 Select Specific Projects":
            selected_projects = top_col1.multiselect(
                "Select Projects to Display",
                options=all_proj_ids,
                default=all_proj_ids[:10] if len(all_proj_ids) > 10 else all_proj_ids,
                format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
                key="ms_multi_projects",
            )
            if not selected_projects:
                selected_projects = all_proj_ids
        else:
            selected_projects = all_proj_ids
        selected_id = selected_projects[0]

        sub_df = df_projects[df_projects["id"].isin(selected_projects)]
        col1, col2, col3 = st.columns(3)
        col1.metric("Selected Projects", f"{len(sub_df)} / {len(df_projects)}")
        col2.metric("Total Planned Budget", f"${float(sub_df['planned_budget'].sum()):,.2f}" if not sub_df.empty else "$0.00")
        col3.metric("Total Actual Spend", f"${float(sub_df['actual_budget'].sum()):,.2f}" if not sub_df.empty else "$0.00")
    else:
        selected_id = top_col1.selectbox(
            "Select Project to View / Manage Schedule",
            options=df_projects["id"].tolist(),
            format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
            key="sb_single_project_choice",
        )
        selected_projects = [selected_id]

        proj_info = df_projects[df_projects["id"] == selected_id].iloc[0]
        col1, col2, col3 = st.columns(3)
        col1.metric("Status", str(proj_info["status"]))
        col2.metric("Planned Budget", f"${float(proj_info['planned_budget']):,.2f}")
        col3.metric("Actual Spend", f"${float(proj_info['actual_budget']):,.2f}")

    st.divider()

    # --------------------------------------------------------------------------
    # 1. TIMELINE VISUALIZATION (INTERACTIVE DRAG & DROP GANTT)
    # --------------------------------------------------------------------------
    if enable_multi_project:
        st.subheader(f"🌐 Multi-Project Master Timeline ({len(selected_projects)} Projects)")
    else:
        st.subheader(f"Timeline Schedule: {selected_id}")

    # Fetch all project bounds for constraint evaluation in fast batch queries
    all_projects_list = [{"id": str(r["id"]), "name": f"{r['id']} - {r['name']}"} for _, r in df_projects.iterrows()]
    project_bounds = milestone_repo.get_all_project_date_bounds()

    # Gather tasks and dependencies for active project(s) via batch queries
    combined_steps_df = milestone_repo.get_milestones_for_projects(selected_projects)
    if not combined_steps_df.empty:
        combined_steps_df["project_name"] = combined_steps_df["project_id"].apply(
            lambda pid: f"{pid} - {proj_map.get(pid, '')}"
        )
    raw_dependencies = milestone_repo.get_dependencies_for_projects(selected_projects)

    if combined_steps_df.empty:
        st.info("No steps defined for the selected project(s) yet. Add steps below or upload a schedule CSV.")
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
                "phase": str(row.get("phase", "General")),
                "project_id": str(row["project_id"]),
                "project_name": str(row["project_name"]),
                "custom_class": "bar-milestone" if row["start_date"] == row["end_date"] else "bar-step",
            })

        # Render custom drag-and-drop component with multi-dependency metadata
        widget_key = f"gantt_widget_{len(selected_projects)}_{selected_id}" if enable_multi_project else f"gantt_widget_{selected_id}"
        gantt_event = _interactive_gantt(
            tasks=gantt_tasks,
            all_projects=all_projects_list,
            project_id=selected_id,
            is_multi_project=enable_multi_project,
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

                if action == "update_task_full" and step_id:
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
                        st.toast(f"Updated Step: {t_name}", icon="✏️")
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
                        st.toast(f"Created Step: {t_name} in Project {t_proj}", icon="➕")
                        st.rerun()
                elif action == "update_dates" and step_id:
                    new_start = str(gantt_event.get("start_date", "")).strip()
                    new_end = str(gantt_event.get("end_date", "")).strip()
                    if new_start and new_end:
                        milestone_repo.update_dates(int(step_id), new_start, new_end)
                        st.toast(f"Updated dates for Step #{step_id}: {new_start} → {new_end}", icon="📅")
                        st.rerun()
                elif action == "update_progress" and step_id:
                    new_prog = gantt_event.get("progress")
                    if new_prog is not None:
                        milestone_repo.update_progress(int(step_id), int(new_prog))
                        st.toast(f"Updated progress for Step #{step_id}: {new_prog}%", icon="📊")
                        st.rerun()
                elif action == "delete_step" and step_id:
                    milestone_repo.delete_milestone(int(step_id))
                    st.toast(f"Deleted Step #{step_id}", icon="🗑️")
                    st.rerun()

    # --------------------------------------------------------------------------
    # 2. CSV BULK STEP LOADER & EXPORTER
    # --------------------------------------------------------------------------
    st.divider()

    if enable_multi_project:
        manage_project_id = st.selectbox(
            "Select Target Project for CSV Bulk Loader",
            options=df_projects["id"].tolist(),
            format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
            key="sb_manage_target_project",
        )
    else:
        manage_project_id = selected_id

    df_steps = milestone_repo.get_milestones_by_project(manage_project_id)

    with st.expander("📥 CSV Bulk Step Loader & Exporter", expanded=False):
        st.subheader(f"CSV Bulk Step Loader & Exporter ({manage_project_id})")
        col_exp, col_imp = st.columns(2)
        with col_exp:
            st.write("##### Export Schedule Template")
            template_csv = MilestoneService.get_csv_template()
            st.download_button(
                label="📄 Download CSV Template",
                data=template_csv,
                file_name="steps_schedule_template.csv",
                mime="text/csv",
            )

        with col_imp:
            st.write("##### Bulk Import Steps")
            uploaded_file = st.file_uploader("Upload Steps CSV", type=["csv"], key="uploader_steps")
            if uploaded_file is not None:
                try:
                    steps_payload = MilestoneService.parse_csv(uploaded_file, manage_project_id)
                    st.dataframe(pd.DataFrame(steps_payload).head(), width="stretch")
                    if st.button("🚀 Import and Save Steps"):
                        count = milestone_repo.bulk_create_milestones(steps_payload)
                        st.success(f"Successfully imported {count} steps to {manage_project_id}!")
                        st.rerun()
                except ValueError as val_err:
                    st.error(str(val_err))
                except Exception as e:
                    st.error(f"Error parsing CSV: {e}")


