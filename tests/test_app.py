"""Legacy regression test suite ensuring backward compatibility."""

import json
import os
import shutil
import tempfile
import unittest

import pandas as pd

from src.database.connection import get_db
from src.database.schema_init import init_db
from src.database.seeder import seed_default_data_if_empty
from src.models.constants import (
    PARAM_TYPE_ENUM,
    PARAM_TYPE_MULTI_ENUM,
    PARAM_TYPE_TAGS,
    PARAM_TYPE_TEXT,
    PARAM_TYPE_URL,
    STATUS_DRAFT,
    STATUS_IN_PROGRESS,
)
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository
from src.services.portfolio_service import PortfolioService
from src.services.schema_service import SchemaService


class TestPPMStudio(unittest.TestCase):
    """Test suite for backward compatibility of core workflows."""

    def setUp(self) -> None:
        """Create a temporary database file for isolation."""
        self.test_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.test_dir, "test_ppm.db")
        self.schema_repo = SchemaRepository(self.temp_db_path)
        self.project_repo = ProjectRepository(self.temp_db_path)

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_init_db_creates_tables(self) -> None:
        """Arrange, Act, Assert table creation in fresh SQLite database."""
        init_db(self.temp_db_path)

        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {
            "schema_groups",
            "schema_parameters",
            "schema_param_options",
            "project",
            "project_task",
        }
        self.assertTrue(expected_tables.issubset(tables))

    def test_seed_default_data_populates_tables(self) -> None:
        """Verify default seeding inserts groups, params, options, projects, and milestones."""
        init_db(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)

        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM schema_groups")
            group_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM schema_parameters")
            param_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM project")
            project_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM project_task")
            milestone_count = cursor.fetchone()[0]

        self.assertGreaterEqual(group_count, 2)
        self.assertGreaterEqual(param_count, 5)
        self.assertGreaterEqual(project_count, 3)
        self.assertGreaterEqual(milestone_count, 5)

    def test_get_next_available_group_order(self) -> None:
        """Verify calculation of next available display order for schema groups."""
        init_db(self.temp_db_path)
        self.assertEqual(SchemaService.get_next_available_group_order(self.temp_db_path), 1)

        seed_default_data_if_empty(self.temp_db_path)
        self.assertEqual(SchemaService.get_next_available_group_order(self.temp_db_path), 6)

    def test_schema_group_edit_and_delete(self) -> None:
        """Verify editing an existing schema group and deleting it."""
        init_db(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)

        # Edit Group 1
        updated = self.schema_repo.update_group(1, "Updated Strategic Alignment", 10)
        self.assertTrue(updated)

        df = self.schema_repo.get_all_groups()
        row = df[df["id"] == 1].iloc[0]
        self.assertEqual(row["group_name"], "Updated Strategic Alignment")
        self.assertEqual(row["display_order"], 10)

        # Delete Group 1
        deleted = self.schema_repo.delete_group(1)
        self.assertTrue(deleted)

        df_after = self.schema_repo.get_all_groups()
        self.assertTrue(df_after[df_after["id"] == 1].empty)

    def test_create_ungrouped_parameter(self) -> None:
        """Verify creating a parameter without assigning it to any group (group_id is NULL)."""
        init_db(self.temp_db_path)
        created = self.schema_repo.create_parameter("PRM_999", None, "Standalone Keyword", PARAM_TYPE_TAGS)
        self.assertTrue(created)

        params = self.schema_repo.get_all_parameters()
        self.assertIn("PRM_999", params["param_id"].values)
        self.assertTrue(params.loc[params["param_id"] == "PRM_999", "group_id"].isna().values[0])

    def test_flatten_dynamic_attributes_with_tags(self) -> None:
        """Verify flattening attributes for PARAM_TYPE_TAGS and PARAM_TYPE_MULTI_ENUM."""
        df_projects = pd.DataFrame([
            {
                "id": "PRJ-001",
                "name": "Project Alpha",
                "status": "In Progress",
                "planned_budget": 100000.0,
                "actual_budget": 50000.0,
                "dynamic_attributes": json.dumps({
                    "PRM_001": ["Python", "FastAPI", "Docker"],
                    "PRM_002": "Single Value",
                }),
            },
            {
                "id": "PRJ-002",
                "name": "Project Beta",
                "status": "Draft",
                "planned_budget": 50000.0,
                "actual_budget": 0.0,
                "dynamic_attributes": json.dumps({"PRM_001": "SingleTag"}),
            },
        ])
        df_params = pd.DataFrame([
            {"param_id": "PRM_001", "param_name": "Tech Tags", "param_type": PARAM_TYPE_TAGS},
            {"param_id": "PRM_002", "param_name": "Note", "param_type": PARAM_TYPE_TEXT},
        ])

        flattened = PortfolioService.flatten_dynamic_attributes(df_projects, df_params)

        self.assertIn("PRM_001", flattened.columns)
        self.assertEqual(flattened.loc[flattened["id"] == "PRJ-001", "PRM_001"].values[0], ["Python", "FastAPI", "Docker"])
        self.assertEqual(flattened.loc[flattened["id"] == "PRJ-002", "PRM_001"].values[0], ["SingleTag"])

    def test_calculate_portfolio_metrics(self) -> None:
        """Verify calculations for planned, actual, variance, and burn rate."""
        df = pd.DataFrame([
            {"planned_budget": 100000.0, "actual_budget": 40000.0},
            {"planned_budget": 200000.0, "actual_budget": 110000.0},
        ])
        metrics = PortfolioService.calculate_portfolio_metrics(df)

        self.assertEqual(metrics.total_planned, 300000.0)
        self.assertEqual(metrics.total_actual, 150000.0)
        self.assertEqual(metrics.variance, 150000.0)
        self.assertEqual(metrics.burn_rate, 50.0)


if __name__ == "__main__":
    unittest.main()
