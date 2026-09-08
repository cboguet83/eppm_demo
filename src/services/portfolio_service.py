"""Business logic service for portfolio calculations and attribute transformation."""

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
        burn_rate = (total_actual / total_planned * 100.0) if total_planned > 0 else 0.0

        return PortfolioMetrics(
            total_projects=total_projects,
            total_planned=total_planned,
            total_actual=total_actual,
            variance=variance,
            burn_rate=burn_rate,
        )

    @staticmethod
    def flatten_dynamic_attributes(
        df_projects: pd.DataFrame, params: pd.DataFrame
    ) -> pd.DataFrame:
        """Unpacks in-memory attributes into individual DataFrame columns.

        Args:
            df_projects: Projects DataFrame containing id and dynamic_attributes columns.
            params: Schema parameters DataFrame with param_id, param_type.

        Returns:
            pd.DataFrame: Merged DataFrame with flattened dynamic attributes.
        """
        if df_projects.empty:
            return df_projects

        flattened_rows: list[dict[str, Any]] = []
        for _, row in df_projects.iterrows():
            raw_json = row.get("dynamic_attributes")
            attrs: dict[str, Any] = {}
            if isinstance(raw_json, dict):
                attrs = dict(raw_json)
            elif isinstance(raw_json, str) and raw_json.strip():
                try:
                    parsed = json.loads(raw_json)
                    if isinstance(parsed, dict):
                        attrs = parsed
                except json.JSONDecodeError:
                    attrs = {}
            attrs["id"] = row["id"]
            flattened_rows.append(attrs)

        df_dyn = pd.DataFrame(flattened_rows)
        df_merged = pd.merge(
            df_projects,
            df_dyn,
            on="id",
            how="left",
            suffixes=("", "_dyn"),
        )


        if not params.empty and "param_id" in params.columns:
            for _, p in params.iterrows():
                pid = str(p["param_id"])
                pname = str(p.get("param_name", pid))
                alias = str(p.get("alias", "")).strip() if pd.notna(p.get("alias")) else ""
                ptype = str(p.get("param_type", PARAM_TYPE_TEXT))

                if pid not in df_merged.columns:
                    df_merged[pid] = None

                if pname in df_merged.columns and pname != pid:
                    df_merged[pid] = df_merged[pid].combine_first(df_merged[pname])
                if alias and alias in df_merged.columns and alias != pid:
                    df_merged[pid] = df_merged[pid].combine_first(df_merged[alias])

                if ptype in (PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS):
                    df_merged[pid] = df_merged[pid].apply(
                        lambda x: x if isinstance(x, list) else ([x] if pd.notna(x) and x != "" else [])
                    )

                if pname != pid:
                    df_merged[pname] = df_merged[pid]
        return df_merged
