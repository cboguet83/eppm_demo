"""Repository workflows through native PostgreSQL services and actors."""

import unittest

import pandas as pd
import psycopg
import pytest

from app.application.services.business_access import BusinessAccess
from app.main import create_planning_service, create_project_service, create_schema_service
from app.presentation.components import planning_frames, schema_frames
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access

class TestRepositories(unittest.TestCase):
    """Test suite for create_schema_service, create_project_service, and create_planning_service."""

    @pytest.fixture(autouse=True)
    def native_setup(
        self, authorized: AuthorizedFixture, runtime: RuntimeResources,
        access: BusinessAccess,
    ) -> None:
        """Use a real business-admin session and an isolated PostgreSQL database."""
        self.authorized = authorized
        self.resources = runtime
        self.access = access
        self.schema_repo = create_schema_service(runtime, access=access)
        self.project_repo = create_project_service(runtime, access=access)
        self.milestone_repo = create_planning_service(runtime, access=access)

    def test_schema_group_crud(self) -> None:
        """Verify creating, editing, and deleting a schema group."""
        # Create
        grp_id = self.schema_repo.create_group("Finance & Risk", 1)
        self.assertGreater(grp_id, 0)

        # Read
        df = schema_frames.groups_frame(self.schema_repo.get_all_groups())
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["group_name"], "Finance & Risk")

        # Update
        updated = self.schema_repo.update_group(grp_id, "Finance & Compliance", 5)
        self.assertTrue(updated)

        df_updated = schema_frames.groups_frame(self.schema_repo.get_all_groups())
        self.assertEqual(df_updated.iloc[0]["group_name"], "Finance & Compliance")
        self.assertEqual(df_updated.iloc[0]["display_order"], 5)

        # Delete
        deleted = self.schema_repo.delete_group(grp_id)
        self.assertTrue(deleted)
        self.assertTrue(schema_frames.groups_frame(self.schema_repo.get_all_groups()).empty)

    def test_schema_parameter_and_option_crud(self) -> None:
        """Verify creating parameters (grouped & ungrouped) and managing discrete options."""
        grp_id = self.schema_repo.create_group("Technical", 1)

        # Grouped parameter
        p1 = self.schema_repo.create_parameter("PRM_001", grp_id, "Cloud Provider", "ENUM")
        self.assertTrue(p1)

        # Ungrouped parameter (group_id is None)
        p2 = self.schema_repo.create_parameter("PRM_002", None, "Tags", 'TAGS')
        self.assertTrue(p2)

        # Add discrete options
        opt1 = self.schema_repo.add_option("PRM_001", "AWS", 1)
        opt2 = self.schema_repo.add_option("PRM_001", "GCP", 2)
        self.assertGreater(opt1, 0)
        self.assertGreater(opt2, 0)

        df_opts = schema_frames.options_frame(self.schema_repo.get_all_options())
        self.assertEqual(len(df_opts), 2)

        # Delete option
        self.schema_repo.delete_option(opt1)
        df_opts_after = schema_frames.options_frame(self.schema_repo.get_all_options())
        self.assertEqual(len(df_opts_after), 1)

        # Delete parameter
        self.schema_repo.delete_parameter("PRM_001")
        df_params = schema_frames.parameters_frame(self.schema_repo.get_all_parameters())
        self.assertEqual(len(df_params), 1)
        self.assertEqual(df_params.iloc[0]["param_id"], "PRM_002")

    def test_project_crud_and_cascade(self) -> None:
        """Verify project creation, update, query, and cascade deletion."""
        self.schema_repo.create_parameter("PRM_001", None, "Test value", "TEXT")
        # Create project
        created = self.project_repo.create_project(
            project_id=100,
            name="Modernization Core",
            status='In Progress',
            planned_budget=250000,
            actual_budget=100000,
            dynamic_attributes={"PRM_001": "Value"},
        )
        self.assertTrue(created)
        self.assertTrue(self.project_repo.exists(100))
        loaded_project = self.project_repo.get_project_by_id(100)
        self.assertIsNotNone(loaded_project)
        self.assertEqual(loaded_project.id, 100)
        self.assertEqual(loaded_project.name, "Modernization Core")
        self.assertEqual(loaded_project.dynamic_attributes, {"PRM_001": "Value"})
        self.assertIsNone(self.project_repo.get_project_by_id(999999))

        # Create step 1
        s1_id = self.milestone_repo.create_milestone(
            project_id=100,
            task_name="Sprint 1",
            phase="Phase 1",
            start_date="2026-01-01",
            end_date="2026-01-15",
            progress_pct=100,
        )
        self.assertGreater(s1_id, 0)

        # Create milestone step 2 with predecessor = s1_id and start_date == end_date
        s2_id = self.milestone_repo.create_milestone(
            project_id=100,
            task_name="Sprint 1 Sign-Off",
            phase="Phase 1",
            start_date="2026-01-15",
            end_date="2026-01-15",
            progress_pct=100,
            predecessor_id=s1_id,
        )
        self.assertGreater(s2_id, 0)

        df_steps = planning_frames.tasks_frame(self.milestone_repo.get_milestones_by_project(100))
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

        df_after_update = planning_frames.tasks_frame(self.milestone_repo.get_milestones_by_project(100))
        s1_updated_row = df_after_update[df_after_update["id"] == s1_id].iloc[0]
        self.assertEqual(s1_updated_row["start_date"], "2026-01-05")
        self.assertEqual(s1_updated_row["end_date"], "2026-01-20")
        self.assertEqual(s1_updated_row["progress_pct"], 80)

        # Delete project and verify milestone cascade
        self.project_repo.delete_project(100)
        self.assertFalse(self.project_repo.exists(100))
        self.assertTrue(planning_frames.tasks_frame(self.milestone_repo.get_milestones_by_project(100)).empty)

    def test_bulk_create_milestones(self) -> None:
        """Verify bulk insertion of step records with predecessors."""
        self.project_repo.create_project(200, "Bulk Proj", "Draft", 0, 0, {})

        payload = [
            {"project_id": 200, "task_name": "T1", "phase": "P1", "start_date": "2026-01-01", "end_date": "2026-01-10", "progress_pct": 0, "predecessor_id": None},
            {"project_id": 200, "task_name": "T2", "phase": "P1", "start_date": "2026-01-11", "end_date": "2026-01-20", "progress_pct": 50, "predecessor_id": 1},
        ]
        inserted = self.milestone_repo.bulk_create_milestones(payload)
        self.assertEqual(inserted, 2)

        df_ms = planning_frames.tasks_frame(self.milestone_repo.get_milestones_by_project(200))
        self.assertEqual(len(df_ms), 2)

    def test_multi_dependencies_and_bounds(self) -> None:
        """Verify multi-predecessors, external dependencies, and project date bounds."""
        self.project_repo.create_project(301, "Source Project", "Active", 0, 0, {})
        self.project_repo.create_project(302, "Target Project", "Active", 0, 0, {})

        # Add steps to PRJ-301
        p301_s1 = self.milestone_repo.create_milestone(301, "Feasibility", "Phase 1", "2026-03-01", "2026-03-10", 100)
        p301_s2 = self.milestone_repo.create_milestone(301, "Architecture", "Phase 1", "2026-03-11", "2026-03-25", 100)

        # Verify date bounds for PRJ-301
        min_d, max_d = self.milestone_repo.get_project_date_bounds(301)
        self.assertEqual(min_d, "2026-03-01")
        self.assertEqual(max_d, "2026-03-25")

        # Add step to PRJ-302 with multi-dependencies: 1 external whole project and 1 external task
        p302_s1 = self.milestone_repo.create_milestone(
            302,
            "Execution Step",
            "Phase 2",
            "2026-03-26",
            "2026-04-10",
            0,
            dependencies=[
                {"predecessor_task_id": None, "predecessor_project_id": 301, "link_type": "FS", "lag_days": 1},
                {"predecessor_task_id": p301_s2, "predecessor_project_id": 301, "link_type": "SS", "lag_days": 5},
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
            [{"predecessor_task_id": p301_s1, "predecessor_project_id": 301, "link_type": "FF", "lag_days": 2}],
        )
        updated_deps = self.milestone_repo.get_task_dependencies(p302_s1)
        self.assertEqual(len(updated_deps), 1)
        self.assertEqual(updated_deps[0]["link_type"], "FF")
        self.assertEqual(updated_deps[0]["lag_days"], 2)

    def test_batch_milestone_queries(self) -> None:
        """Verify batch query methods across multiple projects."""
        self.project_repo.update_project(1, "Batch 1", "Active", 0, 0, {})
        self.project_repo.update_project(2, "Batch 2", "Active", 0, 0, {})

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
        batch_df = planning_frames.tasks_frame(self.milestone_repo.get_milestones_for_projects([1, 2]))
        self.assertEqual(len(batch_df), 3)

        # 4. Batch dependencies for projects
        batch_deps = self.milestone_repo.get_dependencies_for_projects([1, 2])
        self.assertEqual(len(batch_deps), 1)
        self.assertEqual(batch_deps[0]["task_id"], m3)
        self.assertEqual(batch_deps[0]["predecessor_task_id"], m1)

        # 5. Get all milestones across all projects
        all_milestones = planning_frames.tasks_frame(self.milestone_repo.get_all_milestones(), project_labels=True)
        self.assertEqual(len(all_milestones), 3)
        self.assertIn("project_name", all_milestones.columns)
        self.assertEqual(all_milestones.iloc[0]["project_name"], "Batch 1")

    def test_project_manager_foreign_key_crud(self) -> None:
        """Verify creating, reading, and updating a project with function_id (Project Manager)."""
        with psycopg.connect(self.authorized.setup.operator_url) as conn, conn.cursor() as cursor:
            cursor.execute("INSERT INTO eppm.function_type (function_type_id, function_type) VALUES (1, 'Chef de Projet')")
            cursor.execute("INSERT INTO eppm.function (function_id, name, function_type_id) VALUES (10, 'Alice PM', 1)")
            cursor.execute("INSERT INTO eppm.function (function_id, name, function_type_id) VALUES (20, 'Bob PM', 1)")

        # Create project with function_id 10
        created = self.project_repo.create_project(
            project_id=101,
            name="PM Test Project",
            status="Active",
            planned_budget=10000,
            actual_budget=5000,
            dynamic_attributes={},
            function_id=10,
        )
        self.assertTrue(created)

        # Read project
        parameter_ids = tuple(parameter.param_id for parameter in self.schema_repo.get_all_parameters())
        df = pd.DataFrame(self.project_repo.get_planning_catalog(parameter_ids))
        proj = df[df["id"] == 101].iloc[0]
        self.assertEqual(proj["function_id"], 10)

        # Update project with function_id 20
        updated = self.project_repo.update_project(
            project_id=101,
            name="PM Test Project Updated",
            status="Completed",
            planned_budget=12000,
            actual_budget=6000,
            dynamic_attributes={},
            function_id=20,
        )
        self.assertTrue(updated)

        df_updated = pd.DataFrame(self.project_repo.get_planning_catalog(parameter_ids))
        proj_updated = df_updated[df_updated["id"] == 101].iloc[0]
        self.assertEqual(proj_updated["function_id"], 20)

    def test_schema_parameter_mandatory_and_alias_crud(self) -> None:
        """Verify creating and updating schema parameters with mandatory and alias flags."""
        # Create parameter with mandatory=True and custom alias
        created = self.schema_repo.create_parameter(
            param_id="PRM_999",
            param_name="Code Line",
            param_type="ENUM",
            group_id=None,
            mandatory=True,
            alias="code ligne",
        )
        self.assertTrue(created)

        # Read parameter
        df = schema_frames.parameters_frame(self.schema_repo.get_all_parameters())
        row = df[df["param_id"] == "PRM_999"].iloc[0]
        self.assertTrue(bool(row["mandatory"]))
        self.assertEqual(row["alias"], "code ligne")

        # Update parameter
        updated = self.schema_repo.update_parameter(
            param_id="PRM_999",
            param_name="Code Line Updated",
            param_type="ENUM",
            group_id=None,
            mandatory=False,
            alias="code ligne updated",
        )
        self.assertTrue(updated)

        df_updated = schema_frames.parameters_frame(self.schema_repo.get_all_parameters())
        row_updated = df_updated[df_updated["param_id"] == "PRM_999"].iloc[0]
        self.assertFalse(bool(row_updated["mandatory"]))
        self.assertEqual(row_updated["alias"], "code ligne updated")


if __name__ == "__main__":
    unittest.main()
