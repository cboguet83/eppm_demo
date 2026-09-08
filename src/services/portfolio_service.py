"""Business logic service for portfolio calculations and attribute transformation."""

from app.presentation.components.planning_catalog import flatten_dynamic_attributes
import json
from typing import Any
import pandas as pd
from src.models.constants import PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS, PARAM_TYPE_TEXT
from src.models.project import PortfolioMetrics


class PortfolioService:
    """Service handling financial calculations and dynamic attribute transformation."""

    @staticmethod
    def calculate_portfolio_metrics(df_projects: pd.DataFrame) -> PortfolioMetrics:
        """Calculates summary financial KPIs from a projects DataFrame.

        Args:
            df_projects: Projects DataFrame with 'planned_budget' and 'actual_budget'.

        Returns:
            PortfolioMetrics: Strongly-typed metrics container.
        """
        if df_projects.empty:
            return PortfolioMetrics()
        total_projects = len(df_projects)
        total_planned = float(df_projects["planned_budget"].sum())
        total_actual = float(df_projects["actual_budget"].sum())
        variance = total_planned - total_actual
        burn_rate = total_actual / total_planned * 100.0 if total_planned > 0 else 0.0
        return PortfolioMetrics(
            total_projects=total_projects,
            total_planned=total_planned,
            total_actual=total_actual,
            variance=variance,
            burn_rate=burn_rate,
        )

    flatten_dynamic_attributes = staticmethod(flatten_dynamic_attributes)
