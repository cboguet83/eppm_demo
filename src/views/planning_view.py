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
                    t_deps = gantt_event.get("dependencies", [])

                    if t_name and t_start and t_end:
                        new_step_id = milestone_repo.create_milestone(
                            project_id=t_proj,
                            task_name=t_name,
                            phase=t_phase,
                            start_date=t_start,
                            end_date=t_end,
                            progress_pct=t_prog,
                        )
                        if new_step_id and t_deps:
                            for dep in t_deps:
                                milestone_repo.add_dependency(
                                    task_id=new_step_id,
                                    predecessor_task_id=dep.get("predecessor_task_id"),
                                    predecessor_project_id=dep.get("predecessor_project_id"),
                                    link_type=dep.get("link_type", "FS"),
                                    lag_days=dep.get("lag_days", 0),
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
    # 2. MANAGE STEPS: ADD, EDIT, OR BULK IMPORT
    # --------------------------------------------------------------------------
    st.divider()

    if enable_multi_project:
        manage_project_id = st.selectbox(
            "Select Target Project to Manage Steps (Add / Edit / Import)",
            options=df_projects["id"].tolist(),
            format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
            key="sb_manage_target_project",
        )
    else:
        manage_project_id = selected_id

    df_steps = milestone_repo.get_milestones_by_project(manage_project_id)

    tab_add, tab_edit, tab_import = st.tabs([
        "➕ Add Step / Milestone",
        "✏️ Edit Existing Step",
        "📥 CSV Bulk Loader & Exporter",
    ])

    # --------------------------------------------------------------------------
    # TAB A: ADD STEP
    # --------------------------------------------------------------------------
    with tab_add:
        st.subheader(f"Add Step or Milestone ({manage_project_id})")

        today = datetime.date.today()
        if "step_start_date" not in st.session_state:
            st.session_state["step_start_date"] = today
        if "step_end_date" not in st.session_state:
            st.session_state["step_end_date"] = st.session_state["step_start_date"]

        def _sync_step_dates() -> None:
            """Automatically synchronizes the end date to match the newly selected start date."""
            st.session_state["step_end_date"] = st.session_state["step_start_date"]

        col_t1, col_t2 = st.columns(2)
        task_name = col_t1.text_input(
            "Step / Task Name *",
            placeholder="e.g. UAT Validation or Go-Live Milestone",
            key="input_step_name",
        )
        phase_name = col_t2.text_input("Phase / Category", value="Phase 1 - Build", key="input_step_phase")

        col_d1, col_d2, col_d3 = st.columns(3)
        start_d = col_d1.date_input(
            "Start Date *",
            key="step_start_date",
            on_change=_sync_step_dates,
        )
        end_d = col_d2.date_input(
            "End Date * (Set equal to Start Date for Milestone)",
            key="step_end_date",
            min_value=st.session_state["step_start_date"],
            help="Defaults to Start Date (Milestone). Change to a later date for a duration task.",
        )
        prog_val = col_d3.slider("Progress (%)", min_value=0, max_value=100, value=0, key="input_step_progress")

        # Multi-Predecessors Configuration for New Step
        add_deps_key = f"add_deps_{manage_project_id}"
        if add_deps_key not in st.session_state:
            st.session_state[add_deps_key] = []

        cur_add_deps = st.session_state[add_deps_key]
        st.write("##### 🔗 Predecessors & Dependencies")

        if not cur_add_deps:
            st.caption("No predecessors added yet for this step. Use the builder below to add predecessors.")
        else:
            for idx, dep in enumerate(cur_add_deps):
                c_info, c_del = st.columns([5, 1])
                p_proj = dep.get("predecessor_project_id")
                p_task = dep.get("predecessor_task_id")
                l_type = dep.get("link_type", "FS")
                l_lag = dep.get("lag_days", 0)
                lag_str = f"{'+' if l_lag >= 0 else ''}{l_lag}d offset"

                if p_proj and not p_task:
                    target_label = f"🌐 External Project [{p_proj}] (Whole Project)"
                elif p_proj and p_task:
                    target_label = f"🌐 External Project [{p_proj}] > Step #{p_task}"
                else:
                    step_match = df_steps[df_steps["id"] == p_task] if not df_steps.empty else None
                    step_name = step_match["task_name"].iloc[0] if step_match is not None and not step_match.empty else f"Step #{p_task}"
                    target_label = f"📌 {step_name} (Internal)"

                c_info.markdown(f"**{idx + 1}.** {target_label} &bull; `{l_type}` &bull; `{lag_str}`")
                if c_del.button("🗑️ Remove", key=f"btn_del_add_dep_{idx}"):
                    st.session_state[add_deps_key].pop(idx)
                    st.rerun()

        with st.expander("➕ Add a Predecessor Link", expanded=(len(cur_add_deps) == 0)):
            is_ext = st.checkbox("Link to an external project / task", key="chk_add_ext_pred")
            all_proj_df = df_projects
            col_p1, col_p2, col_p3 = st.columns([2, 1, 1])

            builder_target: tuple[Optional[str], Optional[int], Optional[str]] = (None, None, None)

            if is_ext:
                other_projs = [str(p) for p in all_proj_df["id"].tolist() if str(p) != manage_project_id]
                if other_projs:
                    ext_proj_sel = col_p1.selectbox(
                        "External Project",
                        options=other_projs,
                        format_func=lambda x: f"{x} - {all_proj_df[all_proj_df['id']==x]['name'].iloc[0]}",
                        key="sel_ext_proj_add",
                    )
                    ext_steps_df = milestone_repo.get_milestones_by_project(ext_proj_sel)
                    ext_step_options: list[Optional[int]] = [None]
                    ext_step_labels: dict[Optional[int], str] = {None: "(Whole Project - leave blank)"}
                    if not ext_steps_df.empty:
                        for _, s in ext_steps_df.iterrows():
                            sid = int(s["id"])
                            ext_step_options.append(sid)
                            ext_step_labels[sid] = f"ID {sid} - {s['task_name']} ({s['start_date']})"

                    ext_step_id = col_p1.selectbox(
                        "Step (leave blank to link the whole project)",
                        options=ext_step_options,
                        index=0,
                        format_func=lambda x: ext_step_labels.get(x, "Unknown"),
                        key="sel_ext_step_add",
                    )
                    if ext_step_id is not None:
                        builder_target = ("TASK", int(ext_step_id), ext_proj_sel)
                    else:
                        builder_target = ("PROJ", None, ext_proj_sel)
                else:
                    col_p1.info("No other projects available.")
            else:
                if not df_steps.empty:
                    pred_options = df_steps["id"].tolist()
                    pred_labels = {int(s["id"]): f"ID {int(s['id'])} - {s['task_name']} ({s['start_date']})" for _, s in df_steps.iterrows()}
                    selected_pred = col_p1.selectbox(
                        "Internal Predecessor Step",
                        options=pred_options,
                        format_func=lambda x: pred_labels.get(x, "Unknown"),
                        key="input_step_pred",
                    )
                    builder_target = ("TASK", int(selected_pred), None)
                else:
                    col_p1.info("No existing steps in this project yet.")

            link_type_sel = col_p2.selectbox(
                "Link Type",
                options=["FS", "FF", "SS", "SF"],
                format_func=lambda x: {"FS": "Finish-to-Start (FS)", "FF": "Finish-to-Finish (FF)", "SS": "Start-to-Start (SS)", "SF": "Start-to-Finish (SF)"}.get(x, x),
                key="sel_link_type_add",
            )
            lag_offset_val = col_p3.number_input("Offset (days)", min_value=-365, max_value=365, value=0, step=1, key="num_lag_offset_add")

            if st.button("➕ Add Predecessor to List", key="btn_add_to_list_add"):
                if builder_target[0] is not None:
                    new_item = {
                        "predecessor_task_id": builder_target[1],
                        "predecessor_project_id": builder_target[2],
                        "link_type": link_type_sel,
                        "lag_days": int(lag_offset_val),
                    }
                    exists = any(
                        d.get("predecessor_task_id") == new_item["predecessor_task_id"] and
                        d.get("predecessor_project_id") == new_item["predecessor_project_id"]
                        for d in st.session_state[add_deps_key]
                    )
                    if not exists:
                        st.session_state[add_deps_key].append(new_item)
                        st.rerun()
                    else:
                        st.warning("This predecessor is already in the list.")

        st.divider()
        if st.button("➕ Save Step", width="stretch", key="btn_submit_step"):
            clean_task = task_name.strip()
            if not clean_task:
                st.error("Step Name is required.")
            elif end_d < start_d:
                st.error("End Date must be greater than or equal to Start Date.")
            else:
                saved_deps = list(st.session_state.get(add_deps_key, []))
                milestone_repo.create_milestone(
                    project_id=manage_project_id,
                    task_name=clean_task,
                    phase=phase_name.strip() if phase_name.strip() else "General",
                    start_date=start_d.isoformat(),
                    end_date=end_d.isoformat(),
                    progress_pct=int(prog_val),
                    dependencies=saved_deps if saved_deps else None,
                )
                st.session_state[add_deps_key] = []
                if start_d == end_d:
                    st.success(f"Milestone '{clean_task}' (Diamond) added successfully to Project {manage_project_id}!")
                else:
                    st.success(f"Step '{clean_task}' added successfully to Project {manage_project_id}!")
                st.rerun()

    # --------------------------------------------------------------------------
    # TAB B: EDIT STEP
    # --------------------------------------------------------------------------
    with tab_edit:
        st.subheader(f"Edit Existing Step or Milestone ({manage_project_id})")
        if df_steps.empty:
            st.info("No steps available to edit.")
        else:
            edit_step_id = st.selectbox(
                "Select Step to Edit",
                options=df_steps["id"].tolist(),
                format_func=lambda x: f"ID {x} - {df_steps[df_steps['id'] == x]['task_name'].iloc[0]} ({df_steps[df_steps['id'] == x]['phase'].iloc[0]})",
                key="sb_edit_step_choice",
            )
            curr_step = df_steps[df_steps["id"] == edit_step_id].iloc[0]

            curr_start = pd.to_datetime(curr_step["start_date"]).date()
            curr_end = pd.to_datetime(curr_step["end_date"]).date()

            # Session State cache for multi-predecessors editing
            edit_deps_key = f"edit_deps_{edit_step_id}"
            if edit_deps_key not in st.session_state or st.session_state.get("loaded_edit_step_id") != edit_step_id:
                st.session_state[edit_deps_key] = milestone_repo.get_task_dependencies(int(edit_step_id))
                st.session_state["loaded_edit_step_id"] = edit_step_id

            col_e1, col_e2 = st.columns(2)
            edit_name = col_e1.text_input("Step / Task Name *", value=str(curr_step["task_name"]), key=f"in_name_{edit_step_id}")
            edit_phase = col_e2.text_input("Phase / Category", value=str(curr_step["phase"]), key=f"in_phase_{edit_step_id}")

            col_ed1, col_ed2, col_ed3 = st.columns(3)
            edit_start = col_ed1.date_input("Start Date *", value=curr_start, key=f"in_start_{edit_step_id}")
            edit_end = col_ed2.date_input(
                "End Date * (Set equal to Start Date for Milestone)",
                value=curr_end,
                min_value=edit_start,
                key=f"in_end_{edit_step_id}",
            )
            edit_prog = col_ed3.slider(
                "Progress (%)",
                min_value=0,
                max_value=100,
                value=int(curr_step["progress_pct"]),
                key=f"in_prog_{edit_step_id}",
            )

            # Multi-Predecessors List for Edited Step
            st.write("##### 🔗 Configured Predecessors")
            cur_edit_deps = st.session_state.get(edit_deps_key, [])

            if not cur_edit_deps:
                st.caption("No predecessors configured for this step.")
            else:
                for idx, dep in enumerate(cur_edit_deps):
                    c_info, c_del = st.columns([5, 1])
                    p_proj = dep.get("predecessor_project_id")
                    p_task = dep.get("predecessor_task_id")
                    l_type = dep.get("link_type", "FS")
                    l_lag = dep.get("lag_days", 0)
                    lag_str = f"{'+' if l_lag >= 0 else ''}{l_lag}d offset"

                    if p_proj and not p_task:
                        target_label = f"🌐 External Project [{p_proj}] (Whole Project)"
                    elif p_proj and p_task:
                        target_label = f"🌐 External Project [{p_proj}] > Step #{p_task}"
                    else:
                        step_match = df_steps[df_steps["id"] == p_task] if not df_steps.empty else None
                        step_name = step_match["task_name"].iloc[0] if step_match is not None and not step_match.empty else f"Step #{p_task}"
                        target_label = f"📌 {step_name} (Internal)"

                    c_info.markdown(f"**{idx + 1}.** {target_label} &bull; `{l_type}` &bull; `{lag_str}`")
                    if c_del.button("🗑️ Remove", key=f"btn_del_edit_dep_{edit_step_id}_{idx}"):
                        st.session_state[edit_deps_key].pop(idx)
                        st.rerun()

            # Predecessor Builder for Edited Step
            with st.expander("➕ Add a Predecessor Link", expanded=(len(cur_edit_deps) == 0)):
                is_edit_ext = st.checkbox("Link to an external project / task", key=f"chk_edit_ext_{edit_step_id}")
                all_proj_df = df_projects
                col_pe1, col_pe2, col_pe3 = st.columns([2, 1, 1])
                edit_builder_target: tuple[Optional[str], Optional[int], Optional[str]] = (None, None, None)

                if is_edit_ext:
                    other_projs = [str(p) for p in all_proj_df["id"].tolist() if str(p) != manage_project_id]
                    if other_projs:
                        edit_ext_proj = col_pe1.selectbox(
                            "External Project",
                            options=other_projs,
                            format_func=lambda x: f"{x} - {all_proj_df[all_proj_df['id']==x]['name'].iloc[0]}",
                            key=f"sel_ext_proj_edit_{edit_step_id}",
                        )
                        ext_steps_df = milestone_repo.get_milestones_by_project(edit_ext_proj)
                        ext_step_options = [None]
                        ext_step_labels = {None: "(Whole Project - leave blank)"}
                        if not ext_steps_df.empty:
                            for _, s in ext_steps_df.iterrows():
                                sid = int(s["id"])
                                ext_step_options.append(sid)
                                ext_step_labels[sid] = f"ID {sid} - {s['task_name']} ({s['start_date']})"

                        edit_ext_step_id = col_pe1.selectbox(
                            "Step (leave blank to link the whole project)",
                            options=ext_step_options,
                            index=0,
                            format_func=lambda x: ext_step_labels.get(x, "Unknown"),
                            key=f"sel_ext_step_edit_{edit_step_id}",
                        )
                        if edit_ext_step_id is not None:
                            edit_builder_target = ("TASK", int(edit_ext_step_id), edit_ext_proj)
                        else:
                            edit_builder_target = ("PROJ", None, edit_ext_proj)
                    else:
                        col_pe1.info("No other projects available.")
                else:
                    # Exclude self
                    avail_steps = [s for _, s in df_steps.iterrows() if int(s["id"]) != int(edit_step_id)]
                    if avail_steps:
                        avail_ids = [int(s["id"]) for s in avail_steps]
                        avail_labels = {int(s["id"]): f"ID {int(s['id'])} - {s['task_name']} ({s['start_date']})" for s in avail_steps}
                        edit_pred = col_pe1.selectbox(
                            "Internal Predecessor Step",
                            options=avail_ids,
                            format_func=lambda x: avail_labels.get(x, "Unknown"),
                            key=f"sel_int_pred_edit_{edit_step_id}",
                        )
                        edit_builder_target = ("TASK", int(edit_pred), None)
                    else:
                        col_pe1.info("No other steps in this project.")

                cur_ltype_opts = ["FS", "FF", "SS", "SF"]
                edit_ltype = col_pe2.selectbox(
                    "Link Type",
                    options=cur_ltype_opts,
                    format_func=lambda x: {"FS": "Finish-to-Start (FS)", "FF": "Finish-to-Finish (FF)", "SS": "Start-to-Start (SS)", "SF": "Start-to-Finish (SF)"}.get(x, x),
                    key=f"sel_ltype_edit_{edit_step_id}",
                )
                edit_lag = col_pe3.number_input(
                    "Offset (days)",
                    min_value=-365,
                    max_value=365,
                    value=0,
                    step=1,
                    key=f"num_lag_edit_{edit_step_id}",
                )

                if st.button("➕ Add Predecessor to List", key=f"btn_add_to_list_edit_{edit_step_id}"):
                    if edit_builder_target[0] is not None:
                        new_item = {
                            "predecessor_task_id": edit_builder_target[1],
                            "predecessor_project_id": edit_builder_target[2],
                            "link_type": edit_ltype,
                            "lag_days": int(edit_lag),
                        }
                        exists = any(
                            d.get("predecessor_task_id") == new_item["predecessor_task_id"] and
                            d.get("predecessor_project_id") == new_item["predecessor_project_id"]
                            for d in st.session_state[edit_deps_key]
                        )
                        if not exists:
                            st.session_state[edit_deps_key].append(new_item)
                            st.rerun()
                        else:
                            st.warning("This predecessor is already in the list.")

            st.divider()
            btn_update_step = st.button("💾 Update Step Details", width="stretch", key=f"btn_submit_edit_{edit_step_id}")
            if btn_update_step:
                clean_edit_name = edit_name.strip()
                if not clean_edit_name:
                    st.error("Step Name is required.")
                elif edit_end < edit_start:
                    st.error("End Date must be greater than or equal to Start Date.")
                else:
                    final_deps = list(st.session_state.get(edit_deps_key, []))
                    milestone_repo.update_milestone(
                        milestone_id=edit_step_id,
                        task_name=clean_edit_name,
                        phase=edit_phase.strip() if edit_phase.strip() else "General",
                        start_date=edit_start.isoformat(),
                        end_date=edit_end.isoformat(),
                        progress_pct=int(edit_prog),
                        dependencies=final_deps,
                    )
                    st.session_state.pop(edit_deps_key, None)
                    st.success(f"Step '{clean_edit_name}' updated successfully with {len(final_deps)} predecessor(s)!")
                    st.rerun()

    # --------------------------------------------------------------------------
    # TAB C: CSV BULK LOADER & EXPORTER
    # --------------------------------------------------------------------------
    with tab_import:
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

    # --------------------------------------------------------------------------
    # 3. STEPS & MILESTONES REGISTER TABLE
    # --------------------------------------------------------------------------
    if not df_steps.empty:
        st.divider()
        st.subheader("📋 Steps & Milestones Register")
        display_df = df_steps.copy()
        display_df["type"] = display_df.apply(
            lambda r: "🔷 Milestone" if r["start_date"] == r["end_date"] else "⏱️ Step",
            axis=1,
        )
        display_df["predecessor_display"] = display_df["predecessor_name"].fillna("None")

        st.dataframe(
            display_df[[
                "id",
                "type",
                "task_name",
                "phase",
                "start_date",
                "end_date",
                "progress_pct",
                "predecessor_display",
            ]],
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "type": st.column_config.TextColumn("Type", width="small"),
                "task_name": st.column_config.TextColumn("Step / Milestone Name", width="medium"),
                "phase": st.column_config.TextColumn("Phase", width="small"),
                "start_date": st.column_config.DateColumn("Start Date"),
                "end_date": st.column_config.DateColumn("End Date"),
                "progress_pct": st.column_config.ProgressColumn("Progress", min_value=0, max_value=100, format="%d%%"),
                "predecessor_display": st.column_config.TextColumn("Predecessor", width="medium"),
            },
            width="stretch",
            hide_index=True,
        )

        col_act1, col_act2 = st.columns([3, 1])
        del_step_id = col_act1.selectbox(
            "Select Step to Delete",
            options=df_steps["id"].tolist(),
            format_func=lambda x: f"ID {x} - {df_steps[df_steps['id'] == x]['task_name'].iloc[0]}",
            key="sb_del_step",
        )
        if col_act2.button("🗑️ Delete Step"):
            milestone_repo.delete_milestone(del_step_id)
            st.success("Step deleted.")
            st.rerun()
