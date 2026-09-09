"""Regression coverage for planning fast paths without stale or missing data."""

from app.domain.resources.capacity_rules import calculate_pool_scope_daily_usage
from app.presentation.components.planning_catalog import _build_function_lookup
from app.presentation.components.planning_catalog import enrich_projects_with_organization

from app.presentation.components import planning_frames

from contextlib import closing

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from app.infrastructure.database.seeder import seed_default_data_if_empty
from app.main import create_planning_service
from app.main import create_pool_capacity_service, create_resource_pool_service


def planning_app(db_path):
    from app.main import create_planning_workspace
    from app.presentation.pages.planning import render_planning_milestones
    render_planning_milestones(create_planning_workspace(db_path))



class PlanningPerformanceTests(unittest.TestCase):
    def test_catalog_reads_only_requested_properties_and_invalidates_after_edits(self):
        from app.main import create_project_service
        from app.main import create_schema_service
        from app.infrastructure.repositories.portfolio import portfolio_revision
        from app.presentation.components.planning_data import load_planning_catalog, load_dependency_choices
        from app.main import create_planning_workspace
        from app.infrastructure.database.connection import get_db
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'lazy.db')
            seed_default_data_if_empty(path)
            schema = create_schema_service(path)
            schema.create_parameter('custom_lazy', None, 'Lazy property', 'TEXT')
            repo = create_project_service(path)
            pid = repo.create_project(name='Lazy project', dynamic_attributes={'custom_lazy': 'Present'})
            revision = portfolio_revision(path)
            workspace = create_planning_workspace(path)
            projects, frame, _, _ = load_planning_catalog(workspace, revision)
            self.assertTrue(all(not values for values in projects.dynamic_attributes))
            self.assertNotIn('custom_lazy', frame.columns)
            _, filtered, _, _ = load_planning_catalog(workspace, revision, ('custom_lazy',))
            self.assertEqual(filtered[filtered.id == pid].iloc[0]['custom_lazy'], 'Present')
            repo.update_project(pid, 'Changed', 'Draft', 0, 0, {'custom_lazy': 'Updated'})
            _, updated, _, _ = load_planning_catalog(workspace, portfolio_revision(path), ('custom_lazy',))
            self.assertEqual(updated[updated.id == pid].iloc[0]['custom_lazy'], 'Updated')
            first_project = int(projects.iloc[0].id)
            choices = load_dependency_choices(workspace, portfolio_revision(path), first_project)
            expected = planning_frames.tasks_frame(create_planning_service(path).get_milestones_for_projects([first_project])).id.tolist()
            self.assertEqual([r['id'] for r in choices], expected)
            with closing(get_db(path)) as conn, conn:
                indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertIn('idx_planning_task_project', indexes)
            self.assertIn('idx_planning_dependency_task', indexes)

    def test_planning_never_eagerly_loads_all_properties_or_external_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.db')
            seed_default_data_if_empty(path)
            app = AppTest.from_function(planning_app, args=(path,))
            from app.infrastructure.repositories.projects import SqliteProjectGateway
            original_catalog = SqliteProjectGateway.read_planning_catalog
            def bounded_catalog(reader, property_ids=None):
                self.assertIsNotNone(property_ids, 'Planning requested all property values')
                return original_catalog(reader, property_ids)
            with patch.object(SqliteProjectGateway, 'read_planning_catalog', new=bounded_catalog):
                with patch('app.application.services.planning.PlanningService.get_all_external_tasks_map', side_effect=AssertionError('All tasks')):
                    with patch('app.presentation.pages.planning._interactive_gantt', return_value=None) as component:
                        app.session_state['ms_multi_projects'] = [1]
                        app.run()
                        self.assertEqual(list(app.exception), [])
                        self.assertEqual(component.call_args.kwargs['external_tasks'], {})
                        self.assertTrue(all(t['project_id'] == '1' for t in component.call_args.kwargs['tasks']))

    def test_hierarchy_index_is_built_once_and_loops_are_safe(self):
        functions = pd.DataFrame([
            {"function_id": 1, "name": "Director", "hierarchy_level": 2, "manager_function_id": None},
            {"function_id": 2, "name": "Service", "hierarchy_level": 3, "manager_function_id": 1},
            {"function_id": 3, "name": "Manager", "hierarchy_level": 4, "manager_function_id": 2},
            {"function_id": 4, "name": "Loop", "hierarchy_level": 4, "manager_function_id": 4},
        ])
        projects = pd.DataFrame({"function_id": [1, 2, 3, 4, None, 99] * 100})
        employees = pd.DataFrame([{"function_id": 3, "firstname": "Ada", "lastname": "Lovelace"}])
        with patch("app.presentation.components.planning_catalog._build_function_lookup",
                          wraps=_build_function_lookup) as build:
            result = enrich_projects_with_organization(projects, functions, employees)
        build.assert_called_once()
        self.assertEqual(result["level_3_manager_name"].tolist()[:6], ["—", "Service", "Service", "—", "—", "—"])
        self.assertEqual(result["project_manager"].iloc[2], "Ada Lovelace")
        self.assertEqual(result["project_manager"].iloc[1], "Service")

    def test_full_scope_reuses_cache_and_filtered_scope_stays_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "test.db")
            seed_default_data_if_empty(path)
            details = {d.pool_id: d for d in create_pool_capacity_service(path).get_details([pool.id for pool in create_resource_pool_service(path).get_all_pools()])}
            app = AppTest.from_function(planning_app, args=(path,))
            with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
                with patch("app.presentation.pages.planning.calculate_pool_scope_daily_usage",
                                  side_effect=AssertionError("Recomputed full scope")):
                    app.run()
                    self.assertEqual(list(app.exception), [])
                payload = component.call_args.kwargs
                self.assertEqual(payload["external_tasks"], {})
                for pool in payload["resource_pools"]:
                    self.assertEqual(pool["selected_projects_daily_usage_intervals"], pool["daily_usage_intervals"])

                self.assertEqual(payload['tasks'], [])
                project_id = int(payload['project_summaries'][0]['id'])
                app.session_state["ms_multi_projects"] = [project_id]
                app.run()
                self.assertEqual(list(app.exception), [])
                payload = component.call_args.kwargs
                self.assertNotIn(str(project_id), payload["external_tasks"])
                self.assertEqual(payload["external_tasks"], {})  # editor choices are lazy
                for pool in payload["resource_pools"]:
                    detail = details[pool["id"]]
                    expected = calculate_pool_scope_daily_usage(detail.assignments, [project_id])
                    from app.presentation.components.planning_transport import pack_pool_payloads
                    self.assertEqual(pool["selected_projects_daily_usage_intervals"],
                                     pack_pool_payloads([{'selected_projects_daily_usage': expected}])[0]['selected_projects_daily_usage_intervals'])

    def test_external_tasks_exclusion_retains_unselected_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "test.db")
            seed_default_data_if_empty(path)
            repo = create_planning_service(path)
            all_tasks = repo.get_all_external_tasks_map()
            excluded = list(all_tasks)[0]
            expected = {pid: tasks for pid, tasks in all_tasks.items() if pid != excluded}
            self.assertEqual(repo.get_all_external_tasks_map([excluded]), expected)
            self.assertEqual(repo.get_all_external_tasks_map([]), all_tasks)
