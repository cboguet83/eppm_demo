"""Unit tests for Data Access Repositories."""

import os
import shutil
import sqlite3
import tempfile
import unittest

from src.database.connection import get_db
from src.database.schema_init import init_db
from src.models.constants import PARAM_TYPE_TAGS, PARAM_TYPE_TEXT, STATUS_IN_PROGRESS
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository


class TestRepositories(unittest.TestCase):
    """Test suite for SchemaRepository, ProjectRepository, and MilestoneRepository."""

    def setUp(self) -> None:
        """Arrange: Create isolated temporary database and initialize tables."""
        self.test_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.test_dir, "test_repos.db")
        init_db(self.temp_db_path)

        self.schema_repo = SchemaRepository(self.temp_db_path)
        self.project_repo = ProjectRepository(self.temp_db_path)
        self.milestone_repo = MilestoneRepository(self.temp_db_path)

    def tearDown(self) -> None:
        """Clean up temporary test database."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_schema_group_crud(self) -> None:
        """Verify creating, editing, and deleting a schema group."""
        # Create
        grp_id = self.schema_repo.create_group("Finance & Risk", 1)
        self.assertGreater(grp_id, 0)

        # Read
        df = self.schema_repo.get_all_groups()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["group_name"], "Finance & Risk")

        # Update
        updated = self.schema_repo.update_group(grp_id, "Finance & Compliance", 5)
        self.assertTrue(updated)

        df_updated = self.schema_repo.get_all_groups()
        self.assertEqual(df_updated.iloc[0]["group_name"], "Finance & Compliance")
        self.assertEqual(df_updated.iloc[0]["display_order"], 5)

        # Delete
        deleted = self.schema_repo.delete_group(grp_id)
        self.assertTrue(deleted)
        self.assertTrue(self.schema_repo.get_all_groups().empty)

    def test_schema_parameter_and_option_crud(self) -> None:
        """Verify creating parameters (grouped & ungrouped) and managing discrete options."""
        grp_id = self.schema_repo.create_group("Technical", 1)

        # Grouped parameter
        p1 = self.schema_repo.create_parameter("PRM_001", grp_id, "Cloud Provider", "ENUM")
        self.assertTrue(p1)

        # Ungrouped parameter (group_id is None)
        p2 = self.schema_repo.create_parameter("PRM_002", None, "Tags", PARAM_TYPE_TAGS)
        self.assertTrue(p2)

        # Add discrete options
        opt1 = self.schema_repo.add_option("PRM_001", "AWS", 1)
        opt2 = self.schema_repo.add_option("PRM_001", "GCP", 2)
        self.assertGreater(opt1, 0)
        self.assertGreater(opt2, 0)

        df_opts = self.schema_repo.get_all_options()
        self.assertEqual(len(df_opts), 2)

        # Delete option
        self.schema_repo.delete_option(opt1)
        df_opts_after = self.schema_repo.get_all_options()
        self.assertEqual(len(df_opts_after), 1)

        # Delete parameter
        self.schema_repo.delete_parameter("PRM_001")
        df_params = self.schema_repo.get_all_parameters()
        self.assertEqual(len(df_params), 1)
        self.assertEqual(df_params.iloc[0]["param_id"], "PRM_002")

    def test_project_crud_and_cascade(self) -> None:
        """Verify project creation, update, query, and cascade deletion."""
        # Create project
        created = self.project_repo.create_project(
            project_id="PRJ-100",
            name="Modernization Core",
            status=STATUS_IN_PROGRESS,
            planned_budget=250000.0,
            actual_budget=100000.0,
            dynamic_attributes={"PRM_001": "Value"},
        )
        self.assertTrue(created)
        self.assertTrue(self.project_repo.exists("PRJ-100"))

        # Create milestone attached to project
        ms_id = self.milestone_repo.create_milestone(
            project_id="PRJ-100",
            task_name="Sprint 1",
            phase="Phase 1",
            start_date="2026-01-01",
            end_date="2026-01-15",
            progress_pct=100,
        )
        self.assertGreater(ms_id, 0)

        df_ms = self.milestone_repo.get_milestones_by_project("PRJ-100")
        self.assertEqual(len(df_ms), 1)

        # Delete project and verify milestone cascade
        self.project_repo.delete_project("PRJ-100")
        self.assertFalse(self.project_repo.exists("PRJ-100"))
        self.assertTrue(self.milestone_repo.get_milestones_by_project("PRJ-100").empty)

    def test_bulk_create_milestones(self) -> None:
        """Verify bulk insertion of milestone records."""
        self.project_repo.create_project("PRJ-200", "Bulk Proj", "Draft", 0, 0, {})

        payload = [
            {"project_id": "PRJ-200", "task_name": "T1", "phase": "P1", "start_date": "2026-01-01", "end_date": "2026-01-10", "progress_pct": 0},
            {"project_id": "PRJ-200", "task_name": "T2", "phase": "P1", "start_date": "2026-01-11", "end_date": "2026-01-20", "progress_pct": 50},
        ]
        inserted = self.milestone_repo.bulk_create_milestones(payload)
        self.assertEqual(inserted, 2)

        df_ms = self.milestone_repo.get_milestones_by_project("PRJ-200")
        self.assertEqual(len(df_ms), 2)


if __name__ == "__main__":
    unittest.main()
