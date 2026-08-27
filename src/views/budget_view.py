"""Screen 5: Budget Tracking View."""

import pandas as pd
import plotly.express as px
import streamlit as st

from src.i18n import t
from src.repositories.project_repo import ProjectRepository
from src.services.portfolio_service import PortfolioService


def render_budget_tracking(project_repo: ProjectRepository) -> None:
    """Renders the Budget Tracking screen with financial KPIs, variance analytics, and visual breakdown charts."""
    st.header(f"💰 {t('portfolio.kpi_planned_budget', default='Budget Tracking & Financial Analytics')}")

    df_projects = project_repo.get_all_projects()

    if df_projects.empty:
        st.info(t("master_data.dynamic_empty", default="No projects registered yet."))
        return

    # 1. Financial KPI Summary Cards
    metrics = PortfolioService.calculate_portfolio_metrics(df_projects)
    total_planned = metrics.total_planned
    total_actual = metrics.total_actual
    variance = metrics.variance
    burn_rate = metrics.burn_rate

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(t("portfolio.kpi_planned_budget", default="Portfolio Planned"), f"€{total_planned:,.2f}")
    col2.metric(t("portfolio.kpi_actual_spend", default="Portfolio Actual Spend"), f"€{total_actual:,.2f}")
    col3.metric(
        t("portfolio.kpi_variance", default="Net Variance"),
        f"€{variance:,.2f}",
        delta=f"€{variance:,.2f}",
        delta_color="normal" if variance >= 0 else "inverse",
    )
    col4.metric(t("portfolio.kpi_burn_rate", default="Portfolio Burn Rate"), f"{burn_rate:.1f}%")

    if variance < 0:
        st.warning(f"⚠️ Portfolio is currently over budget by **€{abs(variance):,.2f}**!")
    else:
        st.success(f"✅ Portfolio financial health is on track with a budget surplus of **€{variance:,.2f}**.")

    st.divider()

    # 2. Planned vs Actual Grouped Bar Chart
    st.subheader("Project-by-by-Project Planned vs Actual Spend")
    df_melt = df_projects.melt(
        id_vars=["id", "name"],
        value_vars=["planned_budget", "actual_budget"],
        var_name="Budget_Type",
        value_name="Amount",
    )
    df_melt["Budget_Type"] = df_melt["Budget_Type"].map(
        {"planned_budget": "Planned Budget (€)", "actual_budget": "Actual Spend (€)"}
    )
    df_melt["Project_Label"] = df_melt["id"] + " - " + df_melt["name"]

    fig_bar = px.bar(
        df_melt,
        x="Project_Label",
        y="Amount",
        color="Budget_Type",
        barmode="group",
        title="Planned Budget vs Actual Spend by Project",
        template="plotly_white",
        color_discrete_map={
            "Planned Budget (€)": "#2563EB",
            "Actual Spend (€)": "#F59E0B",
        },
    )
    fig_bar.update_layout(
        xaxis_title="Project",
        yaxis_title="Amount (€)",
        legend_title="Type",
        height=380,
    )
    st.plotly_chart(fig_bar, width="stretch")

    # 3. Variance & Spend Distribution Charts
    col_v, col_s = st.columns(2)

    with col_v:
        st.subheader("Budget Variance by Project")
        df_var = df_projects.copy()
        df_var["Variance"] = df_var["planned_budget"] - df_var["actual_budget"]
        df_var["Variance_Color"] = df_var["Variance"].apply(lambda x: "Surplus (Under)" if x >= 0 else "Deficit (Over)")

        fig_var = px.bar(
            df_var,
            x="id",
            y="Variance",
            color="Variance_Color",
            title="Variance (€) [Planned - Actual]",
            template="plotly_white",
            color_discrete_map={
                "Surplus (Under)": "#10B981",
                "Deficit (Over)": "#EF4444",
            },
        )
        fig_var.update_layout(height=350, xaxis_title="Project Code", yaxis_title="Variance (€)")
        st.plotly_chart(fig_var, width="stretch")

    with col_s:
        st.subheader("Spend Distribution by Status")
        fig_pie = px.pie(
            df_projects,
            names="status",
            values="actual_budget",
            title="Actual Spend Distribution by Project Status",
            hole=0.45,
            template="plotly_white",
        )
        fig_pie.update_layout(height=350)
        st.plotly_chart(fig_pie, width="stretch")

    # 4. Detailed Financial Health Register
    st.subheader("Project Financial Health Register")
    df_health = df_projects.copy()
    df_health["variance"] = df_health["planned_budget"] - df_health["actual_budget"]
    df_health["burn_rate_pct"] = (
        (df_health["actual_budget"] / df_health["planned_budget"]) * 100.0
    ).fillna(0.0)

    def get_health_tag(row: pd.Series) -> str:
        if row["actual_budget"] > row["planned_budget"]:
            return "🔴 Over Budget"
        if row["burn_rate_pct"] >= 85.0:
            return "🟡 Near Capacity"
        return "🟢 On Track"

    df_health["health_status"] = df_health.apply(get_health_tag, axis=1)

    st.dataframe(
        df_health[["id", "name", "status", "planned_budget", "actual_budget", "variance", "burn_rate_pct", "health_status"]],
        column_config={
            "id": st.column_config.TextColumn("Project Code", width="small"),
            "name": st.column_config.TextColumn("Project Title", width="medium"),
            "status": st.column_config.TextColumn("Status", width="small"),
            "planned_budget": st.column_config.NumberColumn("Planned (€)", format="€%.2f"),
            "actual_budget": st.column_config.NumberColumn("Actual (€)", format="€%.2f"),
            "variance": st.column_config.NumberColumn("Variance (€)", format="€%.2f"),
            "burn_rate_pct": st.column_config.NumberColumn("Burn Rate (%)", format="%.1f%%"),
            "health_status": st.column_config.TextColumn("Financial Health", width="small"),
        },
        width="stretch",
        hide_index=True,
    )
