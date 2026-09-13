"""Unit tests for Business Logic Services."""

from app.domain.planning.constraints import evaluate_constraints
from app.domain.planning.csv_import import get_csv_template
from app.domain.planning.csv_import import parse_csv
from app.domain.projects.budgets import BudgetAmounts, euro_amount, summarize_budgets
from app.presentation.components.planning_catalog import enrich_projects_with_organization
from app.presentation.components.planning_catalog import flatten_dynamic_attributes
from app.presentation.components.planning_catalog import get_level_3_managing_function
from app.presentation.components.planning_imports import csv_text

import io
import unittest

import pandas as pd


class TestServices(unittest.TestCase):
    """Pure budget, planning, and presentation logic without database setup."""

    def test_calculate_portfolio_metrics(self) -> None:
        """Verify calculations for planned, actual, variance, and burn rate."""
        df = pd.DataFrame([
            {"planned_budget": 100000, "actual_budget": 40000},
            {"planned_budget": 200000, "actual_budget": 110000},
        ])
        metrics = summarize_budgets(BudgetAmounts(euro_amount(row.planned_budget), euro_amount(row.actual_budget)) for row in df.itertuples())

        self.assertEqual(metrics.total_projects, 2)
        self.assertEqual(metrics.total_planned, 300000)
        self.assertEqual(metrics.total_actual, 150000)
        self.assertEqual(metrics.variance, 150000)
        self.assertEqual(metrics.burn_rate, 50.0)

    def test_calculate_portfolio_metrics_empty(self) -> None:
        """Verify metrics for empty DataFrame."""
        metrics = summarize_budgets([])
        self.assertEqual(metrics.total_projects, 0)
        self.assertEqual(metrics.total_planned, 0.0)
        self.assertEqual(metrics.total_actual, 0.0)

    def test_flatten_dynamic_attributes(self) -> None:
        """Verify flattening dynamic JSON attributes into DataFrame columns."""
        df_projects = pd.DataFrame([
            {
                "id": 1,
                "name": "Alpha",
                "dynamic_attributes": {
                    "PRM_001": ["Python", "Docker"],
                    "PRM_002": "Single",
                },
            },
            {
                "id": 2,
                "name": "Beta",
                "dynamic_attributes": {
                    "PRM_001": "SingleTag",
                },
            },
        ])
        df_params = pd.DataFrame([
            {"param_id": "PRM_001", "param_name": "Tags", "param_type": 'TAGS'},
            {"param_id": "PRM_002", "param_name": "Text", "param_type": 'TEXT'},
        ])

        flattened = flatten_dynamic_attributes(df_projects, df_params)

        self.assertIn("PRM_001", flattened.columns)
        self.assertIn("PRM_002", flattened.columns)
        self.assertEqual(flattened.loc[flattened["id"] == 1, "PRM_001"].values[0], ["Python", "Docker"])
        self.assertEqual(flattened.loc[flattened["id"] == 2, "PRM_001"].values[0], ["SingleTag"])


    def test_milestone_service_parse_csv(self) -> None:
        """Verify parsing valid step/milestone CSV data including description, predecessor_id and 0-duration milestones."""
        csv_data = io.StringIO(
            "task_name,phase,start_date,end_date,progress_pct,description,predecessor_id\n"
            "Deploy API,Phase 1,2026-01-01,2026-01-15,100,Backend service deploy,\n"
            "Milestone Gate 1,Phase 1,2026-01-15,2026-01-15,100,Gate review signoff,1\n"
            "Build UI,Phase 2,2026-01-16,2026-02-15,50,,2\n"
        )
        parsed = parse_csv(csv_text(csv_data))
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["task_name"], "Deploy API")
        self.assertEqual(parsed[0]["description"], "Backend service deploy")
        self.assertIsNone(parsed[0]["predecessor_id"])
        self.assertEqual(parsed[1]["start_date"], parsed[1]["end_date"])
        self.assertEqual(parsed[1]["description"], "Gate review signoff")
        self.assertEqual(parsed[1]["predecessor_id"], 1)
        self.assertEqual(parsed[2]["description"], "")
        self.assertIn("description", get_csv_template())

    def test_milestone_service_parse_csv_invalid_dates(self) -> None:
        """Verify error raised when end_date is before start_date."""
        invalid_csv = io.StringIO(
            "task_name,phase,start_date,end_date,progress_pct\n"
            "Invalid Task,Phase 1,2026-02-15,2026-01-01,0\n"
        )
        with self.assertRaises(ValueError):
            parse_csv(csv_text(invalid_csv))

    def test_milestone_service_parse_csv_missing_cols(self) -> None:
        """Verify error raised on missing required columns."""
        invalid_csv = io.StringIO("phase,start_date\nPhase 1,2026-01-01\n")
        with self.assertRaises(ValueError):
            parse_csv(csv_text(invalid_csv))

    def test_evaluate_constraints_fs_ff_ss_sf(self) -> None:
        """Verify evaluation of all 4 link types (FS, FF, SS, SF) with positive/negative lags."""
        tasks = [
            {"id": 1, "task_name": "Task 1", "start_date": "2026-01-01", "end_date": "2026-01-10"},
            {"id": 2, "task_name": "Task 2 (FS valid)", "start_date": "2026-01-12", "end_date": "2026-01-20"},
            {"id": 3, "task_name": "Task 3 (FS violated)", "start_date": "2026-01-08", "end_date": "2026-01-15"},
            {"id": 4, "task_name": "Task 4 (SS valid with +2d lag)", "start_date": "2026-01-05", "end_date": "2026-01-15"},
            {"id": 5, "task_name": "Task 5 (FF violated)", "start_date": "2026-01-01", "end_date": "2026-01-09"},
        ]
        dependencies = [
            {"task_id": 2, "predecessor_task_id": 1, "link_type": "FS", "lag_days": 1},   # Req start >= 2026-01-11 (actual: 2026-01-12) -> Valid
            {"task_id": 3, "predecessor_task_id": 1, "link_type": "FS", "lag_days": 0},   # Req start >= 2026-01-10 (actual: 2026-01-08) -> Violated
            {"task_id": 4, "predecessor_task_id": 1, "link_type": "SS", "lag_days": 2},   # Req start >= 2026-01-03 (actual: 2026-01-05) -> Valid
            {"task_id": 5, "predecessor_task_id": 1, "link_type": "FF", "lag_days": 0},   # Req end >= 2026-01-10 (actual: 2026-01-09) -> Violated
        ]

        evaluated, violations = evaluate_constraints(tasks, dependencies)

        self.assertEqual(len(evaluated), 4)
        self.assertFalse(evaluated[0]["is_violated"])
        self.assertTrue(evaluated[1]["is_violated"])
        self.assertFalse(evaluated[2]["is_violated"])
        self.assertTrue(evaluated[3]["is_violated"])

        self.assertEqual(len(violations[2]), 0)
        self.assertEqual(len(violations[3]), 1)
        self.assertIn("FS with 'Task 1'", violations[3][0])
        self.assertEqual(len(violations[5]), 1)
        self.assertIn("FF with 'Task 1'", violations[5][0])

    def test_evaluate_constraints_external_project(self) -> None:
        """Verify evaluation of dependencies linked to whole external projects."""
        tasks = [
            {"id": 10, "task_name": "Internal Task", "start_date": "2026-02-01", "end_date": "2026-02-15"},
        ]
        dependencies = [
            {"task_id": 10, "predecessor_task_id": None, "predecessor_project_id": "PRJ-EXT", "link_type": "FS", "lag_days": 0},
        ]
        # Ext project bounds: start: 2026-01-01, end: 2026-02-05
        project_bounds = {"PRJ-EXT": ("2026-01-01", "2026-02-05")}

        evaluated, violations = evaluate_constraints(tasks, dependencies, project_bounds)
        self.assertEqual(len(evaluated), 1)
        # Req start >= 2026-02-05, actual is 2026-02-01 -> Violated
        self.assertTrue(evaluated[0]["is_violated"])
        self.assertEqual(len(violations[10]), 1)


    def test_flatten_dynamic_attributes_uses_ids_for_values_and_names_for_display(self) -> None:
        """Project values use stable parameter IDs; display columns use parameter names."""
        df_projects = pd.DataFrame([
            {
                "id": 1,
                "name": "Project One",
                "dynamic_attributes": {
                    "PRM_017": "6a",
                    "PRM_018": 49.61,
                },
            }
        ])
        params_df = pd.DataFrame([
            {"param_id": "PRM_017", "param_name": "code_line", "alias": "code ligne", "param_type": "ENUM"},
            {"param_id": "PRM_018", "param_name": "lat", "alias": "Latitude", "param_type": "NUMBER"},
        ])
        flattened = flatten_dynamic_attributes(df_projects, params_df)
        self.assertEqual(flattened.iloc[0]["code_line"], "6a")
        self.assertEqual(flattened.iloc[0]["lat"], 49.61)

    def test_property_values_do_not_fall_back_to_display_names_or_aliases(self) -> None:
        """Only stable property IDs supply values to the planning projection."""
        projects = pd.DataFrame([{
            "id": 1, "dynamic_attributes": {"Display title": "Old name", "label": "Old alias"},
        }])
        parameters = pd.DataFrame([{
            "param_id": "p", "param_name": "Display title", "alias": "label", "param_type": "TEXT",
        }])

        flattened = flatten_dynamic_attributes(projects, parameters)

        self.assertIsNone(flattened.iloc[0]["p"])
        self.assertIsNone(flattened.iloc[0]["Display title"])

    def test_get_level_3_managing_function(self) -> None:
        """Verify traversal up the reporting hierarchy to locate Level 3 managing function."""
        df_funcs = pd.DataFrame([
            {"function_id": 1, "name": "DG", "hierarchy_level": 1, "manager_function_id": None},
            {"function_id": 2, "name": "Dir 1", "hierarchy_level": 2, "manager_function_id": 1},
            {"function_id": 5, "name": "Chef Service A", "hierarchy_level": 3, "manager_function_id": 2},
            {"function_id": 10, "name": "Chef Div A1", "hierarchy_level": 4, "manager_function_id": 5},
            {"function_id": 17, "name": "Chef Projet A1", "hierarchy_level": 5, "manager_function_id": 10},
        ])

        # 1. Level 5 function climbs up to level 3
        l3 = get_level_3_managing_function(17, df_funcs)
        self.assertIsNotNone(l3)
        self.assertEqual(l3["function_id"], 5)
        self.assertEqual(l3["name"], "Chef Service A")

        # 2. Level 4 function climbs up to level 3
        l3_div = get_level_3_managing_function(10, df_funcs)
        self.assertIsNotNone(l3_div)
        self.assertEqual(l3_div["function_id"], 5)

        # 3. Level 3 function returns itself
        l3_self = get_level_3_managing_function(5, df_funcs)
        self.assertIsNotNone(l3_self)
        self.assertEqual(l3_self["function_id"], 5)

        # 4. Level 2 function (above level 3) returns None
        l3_above = get_level_3_managing_function(2, df_funcs)
        self.assertIsNone(l3_above)

        # 5. None or invalid function_id returns None
        self.assertIsNone(get_level_3_managing_function(None, df_funcs))
        self.assertIsNone(get_level_3_managing_function(999, df_funcs))

    def test_enrich_projects_with_organization(self) -> None:
        """Verify enrichment of projects dataframe with Project Manager and Level 3 Managing Function."""
        df_funcs = pd.DataFrame([
            {"function_id": 1, "name": "DG", "hierarchy_level": 1, "manager_function_id": None},
            {"function_id": 2, "name": "Dir 1", "hierarchy_level": 2, "manager_function_id": 1},
            {"function_id": 5, "name": "Chef Service A", "hierarchy_level": 3, "manager_function_id": 2},
            {"function_id": 10, "name": "Chef Div A1", "hierarchy_level": 4, "manager_function_id": 5},
            {"function_id": 17, "name": "Chef Projet A1", "hierarchy_level": 5, "manager_function_id": 10},
        ])
        df_projects = pd.DataFrame([
            {"id": 1, "name": "P1", "function_id": 17},
            {"id": 2, "name": "P2", "function_id": None},
            {"id": 3, "name": "P3", "function_id": 10},
        ])
        df_employees = pd.DataFrame([
            {"employee_id": 101, "firstname": "Ada", "lastname": "Lovelace", "function_id": 17},
        ])

        enriched = enrich_projects_with_organization(
            df_projects,
            df_funcs,
            df_employees,
        )
        self.assertEqual(enriched.iloc[0]["project_manager"], "Ada Lovelace")
        self.assertEqual(enriched.iloc[0]["level_3_manager_name"], "Chef Service A")
        self.assertEqual(enriched.iloc[0]["level_3_manager_id"], 5)

        self.assertEqual(enriched.iloc[1]["project_manager"], "—")
        self.assertEqual(enriched.iloc[1]["level_3_manager_name"], "—")
        self.assertTrue(pd.isna(enriched.iloc[1]["level_3_manager_id"]))
        self.assertEqual(enriched.iloc[2]["project_manager"], "Chef Div A1")


if __name__ == "__main__":
    unittest.main()
