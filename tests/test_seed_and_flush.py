"""Unit tests for Database Seeding and Database Flushing scripts."""

from app.main import create_project_service
from app.main import create_schema_service

from app.presentation.components import planning_frames
import pandas as pd

from contextlib import closing

import gc
import os
import shutil
import tempfile
import unittest

from app.infrastructure.database.flush import flush_database
from app.infrastructure.database.bulk_seed import seed_database
from app.infrastructure.database.connection import get_db
from app.main import create_planning_service


class TestSeedAndFlush(unittest.TestCase):
    """Test suite verifying database seeding and flushing operations."""

    def setUp(self) -> None:
        """Sets up a temporary SQLite database for test isolation."""
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_seed_flush.db")

        self.project_repo = create_project_service(db_path=self.db_path)
        self.milestone_repo = create_planning_service(db_path=self.db_path)

    def tearDown(self) -> None:
        """Cleans up the temporary database directory."""
        gc.collect()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_seed_database_generates_correct_counts_and_structures(self) -> None:
        """Verify seed_database creates the requested number of projects and tasks within min/max bounds."""
        res = seed_database(
            num_projects=15,
            min_tasks_per_project=3,
            max_tasks_per_project=8,
            db_path=self.db_path,
            clean_first=True,
            random_seed=123,
        )

        self.assertEqual(res["projects_created"], 15)
        self.assertGreaterEqual(res["tasks_created"], 15 * 3)
        self.assertLessEqual(res["tasks_created"], 15 * 8)
        self.assertGreater(res["dependencies_created"], 0)

        # Verify projects in database
        df_projects = pd.DataFrame(create_project_service(self.db_path).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(self.db_path).get_all_parameters())))
        self.assertEqual(len(df_projects), 15)
        self.assertTrue(all(isinstance(p_id, int) for p_id in df_projects["id"]))

        # Verify tasks per project
        for p_id in df_projects["id"]:
            tasks_df = planning_frames.tasks_frame(self.milestone_repo.get_milestones_by_project(p_id))
            self.assertGreaterEqual(len(tasks_df), 3)
            self.assertLessEqual(len(tasks_df), 8)

        # Verify dependencies existence
        with closing(get_db(self.db_path)) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM task_dependencies WHERE predecessor_project_id IS NOT NULL")
            ext_deps_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM task_dependencies WHERE predecessor_project_id IS NULL")
            int_deps_count = cursor.fetchone()[0]

            self.assertGreater(int_deps_count, 0)
            # Ext deps might be present with random seed
            cursor.execute("SELECT DISTINCT link_type FROM task_dependencies")
            link_types = {row[0] for row in cursor.fetchall()}
            self.assertTrue(any(lt in link_types for lt in ["FS", "SS", "FF", "SF"]))

    def test_flush_database_empties_all_tables(self) -> None:
        """Verify flush_database completely removes all projects, tasks, and dependencies."""
        # Seed initial data
        seed_database(
            num_projects=10,
            min_tasks_per_project=2,
            max_tasks_per_project=5,
            db_path=self.db_path,
            clean_first=False,
            random_seed=99,
        )

        # Verify data is present
        self.assertEqual(len(pd.DataFrame(create_project_service(self.db_path).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(self.db_path).get_all_parameters())))), 10)

        # Flush
        flush_res = flush_database(db_path=self.db_path)
        self.assertEqual(flush_res["projects_deleted"], 10)
        self.assertGreater(flush_res["tasks_deleted"], 0)
        self.assertGreater(flush_res["dependencies_deleted"], 0)

        # Verify database is now completely empty
        self.assertEqual(len(pd.DataFrame(create_project_service(self.db_path).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(self.db_path).get_all_parameters())))), 0)
        with closing(get_db(self.db_path)) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM project_task")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM task_dependencies")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_seed_database_with_zero_tasks(self) -> None:
        """Verify seed_database can create projects with 0 tasks without errors."""
        res = seed_database(
            num_projects=5,
            min_tasks_per_project=0,
            max_tasks_per_project=0,
            db_path=self.db_path,
            clean_first=True,
            random_seed=42,
        )

        self.assertEqual(res["projects_created"], 5)
        self.assertEqual(res["tasks_created"], 0)
        self.assertEqual(res["dependencies_created"], 0)

        df_projects = pd.DataFrame(create_project_service(self.db_path).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(self.db_path).get_all_parameters())))
        self.assertEqual(len(df_projects), 5)
        for p_id in df_projects["id"]:
            tasks_df = planning_frames.tasks_frame(self.milestone_repo.get_milestones_by_project(p_id))
            self.assertEqual(len(tasks_df), 0)


if __name__ == "__main__":
    unittest.main()
