"""Integration tests for PPM Studio Pro."""

import os
import shutil
import tempfile
import unittest

from src.database.connection import get_db
from src.database.schema_init import init_db
from src.database.seeder import seed_default_data_if_empty
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository
from src.services.portfolio_service import PortfolioService


class TestIntegration(unittest.TestCase):
    """End-to-end workflow integration tests across repositories and services."""

    def setUp(self) -> None:
        """Arrange: Isolated test database initialized with seed data."""
        self.test_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.test_dir, "test_integration.db")
        init_db(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)

        self.schema_repo = SchemaRepository(self.temp_db_path)
        self.project_repo = ProjectRepository(self.temp_db_path)
        self.milestone_repo = MilestoneRepository(self.temp_db_path)

    def tearDown(self) -> None:
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_full_portfolio_lifecycle(self) -> None:
        """Verify full lifecycle: create schema -> create project -> add milestone -> calculate KPIs -> delete."""
        # 1. Add new schema group and parameter
        grp_id = self.schema_repo.create_group("Cloud Operations", 10)
        self.schema_repo.create_parameter("PRM_CLD", grp_id, "Cloud Target", "ENUM")
        self.schema_repo.add_option("PRM_CLD", "GCP", 1)
        self.schema_repo.add_option("PRM_CLD", "Azure", 2)

        # 2. Add new project using the dynamic parameter
        new_pid = 101
        self.project_repo.create_project(
            project_id=new_pid,
            name="Cloud Migration",
            status="In Progress",
            planned_budget=100000.0,
            actual_budget=40000.0,
            dynamic_attributes={"PRM_CLD": "GCP"},
        )

        # 3. Add milestones
        self.milestone_repo.create_milestone(
            project_id=new_pid,
            task_name="Assessment",
            phase="Phase 1",
            start_date="2026-01-01",
            end_date="2026-02-01",
            progress_pct=100,
        )

        # 4. Fetch projects and verify metrics & attribute flattening
        df_projects = self.project_repo.get_all_projects()
        df_params = self.schema_repo.get_all_parameters()
        metrics = PortfolioService.calculate_portfolio_metrics(df_projects)
        df_flattened = PortfolioService.flatten_dynamic_attributes(df_projects, df_params)

        self.assertIn("PRM_CLD", df_flattened.columns)
        self.assertEqual(
            df_flattened.loc[df_flattened["id"] == new_pid, "PRM_CLD"].values[0],
            "GCP",
        )
        self.assertGreaterEqual(metrics.total_projects, 4)

        # 5. Clean up project
        self.project_repo.delete_project(new_pid)
        self.assertFalse(self.project_repo.exists(new_pid))


if __name__ == "__main__":
    unittest.main()
