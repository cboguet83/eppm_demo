"""Regression coverage for planning fast paths without stale or missing data."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.database.seeder import seed_default_data_if_empty
from src.repositories.milestone_repo import MilestoneRepository
from src.services.pool_capacity_cache import load_pool_capacities
from src.services.resource_pool_service import ResourcePoolService


def planning_app(db_path):
    from src.repositories.project_repo import ProjectRepository
    from src.repositories.milestone_repo import MilestoneRepository
    from src.repositories.tag_repo import TagRepository
    from src.repositories.resource_pool_repo import ResourcePoolRepository
    from src.repositories.organization_repo import OrganizationRepository
    from src.repositories.schema_repo import SchemaRepository
    from src.views.planning_view import render_planning_milestones
    render_planning_milestones(
        ProjectRepository(db_path), MilestoneRepository(db_path), TagRepository(db_path),
        ResourcePoolRepository(db_path), OrganizationRepository(db_path), SchemaRepository(db_path),
    )


class PlanningPerformanceTests(unittest.TestCase):
    def test_hierarchy_index_is_built_once_and_loops_are_safe(self):
        # app.py reloads service modules during integration tests.
        from src.services.organization_service import OrganizationService
        functions = pd.DataFrame([
            {"function_id": 1, "name": "Director", "hierarchy_level": 2, "manager_function_id": None},
            {"function_id": 2, "name": "Service", "hierarchy_level": 3, "manager_function_id": 1},
            {"function_id": 3, "name": "Manager", "hierarchy_level": 4, "manager_function_id": 2},
            {"function_id": 4, "name": "Loop", "hierarchy_level": 4, "manager_function_id": 4},
        ])
        projects = pd.DataFrame({"function_id": [1, 2, 3, 4, None, 99] * 100})
        employees = pd.DataFrame([{"function_id": 3, "firstname": "Ada", "lastname": "Lovelace"}])
        with patch.object(OrganizationService, "_build_function_lookup",
                          wraps=OrganizationService._build_function_lookup) as build:
            result = OrganizationService.enrich_projects_with_organization(projects, functions, employees)
        build.assert_called_once()
        self.assertEqual(result["level_3_manager_name"].tolist()[:6], ["—", "Service", "Service", "—", "—", "—"])
        self.assertEqual(result["project_manager"].iloc[2], "Ada Lovelace")
        self.assertEqual(result["project_manager"].iloc[1], "Service")

    def test_full_scope_reuses_cache_and_filtered_scope_stays_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "test.db")
            seed_default_data_if_empty(path)
            details = {d.pool_id: d for d in load_pool_capacities(path, details=True)}
            app = AppTest.from_function(planning_app, args=(path,))
            with patch("src.views.planning_view._interactive_gantt", return_value=None) as component:
                with patch.object(ResourcePoolService, "calculate_pool_scope_daily_usage",
                                  side_effect=AssertionError("Recomputed full scope")):
                    app.run()
                    self.assertEqual(list(app.exception), [])
                payload = component.call_args.kwargs
                self.assertEqual(payload["external_tasks"], {})
                for pool in payload["resource_pools"]:
                    self.assertEqual(pool["selected_projects_daily_usage"], pool["daily_usage"])
                    self.assertEqual(pool["selected_projects_overallocated_dates"], pool["overallocated_dates"])

                project_id = int(payload["tasks"][0]["project_id"])
                app.session_state["ms_multi_projects"] = [project_id]
                app.run()
                self.assertEqual(list(app.exception), [])
                payload = component.call_args.kwargs
                self.assertNotIn(str(project_id), payload["external_tasks"])
                self.assertTrue(payload["external_tasks"])
                for pool in payload["resource_pools"]:
                    detail = details[pool["id"]]
                    expected = ResourcePoolService.calculate_pool_scope_daily_usage(detail.assignments, [project_id])
                    self.assertEqual(pool["selected_projects_daily_usage"], expected)
                    violations = ResourcePoolService.calculate_daily_overassignments(
                        expected, detail.effective_capacity_fte,
                        detail.daily_assigned_capacity if detail.has_assigned_resources else {},
                    )
                    self.assertEqual(pool["selected_projects_overallocated_dates"], [v.date for v in violations])

    def test_external_tasks_exclusion_retains_unselected_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "test.db")
            seed_default_data_if_empty(path)
            repo = MilestoneRepository(path)
            all_tasks = repo.get_all_external_tasks_map()
            excluded = list(all_tasks)[0]
            expected = {pid: tasks for pid, tasks in all_tasks.items() if pid != excluded}
            self.assertEqual(repo.get_all_external_tasks_map([excluded]), expected)
            self.assertEqual(repo.get_all_external_tasks_map([]), all_tasks)
