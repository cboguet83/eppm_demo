"""Native planning property projection, lazy reads and exact scoped capacity."""

from pathlib import Path
import unittest
from unittest.mock import patch

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.application.services.business_access import BusinessAccess
from app.domain.resources.capacity_rules import calculate_pool_scope_daily_usage
from app.infrastructure.postgresql.backup import PostgresTools
from app.infrastructure.postgresql.projects import PostgresProjectGateway
from app.main import create_planning_service, create_planning_workspace, create_pool_capacity_service, create_project_service, create_resource_pool_service
from app.operator_services import create_maintenance_service
from app.presentation.components import planning_frames
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import native_screen, runtime as runtime, access as access


def planning_app(runtime: RuntimeResources, access: BusinessAccess) -> AppTest:
    """Mount the actual planning page using native resources and actor context."""
    return native_screen("""
from app.main import create_planning_workspace
from app.presentation.pages.planning import render_planning_milestones
render_planning_milestones(create_planning_workspace(runtime, access=access))
""", runtime, access)


class PlanningPerformanceTests(unittest.TestCase):
    """Exercise the original demo's planning behavior using real PostgreSQL reads."""

    @pytest.fixture(autouse=True)
    def native_setup(
        self, runtime: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
        clients: PostgresTools, tmp_path: Path,
    ) -> None:
        """Seed the isolated native demo through the archive-protected operator path."""
        with psycopg.connect(authorized.setup.operator_url) as connection:
            connection.execute("DELETE FROM eppm.project")
        create_maintenance_service(
            authorized.setup.operator_url, backup_directory=tmp_path, archive_tools=clients,
        ).seed_defaults()
        self.resources = runtime
        self.access = access
        self.authorized = authorized

    def test_catalog_reads_only_requested_properties_and_invalidates_after_edits(self):
        from app.main import create_project_service
        from app.main import create_schema_service
        from app.presentation.components.planning_data import load_planning_catalog, load_dependency_choices
        from app.main import create_planning_workspace
        schema = create_schema_service(self.resources, access=self.access)
        schema.create_parameter('custom_lazy', None, 'Lazy property', 'TEXT')
        repo = create_project_service(self.resources, access=self.access)
        pid = repo.create_project(name='Lazy project', dynamic_attributes={'custom_lazy': 'Present'})
        revision = create_planning_workspace(self.resources, access=self.access).revision()
        workspace = create_planning_workspace(self.resources, access=self.access)
        projects, frame, _, _ = load_planning_catalog(workspace, revision)
        self.assertTrue(all(not values for values in projects.dynamic_attributes))
        self.assertNotIn('custom_lazy', frame.columns)
        _, filtered, _, _ = load_planning_catalog(workspace, revision, ('custom_lazy',))
        self.assertEqual(filtered[filtered.id == pid].iloc[0]['custom_lazy'], 'Present')
        repo.update_project(pid, 'Changed', 'Draft', 0, 0, {'custom_lazy': 'Updated'})
        _, updated, _, _ = load_planning_catalog(workspace, create_planning_workspace(self.resources, access=self.access).revision(), ('custom_lazy',))
        self.assertEqual(updated[updated.id == pid].iloc[0]['custom_lazy'], 'Updated')
        first_project = int(projects.iloc[0].id)
        choices = load_dependency_choices(workspace, create_planning_workspace(self.resources, access=self.access).revision(), first_project)
        expected = planning_frames.tasks_frame(create_planning_service(self.resources, access=self.access).get_milestones_for_projects([first_project])).id.tolist()
        self.assertEqual([r['id'] for r in choices], expected)
        with psycopg.connect(self.authorized.setup.operator_url) as conn:
            indexes = {r[0] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE schemaname='eppm'")}
        self.assertIn('planning_task_project', indexes)
        self.assertIn('planning_dependency_task', indexes)


    def test_planning_never_eagerly_loads_all_properties_or_external_tasks(self):
        app = planning_app(self.resources, self.access)
        original_catalog = PostgresProjectGateway.read_planning_catalog
        def bounded_catalog(reader, property_ids=None):
            self.assertIsNotNone(property_ids, 'Planning requested all property values')
            return original_catalog(reader, property_ids)
        with patch.object(PostgresProjectGateway, 'read_planning_catalog', new=bounded_catalog):
            with patch('app.application.services.planning.PlanningService.get_all_external_tasks_map', side_effect=AssertionError('All tasks')):
                with patch('app.presentation.pages.planning._interactive_gantt', return_value=None) as component:
                    selected = create_project_service(self.resources, access=self.access).get_planning_catalog()[0]['id']
                    app.session_state['ms_multi_projects'] = [selected]
                    app.run()
                    self.assertEqual(list(app.exception), [])
                    self.assertEqual(component.call_args.kwargs['external_tasks'], {})
                    self.assertTrue(all(t['project_id'] == str(selected) for t in component.call_args.kwargs['tasks']))


    def test_full_scope_reuses_cache_and_filtered_scope_stays_exact(self):
        details = {d.pool_id: d for d in create_pool_capacity_service(self.resources, access=self.access).get_details([pool.id for pool in create_resource_pool_service(self.resources, access=self.access).get_all_pools()])}
        app = planning_app(self.resources, self.access)
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
        repo = create_planning_service(self.resources, access=self.access)
        all_tasks = repo.get_all_external_tasks_map()
        excluded = list(all_tasks)[0]
        expected = {pid: tasks for pid, tasks in all_tasks.items() if pid != excluded}
        self.assertEqual(repo.get_all_external_tasks_map([int(excluded)]), expected)
        self.assertEqual(repo.get_all_external_tasks_map([]), all_tasks)
