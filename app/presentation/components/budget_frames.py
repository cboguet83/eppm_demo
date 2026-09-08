"""Display-only conversions for decimal budget calculations."""

import pandas as pd

from app.application.services.budgets import BudgetReport
from app.domain.projects.budgets import (
    BudgetAmounts,
    PortfolioMetrics,
    euro_amount,
    summarize_budgets,
)

HEALTH_LABELS = {
    "over_budget": "🔴 Over Budget",
    "near_capacity": "🟡 Near Capacity",
    "on_track": "🟢 On Track",
}


def budget_frame(report: BudgetReport) -> pd.DataFrame:
    """Convert final monetary results to chart/widget numbers after calculation."""
    return pd.DataFrame(
        [
            {
                "id": str(row.project.id),
                "name": row.project.name,
                "status": row.project.status,
                "planned_budget": float(row.project.amounts.planned_budget),
                "actual_budget": float(row.project.amounts.actual_budget),
                "variance": float(row.analysis.variance),
                "burn_rate_pct": (
                    float(row.analysis.burn_rate) if row.analysis.burn_rate is not None else None
                ),
                "health_status": HEALTH_LABELS[row.analysis.health],
                "Variance_Color": (
                    "Surplus (Under)" if row.analysis.variance >= 0 else "Deficit (Over)"
                ),
            }
            for row in report.rows
        ]
    )


def calculate_frame_metrics(projects: pd.DataFrame) -> PortfolioMetrics:
    """Adapt legacy DataFrame amounts to the shared decimal aggregate rules."""
    if projects.empty:
        return PortfolioMetrics()
    return summarize_budgets(
        BudgetAmounts(
            euro_amount(planned if pd.notna(planned) else None),
            euro_amount(actual if pd.notna(actual) else None),
        )
        for planned, actual in projects[["planned_budget", "actual_budget"]].itertuples(
            index=False, name=None
        )
    )
