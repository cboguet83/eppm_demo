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
    selected_id = st.selectbox(
        "Select Project to View / Manage Schedule",
        options=df_projects["id"].tolist(),
        format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
    )

    proj_info = df_projects[df_projects["id"] == selected_id].iloc[0]
    col1, col2, col3 = st.columns(3)
    col1.metric("Status", str(proj_info["status"]))
    col2.metric("Planned Budget", f"${float(proj_info['planned_budget']):,.2f}")
    col3.metric("Actual Spend", f"${float(proj_info['actual_budget']):,.2f}")

    st.divider()

    df_steps = milestone_repo.get_milestones_by_project(selected_id)

    # --------------------------------------------------------------------------
    # 1. TIMELINE VISUALIZATION (INTERACTIVE DRAG & DROP GANTT OR PLOTLY ROADMAP)
    # --------------------------------------------------------------------------
    st.subheader(f"Timeline Schedule: {selected_id}")

    if df_steps.empty:
        st.info("No steps defined for this project yet. Add steps below or upload a schedule CSV.")
    else:
        chart_mode = st.radio(
            "Timeline Mode",
            ["🖐️ Interactive Drag & Drop Gantt", "📈 Plotly Dependency Roadmap"],
            horizontal=True,
            key="gantt_mode_toggle",
        )

        if chart_mode == "🖐️ Interactive Drag & Drop Gantt":
            # Convert steps into Frappe Gantt tasks payload
            gantt_tasks = []
            for _, row in df_steps.iterrows():
                dep_str = str(int(row["predecessor_id"])) if pd.notna(row.get("predecessor_id")) else ""
                gantt_tasks.append({
                    "id": str(int(row["id"])),
                    "name": str(row["task_name"]),
                    "start": str(row["start_date"]),
                    "end": str(row["end_date"]),
                    "progress": int(row.get("progress_pct", 0)),
                    "dependencies": dep_str,
                    "phase": str(row.get("phase", "General")),
                    "custom_class": "bar-milestone" if row["start_date"] == row["end_date"] else "bar-step",
                })

            # Render custom drag-and-drop component
            gantt_event = _interactive_gantt(tasks=gantt_tasks, key=f"gantt_widget_{selected_id}")

            # Handle bi-directional Drag & Drop changes from JS (deduplicated via nonce)
            if gantt_event and isinstance(gantt_event, dict):
                nonce = gantt_event.get("nonce")
                last_nonce = st.session_state.get("last_gantt_nonce")

                if nonce and nonce != last_nonce:
                    st.session_state["last_gantt_nonce"] = nonce
                    action = gantt_event.get("action")
                    step_id = gantt_event.get("id")

                    if action == "update_dates" and step_id:
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

        else:
            # Render Plotly Gantt with squared orthogonal dependency arrows and diamond milestones
            df_plot = df_steps.copy()
            df_plot["start_dt"] = pd.to_datetime(df_plot["start_date"])
            df_plot["end_dt"] = pd.to_datetime(df_plot["end_date"])
            df_plot["is_milestone"] = df_plot["start_date"] == df_plot["end_date"]
            df_plot["bar_end_dt"] = df_plot.apply(
                lambda r: r["end_dt"] + pd.Timedelta(hours=12) if r["is_milestone"] else r["end_dt"],
                axis=1,
            )

            df_bars = df_plot[~df_plot["is_milestone"]].copy()
            if not df_bars.empty:
                fig = px.timeline(
                    df_bars,
                    x_start="start_dt",
                    x_end="end_dt",
                    y="task_name",
                    color="phase",
                    hover_data=["progress_pct"],
                    title=f"Schedule Roadmap — {proj_info['name']}",
                    template="plotly_white",
                )
            else:
                fig = px.timeline(
                    df_plot,
                    x_start="start_dt",
                    x_end="bar_end_dt",
                    y="task_name",
                    color="phase",
                    hover_data=["progress_pct"],
                    title=f"Schedule Roadmap — {proj_info['name']}",
                    template="plotly_white",
                )

            # Overlay diamond shapes for milestones (start_date == end_date)
            df_milestones = df_plot[df_plot["is_milestone"]]
            if not df_milestones.empty:
                fig.add_trace(
                    go.Scatter(
                        x=df_milestones["start_dt"],
                        y=df_milestones["task_name"],
                        mode="markers+text",
                        marker=dict(
                            symbol="diamond",
                            size=18,
                            color="#DC2626",
                            line=dict(width=2, color="#7F1D1D"),
                        ),
                        name="🔷 Milestones (Key Dates)",
                        text=df_milestones["task_name"],
                        textposition="middle right",
                        hovertemplate="<b>🔷 Milestone: %{y}</b><br>Date: %{x|%Y-%m-%d}<extra></extra>",
                    )
                )

            # Draw squared dependency links (strictly horizontal & vertical segments)
            min_date = df_plot["start_dt"].min()
            max_date = df_plot["end_dt"].max()
            time_span = max(pd.Timedelta(days=7), max_date - min_date)
            step_offset = time_span * 0.02

            pred_map = {row["id"]: row for _, row in df_plot.iterrows()}
            for _, row in df_plot.iterrows():
                pred_id = row.get("predecessor_id")
                if pd.notna(pred_id) and pred_id in pred_map:
                    pred_row = pred_map[pred_id]
                    p_end = pred_row["end_dt"]
                    s_start = row["start_dt"]
                    p_y = pred_row["task_name"]
                    s_y = row["task_name"]

                    if s_start > p_end:
                        mid_x = p_end + (s_start - p_end) / 2
                        route_x = [p_end, mid_x, mid_x, s_start]
                        route_y = [p_y, p_y, s_y, s_y]
                        arrow_ax = mid_x
                    else:
                        elbow_x = p_end + step_offset
                        route_x = [p_end, elbow_x, elbow_x, s_start]
                        route_y = [p_y, p_y, s_y, s_y]
                        arrow_ax = elbow_x

                    fig.add_trace(
                        go.Scatter(
                            x=route_x,
                            y=route_y,
                            mode="lines",
                            line=dict(color="#2563EB", width=2),
                            hoverinfo="skip",
                            showlegend=False,
                        )
                    )

                    fig.add_annotation(
                        x=s_start,
                        y=s_y,
                        ax=s_start - pd.Timedelta(hours=12) if s_start >= arrow_ax else s_start + pd.Timedelta(hours=12),
                        ay=s_y,
                        xref="x",
                        yref="y",
                        axref="x",
                        ayref="y",
                        showarrow=True,
                        arrowhead=2,
                        arrowsize=1.2,
                        arrowwidth=2,
                        arrowcolor="#2563EB",
                    )

            fig.update_yaxes(autorange="reversed")
            fig.update_layout(
                height=max(380, 50 * len(df_plot) + 120),
                margin=dict(l=20, r=20, t=40, b=20),
                xaxis_title="Timeline Date",
                yaxis_title="Steps & Milestones",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, width="stretch")

    # --------------------------------------------------------------------------
    # 2. MANAGE STEPS: ADD, EDIT, OR BULK IMPORT
    # --------------------------------------------------------------------------
    st.divider()
    tab_add, tab_edit, tab_import = st.tabs([
        "➕ Add Step / Milestone",
        "✏️ Edit Existing Step",
        "📥 CSV Bulk Loader & Exporter",
    ])

    # --------------------------------------------------------------------------
    # TAB A: ADD STEP
    # --------------------------------------------------------------------------
    with tab_add:
        st.subheader("Add Step or Milestone")

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

        # Predecessor Selection
        pred_options: list[Optional[int]] = [None]
        pred_labels: dict[Optional[int], str] = {None: "(None / Independent)"}
        if not df_steps.empty:
            for _, s in df_steps.iterrows():
                sid = int(s["id"])
                pred_options.append(sid)
                pred_labels[sid] = f"ID {sid} - {s['task_name']} ({s['start_date']})"

        selected_pred = st.selectbox(
            "Predecessor Step (Optional)",
            options=pred_options,
            format_func=lambda x: pred_labels.get(x, "Unknown"),
            help="Select a preceding step to draw a visual dependency link on the timeline.",
            key="input_step_pred",
        )

        if st.button("➕ Save Step", width="stretch", key="btn_submit_step"):
            clean_task = task_name.strip()
            if not clean_task:
                st.error("Step Name is required.")
            elif end_d < start_d:
                st.error("End Date must be greater than or equal to Start Date.")
            else:
                milestone_repo.create_milestone(
                    project_id=selected_id,
                    task_name=clean_task,
                    phase=phase_name.strip() if phase_name.strip() else "General",
                    start_date=start_d.isoformat(),
                    end_date=end_d.isoformat(),
                    progress_pct=int(prog_val),
                    predecessor_id=selected_pred,
                )
                if start_d == end_d:
                    st.success(f"Milestone '{clean_task}' (Diamond) added successfully!")
                else:
                    st.success(f"Step '{clean_task}' added successfully!")
                st.rerun()

    # --------------------------------------------------------------------------
    # TAB B: EDIT STEP
    # --------------------------------------------------------------------------
    with tab_edit:
        st.subheader("Edit Existing Step or Milestone")
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

            with st.form(f"form_edit_step_{edit_step_id}"):
                col_e1, col_e2 = st.columns(2)
                edit_name = col_e1.text_input("Step / Task Name *", value=str(curr_step["task_name"]))
                edit_phase = col_e2.text_input("Phase / Category", value=str(curr_step["phase"]))

                col_ed1, col_ed2, col_ed3 = st.columns(3)
                edit_start = col_ed1.date_input("Start Date *", value=curr_start)
                edit_end = col_ed2.date_input(
                    "End Date * (Set equal to Start Date for Milestone)",
                    value=curr_end,
                    min_value=edit_start,
                )
                edit_prog = col_ed3.slider(
                    "Progress (%)",
                    min_value=0,
                    max_value=100,
                    value=int(curr_step["progress_pct"]),
                )

                # Predecessors (exclude self to avoid self-reference cycle)
                edit_pred_options: list[Optional[int]] = [None]
                edit_pred_labels: dict[Optional[int], str] = {None: "(None / Independent)"}
                for _, s in df_steps.iterrows():
                    sid = int(s["id"])
                    if sid != edit_step_id:
                        edit_pred_options.append(sid)
                        edit_pred_labels[sid] = f"ID {sid} - {s['task_name']} ({s['start_date']})"

                cur_pred_val = int(curr_step["predecessor_id"]) if pd.notna(curr_step["predecessor_id"]) else None
                pred_idx = edit_pred_options.index(cur_pred_val) if cur_pred_val in edit_pred_options else 0

                edit_pred = st.selectbox(
                    "Predecessor Step",
                    options=edit_pred_options,
                    index=pred_idx,
                    format_func=lambda x: edit_pred_labels.get(x, "Unknown"),
                )

                btn_update_step = st.form_submit_button("💾 Update Step Details", width="stretch")
                if btn_update_step:
                    clean_edit_name = edit_name.strip()
                    if not clean_edit_name:
                        st.error("Step Name is required.")
                    elif edit_end < edit_start:
                        st.error("End Date must be greater than or equal to Start Date.")
                    else:
                        milestone_repo.update_milestone(
                            milestone_id=edit_step_id,
                            task_name=clean_edit_name,
                            phase=edit_phase.strip() if edit_phase.strip() else "General",
                            start_date=edit_start.isoformat(),
                            end_date=edit_end.isoformat(),
                            progress_pct=int(edit_prog),
                            predecessor_id=edit_pred,
                        )
                        st.success(f"Step '{clean_edit_name}' updated successfully!")
                        st.rerun()

    # --------------------------------------------------------------------------
    # TAB C: CSV BULK LOADER & EXPORTER
    # --------------------------------------------------------------------------
    with tab_import:
        st.subheader("CSV Bulk Step Loader & Exporter")
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
                    steps_payload = MilestoneService.parse_csv(uploaded_file, selected_id)
                    st.dataframe(pd.DataFrame(steps_payload).head(), width="stretch")
                    if st.button("🚀 Import and Save Steps"):
                        count = milestone_repo.bulk_create_milestones(steps_payload)
                        st.success(f"Successfully imported {count} steps!")
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
