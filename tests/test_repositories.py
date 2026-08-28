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

        # Create step 1
        s1_id = self.milestone_repo.create_milestone(
            project_id="PRJ-100",
            task_name="Sprint 1",
            phase="Phase 1",
            start_date="2026-01-01",
            end_date="2026-01-15",
            progress_pct=100,
        )
        self.assertGreater(s1_id, 0)

        # Create milestone step 2 with predecessor = s1_id and start_date == end_date
        s2_id = self.milestone_repo.create_milestone(
            project_id="PRJ-100",
            task_name="Sprint 1 Sign-Off",
            phase="Phase 1",
            start_date="2026-01-15",
            end_date="2026-01-15",
            progress_pct=100,
            predecessor_id=s1_id,
        )
        self.assertGreater(s2_id, 0)

        df_steps = self.milestone_repo.get_milestones_by_project("PRJ-100")
        self.assertEqual(len(df_steps), 2)
        s2_row = df_steps[df_steps["id"] == s2_id].iloc[0]
        self.assertEqual(s2_row["predecessor_name"], "Sprint 1")
        self.assertEqual(s2_row["start_date"], s2_row["end_date"])

        # Update step 2 via update_milestone
        updated = self.milestone_repo.update_milestone(
            milestone_id=s2_id,
            task_name="Sprint 1 Final Approval",
            phase="Phase 1 - Gate",
            start_date="2026-01-16",
            end_date="2026-01-16",
            progress_pct=100,
            predecessor_id=s1_id,
        )
        self.assertTrue(updated)

        # Update dates via drag-and-drop helper
        d_updated = self.milestone_repo.update_dates(s1_id, "2026-01-05", "2026-01-20")
        self.assertTrue(d_updated)

        # Update progress via helper
        p_updated = self.milestone_repo.update_progress(s1_id, 80)
        self.assertTrue(p_updated)

        df_after_update = self.milestone_repo.get_milestones_by_project("PRJ-100")
        s1_updated_row = df_after_update[df_after_update["id"] == s1_id].iloc[0]
        self.assertEqual(s1_updated_row["start_date"], "2026-01-05")
        self.assertEqual(s1_updated_row["end_date"], "2026-01-20")
        self.assertEqual(s1_updated_row["progress_pct"], 80)

        # Delete project and verify milestone cascade
        self.project_repo.delete_project("PRJ-100")
        self.assertFalse(self.project_repo.exists("PRJ-100"))
        self.assertTrue(self.milestone_repo.get_milestones_by_project("PRJ-100").empty)

    def test_bulk_create_milestones(self) -> None:
        """Verify bulk insertion of step records with predecessors."""
        self.project_repo.create_project("PRJ-200", "Bulk Proj", "Draft", 0, 0, {})

        payload = [
            {"project_id": "PRJ-200", "task_name": "T1", "phase": "P1", "start_date": "2026-01-01", "end_date": "2026-01-10", "progress_pct": 0, "predecessor_id": None},
            {"project_id": "PRJ-200", "task_name": "T2", "phase": "P1", "start_date": "2026-01-11", "end_date": "2026-01-20", "progress_pct": 50, "predecessor_id": 1},
        ]
        inserted = self.milestone_repo.bulk_create_milestones(payload)
        self.assertEqual(inserted, 2)

        df_ms = self.milestone_repo.get_milestones_by_project("PRJ-200")
        self.assertEqual(len(df_ms), 2)

    def test_multi_dependencies_and_bounds(self) -> None:
        """Verify multi-predecessors, external dependencies, and project date bounds."""
        self.project_repo.create_project("PRJ-301", "Source Project", "Active", 0, 0, {})
        self.project_repo.create_project("PRJ-302", "Target Project", "Active", 0, 0, {})

        # Add steps to PRJ-301
        p301_s1 = self.milestone_repo.create_milestone("PRJ-301", "Feasibility", "Phase 1", "2026-03-01", "2026-03-10", 100)
        p301_s2 = self.milestone_repo.create_milestone("PRJ-301", "Architecture", "Phase 1", "2026-03-11", "2026-03-25", 100)

        # Verify date bounds for PRJ-301
        min_d, max_d = self.milestone_repo.get_project_date_bounds("PRJ-301")
        self.assertEqual(min_d, "2026-03-01")
        self.assertEqual(max_d, "2026-03-25")

        # Add step to PRJ-302 with multi-dependencies: 1 external whole project and 1 external task
        p302_s1 = self.milestone_repo.create_milestone(
            "PRJ-302",
            "Execution Step",
            "Phase 2",
            "2026-03-26",
            "2026-04-10",
            0,
            dependencies=[
                {"predecessor_task_id": None, "predecessor_project_id": "PRJ-301", "link_type": "FS", "lag_days": 1},
                {"predecessor_task_id": p301_s2, "predecessor_project_id": "PRJ-301", "link_type": "SS", "lag_days": 5},
            ],
        )
        self.assertGreater(p302_s1, 0)

        deps = self.milestone_repo.get_task_dependencies(p302_s1)
        self.assertEqual(len(deps), 2)
        link_types = [d["link_type"] for d in deps]
        self.assertIn("FS", link_types)
        self.assertIn("SS", link_types)

        # Update dependencies
        self.milestone_repo.save_task_dependencies(
            p302_s1,
            [{"predecessor_task_id": p301_s1, "predecessor_project_id": "PRJ-301", "link_type": "FF", "lag_days": 2}],
        )
        updated_deps = self.milestone_repo.get_task_dependencies(p302_s1)
        self.assertEqual(len(updated_deps), 1)
        self.assertEqual(updated_deps[0]["link_type"], "FF")
        self.assertEqual(updated_deps[0]["lag_days"], 2)

    def test_batch_milestone_queries(self) -> None:
        """Verify batch query methods across multiple projects."""
        self.project_repo.create_project(1, "Batch 1", "Active", 0, 0, {})
        self.project_repo.create_project(2, "Batch 2", "Active", 0, 0, {})

        m1 = self.milestone_repo.create_milestone(1, "Task 1", "Phase 1", "2026-01-01", "2026-01-10", 50)
        m2 = self.milestone_repo.create_milestone(1, "Task 2", "Phase 1", "2026-01-11", "2026-01-20", 0)
        m3 = self.milestone_repo.create_milestone(2, "Task 3", "Phase 2", "2026-02-01", "2026-02-15", 10,
                                                  dependencies=[{"predecessor_task_id": m1, "link_type": "FS", "lag_days": 2}])

        # 1. Batch date bounds
        all_bounds = self.milestone_repo.get_all_project_date_bounds()
        self.assertIn("1", all_bounds)
        self.assertIn("2", all_bounds)
        self.assertEqual(all_bounds["1"], ("2026-01-01", "2026-01-20"))
        self.assertEqual(all_bounds["2"], ("2026-02-01", "2026-02-15"))

        # 2. Batch external tasks map
        ext_map = self.milestone_repo.get_all_external_tasks_map()
        self.assertIn("1", ext_map)
        self.assertEqual(len(ext_map["1"]), 2)
        self.assertEqual(ext_map["1"][0]["task_name"], "Task 1")

        # 3. Batch milestones for projects
        batch_df = self.milestone_repo.get_milestones_for_projects([1, 2])
        self.assertEqual(len(batch_df), 3)

        # 4. Batch dependencies for projects
        batch_deps = self.milestone_repo.get_dependencies_for_projects([1, 2])
        self.assertEqual(len(batch_deps), 1)
        self.assertEqual(batch_deps[0]["task_id"], m3)
        self.assertEqual(batch_deps[0]["predecessor_task_id"], m1)

        # 5. Get all milestones across all projects
        all_milestones = self.milestone_repo.get_all_milestones()
        self.assertEqual(len(all_milestones), 3)
        self.assertIn("project_name", all_milestones.columns)
        self.assertEqual(all_milestones.iloc[0]["project_name"], "Batch 1")


if __name__ == "__main__":
    unittest.main()

