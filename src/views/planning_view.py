"""Screen 4: Planning & Milestone Loader View."""

import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.project_repo import ProjectRepository
from src.services.milestone_service import MilestoneService


def render_planning_milestones(
    project_repo: ProjectRepository,
    milestone_repo: MilestoneRepository,
) -> None:
    """Renders the Planning & Milestone Loader screen with Gantt chart visualization and CSV bulk import."""
    st.header("📅 Planning & Milestone Loader")

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

    df_milestones = milestone_repo.get_milestones_by_project(selected_id)

    # 1. Gantt Timeline Chart
    st.subheader(f"Timeline & Gantt Chart: {selected_id}")
    if df_milestones.empty:
        st.info("No milestones defined for this project yet. Add tasks below or upload a schedule CSV.")
    else:
        df_plot = df_milestones.copy()
        df_plot["start_date"] = pd.to_datetime(df_plot["start_date"])
        df_plot["end_date"] = pd.to_datetime(df_plot["end_date"])

        fig = px.timeline(
            df_plot,
            x_start="start_date",
            x_end="end_date",
            y="task_name",
            color="phase",
            hover_data=["progress_pct"],
            title=f"Milestone Schedule — {proj_info['name']}",
            template="plotly_white",
        )
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(
            height=360,
            margin=dict(l=20, r=20, t=40, b=20),
            xaxis_title="Timeline Date",
            yaxis_title="Tasks / Milestones",
        )
        st.plotly_chart(fig, width="stretch")

    # 2. Add Single Milestone Form
    st.subheader("Add Single Milestone")
    with st.form("form_add_milestone", clear_on_submit=True):
        col_t1, col_t2 = st.columns(2)
        task_name = col_t1.text_input("Task / Milestone Name *", placeholder="e.g. UAT Testing")
        phase_name = col_t2.text_input("Phase / Category", value="Phase 1 - Build")

        col_d1, col_d2, col_d3 = st.columns(3)
        today = datetime.date.today()
        start_d = col_d1.date_input("Start Date", value=today)
        end_d = col_d2.date_input("End Date", value=today + datetime.timedelta(days=30))
        prog_val = col_d3.slider("Progress (%)", min_value=0, max_value=100, value=0)

        btn_add_ms = st.form_submit_button("➕ Add Milestone")
        if btn_add_ms:
            if not task_name.strip():
                st.error("Task Name is required.")
            elif start_d > end_d:
                st.error("Start Date cannot be after End Date.")
            else:
                milestone_repo.create_milestone(
                    project_id=selected_id,
                    task_name=task_name.strip(),
                    phase=phase_name.strip() if phase_name.strip() else "General",
                    start_date=start_d.isoformat(),
                    end_date=end_d.isoformat(),
                    progress_pct=int(prog_val),
                )
                st.success("Milestone added successfully!")
                st.rerun()

    # 3. Milestone Table & Actions
    if not df_milestones.empty:
        st.subheader("Milestones Register")
        st.dataframe(
            df_milestones[["id", "task_name", "phase", "start_date", "end_date", "progress_pct"]],
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "task_name": st.column_config.TextColumn("Task Name", width="medium"),
                "phase": st.column_config.TextColumn("Phase", width="small"),
                "start_date": st.column_config.DateColumn("Start Date"),
                "end_date": st.column_config.DateColumn("End Date"),
                "progress_pct": st.column_config.ProgressColumn("Progress", min_value=0, max_value=100, format="%d%%"),
            },
            width="stretch",
            hide_index=True,
        )

        col_act1, col_act2 = st.columns([3, 1])
        del_ms_id = col_act1.selectbox(
            "Select Milestone to Delete",
            options=df_milestones["id"].tolist(),
            format_func=lambda x: f"ID {x} - {df_milestones[df_milestones['id'] == x]['task_name'].iloc[0]}",
        )
        if col_act2.button("🗑️ Delete Milestone"):
            milestone_repo.delete_milestone(del_ms_id)
            st.success("Milestone deleted.")
            st.rerun()

    # 4. CSV Bulk Loader & Exporter
    st.divider()
    st.subheader("📥 CSV Bulk Loader & Exporter")

    col_exp, col_imp = st.columns(2)
    with col_exp:
        st.write("##### Export Schedule Template")
        template_csv = MilestoneService.get_csv_template()
        st.download_button(
            label="📄 Download CSV Template",
            data=template_csv,
            file_name="milestone_template.csv",
            mime="text/csv",
        )

    with col_imp:
        st.write("##### Bulk Import Milestones")
        uploaded_file = st.file_uploader("Upload Milestones CSV", type=["csv"])
        if uploaded_file is not None:
            try:
                milestones_payload = MilestoneService.parse_csv(uploaded_file, selected_id)
                st.dataframe(pd.DataFrame(milestones_payload).head(), width="stretch")
                if st.button("🚀 Import and Save Milestones"):
                    count = milestone_repo.bulk_create_milestones(milestones_payload)
                    st.success(f"Successfully imported {count} milestones!")
                    st.rerun()
            except Exception as e:
                st.error(f"Error parsing CSV: {e}")
