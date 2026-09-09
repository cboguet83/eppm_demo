"""Display-only conversions for decimal budget calculations."""

import pandas as pd

from app.application.services.budgets import BudgetReport

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
