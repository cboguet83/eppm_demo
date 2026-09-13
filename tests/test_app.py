"""Pure portfolio display and budget regressions without database setup."""

import unittest

import pandas as pd

from app.domain.projects.budgets import BudgetAmounts, euro_amount, summarize_budgets
from app.presentation.components.planning_catalog import flatten_dynamic_attributes


class TestPortfolioLogic(unittest.TestCase):
    """Keep projection and financial arithmetic independent of persistence."""

    def test_flatten_dynamic_attributes_with_tags(self) -> None:
        """Verify flattening attributes for 'TAGS' and 'MULTI_ENUM'."""
        df_projects = pd.DataFrame([
            {
                "id": 1,
                "name": "Project Alpha",
                "status": "In Progress",
                "planned_budget": 100000,
                "actual_budget": 50000,
                "dynamic_attributes": {
                    "PRM_001": ["Python", "FastAPI", "Docker"],
                    "PRM_002": "Single Value",
                },
            },
            {
                "id": 2,
                "name": "Project Beta",
                "status": "Draft",
                "planned_budget": 50000,
                "actual_budget": 0,
                "dynamic_attributes": {"PRM_001": "SingleTag"},
            },
        ])
        df_params = pd.DataFrame([
            {"param_id": "PRM_001", "param_name": "Tech Tags", "param_type": 'TAGS'},
            {"param_id": "PRM_002", "param_name": "Note", "param_type": 'TEXT'},
        ])

        flattened = flatten_dynamic_attributes(df_projects, df_params)

        self.assertIn("PRM_001", flattened.columns)
        self.assertEqual(flattened.loc[flattened["id"] == 1, "PRM_001"].values[0], ["Python", "FastAPI", "Docker"])
        self.assertEqual(flattened.loc[flattened["id"] == 2, "PRM_001"].values[0], ["SingleTag"])


    def test_calculate_portfolio_metrics(self) -> None:
        """Verify calculations for planned, actual, variance, and burn rate."""
        df = pd.DataFrame([
            {"planned_budget": 100000, "actual_budget": 40000},
            {"planned_budget": 200000, "actual_budget": 110000},
        ])
        metrics = summarize_budgets(BudgetAmounts(euro_amount(row.planned_budget), euro_amount(row.actual_budget)) for row in df.itertuples())

        self.assertEqual(metrics.total_planned, 300000)
        self.assertEqual(metrics.total_actual, 150000)
        self.assertEqual(metrics.variance, 150000)
        self.assertEqual(metrics.burn_rate, 50.0)
