"""Regression tests for lazy, current task-resource-pool dialogs."""

from app.presentation.components import resource_pool_frames

import datetime
import unittest
from unittest.mock import patch

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.application.services.business_access import BusinessAccess
from app.main import create_resource_pool_service
from app.runtime import RuntimeResources
from tests.postgresql.ui import runtime as runtime, access as access


def task_pool_app(resources: RuntimeResources, access: BusinessAccess, task_id: int = 1) -> None:
    """Render the real injected dialog against an isolated database."""
    from app.main import create_planning_workspace
    from app.presentation.pages.planning import _manage_task_resource_pools_dialog
    _manage_task_resource_pools_dialog(task_id, 'Test task', 1, create_planning_workspace(resources, access=access))


def project_pool_app(resources: RuntimeResources, access: BusinessAccess) -> None:
    """Render project allocation against the same many-pool fixture."""
    from app.main import create_planning_workspace
    from app.presentation.pages.planning import _manage_project_resource_pools_dialog
    _manage_project_resource_pools_dialog(1, 'Project', create_planning_workspace(resources, access=access))



class TaskPoolDialogTests(unittest.TestCase):
    """Keep modal reads bounded without hiding changes or breaking mutations."""

    def test_project_popup_batches_only_assigned_pools_and_reuses_the_result(self) -> None:
        from app.application.services.pool_capacity import PoolCapacityService
        with psycopg.connect(self.setup.operator_url) as conn:
            conn.execute('INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,project_plan_id) VALUES (1,1,0.5,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))')
        original = PoolCapacityService.get_details
        app = AppTest.from_function(project_pool_app, args=(self.resources, self.access))
        with patch.object(PoolCapacityService, 'get_details', autospec=True, side_effect=original) as reads:
            app.run()
            self.assert_healthy(app)
            self.assertEqual([call.args[1] for call in reads.call_args_list], [[1]])
            reads.reset_mock()
            app.number_input(key='ni_assign_proj_fte').set_value(1.5).run()
            app.radio(key='rb_assign_proj_period_mode').set_value('custom').run()
            self.assert_healthy(app)
            self.assertEqual(reads.call_count, 0)

    @pytest.fixture(autouse=True)
    def native_setup(self, authorized, runtime, access) -> None:
        """Create real tasks, duplicate assignments and many unrelated pools."""
        self.setup, self.resources, self.access = authorized.setup, runtime, access
        self.repo = create_resource_pool_service(runtime, access=access)
        with psycopg.connect(self.setup.operator_url) as conn, conn.cursor() as cursor:
            conn.execute("UPDATE eppm.project SET name='Project' WHERE id=1")
            cursor.executemany(
                'INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (%s,1,%s,%s,%s,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))',
                [(1, 'Assigned task', '2026-01-01', '2026-12-31'),
                 (2, 'Empty task', '2026-02-01', '2026-02-28')],
            )
            conn.execute(
                "INSERT INTO eppm.employee(employee_id,firstname,lastname,email) VALUES(1,'Test','Employee','test@example.invalid')"
            )
            cursor.executemany(
                'INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(%s,%s,%s)',
                [(1, 'Employee pool', 2), (2, 'Fallback pool', 3), (3, 'Zero pool', 0)]
                + [(pid, f'Unrelated pool {pid}', 4) for pid in range(5, 105)],
            )
            conn.execute(
                'INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) '
                "VALUES(1,'employee',1)"
            )
            cursor.executemany(
                'INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,project_plan_id) VALUES (1,1,1,%s,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))', [(0.25,), (0.25,)],
            )

    def app(self, task_id: int = 1) -> AppTest:
        """Build a dialog test session.

        Args:
            task_id: Selected task ID.

        Returns:
            Test session backed by the fixture database.
        """
        return AppTest.from_function(task_pool_app, args=(self.resources, self.access, task_id), default_timeout=30)

    def assert_healthy(self, app: AppTest) -> None:
        """Assert that the dialog rendered without a Streamlit exception.

        Args:
            app: Session whose latest run should be healthy.
        """
        self.assertEqual(list(app.exception), [])

    def test_cold_modal_calculates_only_displayed_statuses_and_reuses_them(self) -> None:
        """Unrelated cold pools never trigger capacity calculations."""
        from app.application.services.pool_capacity import PoolCapacityService
        _batch_calculate = PoolCapacityService.calculate_many

        app = self.app()
        with patch('app.application.services.pool_capacity.PoolCapacityService.calculate_many', autospec=True, side_effect=_batch_calculate) as calculate:
            app.run()
            self.assert_healthy(app)
            self.assertEqual([call.args[1] for call in calculate.call_args_list], [[1]])
        with patch('app.application.services.pool_capacity.PoolCapacityService.calculate_many',
                   side_effect=AssertionError('Modal recomputed capacity')):
            app.number_input(key='ni_assign_task_fte').set_value(1.5).run()
            app.radio(key='rb_assign_task_period_mode').set_value('custom').run()
            self.assert_healthy(app)
        self.assertEqual(len(app.selectbox[0].options), 103)
        self.assertIn('🏊 Zero pool (Cap: 0.00 FTE)', app.selectbox[0].options)
        self.assertEqual(sum('OK (Peak: 0.50 / Cap: 2.00 FTE)' in item.value for item in app.markdown), 2)

    def test_empty_task_needs_no_calculations_and_legacy_capacity_still_has_a_label(self) -> None:
        """Defined capacities are lightweight; unspecified capacities stay compatible."""
        app = self.app(2)
        with patch('app.application.services.pool_capacity.PoolCapacityService.calculate_many',
                   side_effect=AssertionError('Unassigned task calculated demand')):
            app.run()
            self.assert_healthy(app)
        with psycopg.connect(self.setup.operator_url) as conn:
            conn.execute("INSERT INTO eppm.resource_pool(id,name) VALUES(4,'Legacy pool')")
            conn.execute(
                'INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) '
                "VALUES(4,'employee',1)"
            )
        from app.application.services.pool_capacity import PoolCapacityService
        _batch_calculate = PoolCapacityService.calculate_many

        with patch('app.application.services.pool_capacity.PoolCapacityService.calculate_many', autospec=True, side_effect=_batch_calculate) as calculate:
            app.run()
            self.assert_healthy(app)
            self.assertEqual([call.args[1] for call in calculate.call_args_list], [[4]])
        self.assertIn('🏊 Legacy pool (Cap: 1.00 FTE)', app.selectbox[0].options)

    def test_external_calendar_and_assignment_changes_refresh_warnings(self) -> None:
        """A single zero-capacity day remains visible after a cached modal rerun."""
        app = self.app().run()
        with psycopg.connect(self.setup.operator_url) as conn:
            conn.execute(
                'INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) '
                "VALUES(1,'2026-06-15','2026-06-15',0)"
            )
            conn.execute("UPDATE eppm.resource_pool SET capacity_fte=5 WHERE id=2")
        app.run()
        self.assert_healthy(app)
        self.assertEqual(sum('Overassigned (Peak: 0.50' in item.value for item in app.markdown), 2)
        self.assertIn('🏊 Fallback pool (Cap: 5.00 FTE)', app.selectbox[0].options)
        with psycopg.connect(self.setup.operator_url) as conn:
            conn.execute('DELETE FROM eppm.resource_pool_assignment WHERE task_id=1')
        app.run()
        self.assert_healthy(app)
        self.assertFalse(any('Overassigned (Peak:' in item.value for item in app.markdown))
        self.assertEqual(len(app.info), 1)

    def test_assign_and_remove_preserve_full_task_dates_and_values(self) -> None:
        """An assignment is saved once with its values, then can be removed."""
        app = self.app().run()
        app.selectbox(key='sb_assign_task_pool').set_value((2, '🏊 Fallback pool (Cap: 3.00 FTE)'))
        app.number_input(key='ni_assign_task_fte').set_value(2.5)
        app.text_input(key='ti_assign_task_notes').set_value('  Test assignment  ')
        app.button(key='btn_confirm_assign_task_pool').click().run()
        self.assert_healthy(app)
        assignments = resource_pool_frames.assignments_frame(self.repo.get_assignments(task_id=1))
        self.assertEqual(len(assignments), 3)
        saved = assignments[assignments.pool_id == 2].iloc[0]
        self.assertEqual(saved.fte_assigned, 2.5)
        self.assertEqual(saved.notes, 'Test assignment')
        self.assertIsNone(saved.custom_start_date)
        self.assertIsNone(saved.custom_end_date)
        app.button(key=f'btn_del_assign_task_{int(saved.id)}').click().run()
        self.assert_healthy(app)
        self.assertEqual(len(resource_pool_frames.assignments_frame(self.repo.get_assignments(task_id=1))), 2)

    def test_relative_project_and_task_assignments_store_only_scheduling_parameters(self) -> None:
        """Both dialogs preview and save offsets without materializing dates."""
        for owner in ('task', 'proj'):
            app = self.app() if owner == 'task' else AppTest.from_function(project_pool_app, args=(self.resources, self.access))
            app.run()
            app.radio(key=f'rb_assign_{owner}_period_mode').set_value('relative').run()
            app.selectbox(key=f'assign_{owner}_anchor').set_value('end').run()
            app.number_input(key=f'assign_{owner}_offset').set_value(10).run()
            app.number_input(key=f'assign_{owner}_duration').set_value(5).run()
            self.assertTrue(any('2027-01-10' in item.value and '2027-01-14' in item.value for item in app.caption))
            app.button(key=f'btn_confirm_assign_{owner}_pool').click().run()
            self.assert_healthy(app)
            rows = self.repo.get_assignments(project_id=1)
            relative = [row for row in rows if row.get('schedule_anchor') == 'end' and (row['task_id'] is not None) == (owner == 'task')]
            self.assertEqual(len(relative), 1)
            self.assertIsNone(relative[0]['custom_start_date'])
            self.assertIsNone(relative[0]['custom_end_date'])
            self.assertEqual((relative[0]['offset_days'], relative[0]['duration_days']), (10, 5))

    def test_custom_dates_are_validated_and_saved(self) -> None:
        """Invalid ranges do not silently become full-duration assignments."""
        app = self.app().run()
        app.radio(key='rb_assign_task_period_mode').set_value('custom').run()
        app.date_input(key='di_assign_task_s').set_value(datetime.date(2026, 6, 20))
        app.date_input(key='di_assign_task_e').set_value(datetime.date(2026, 6, 10))
        app.button(key='btn_confirm_assign_task_pool').click().run()
        self.assert_healthy(app)
        self.assertTrue(app.error)
        self.assertEqual(len(resource_pool_frames.assignments_frame(self.repo.get_assignments(task_id=1))), 2)
        app.date_input(key='di_assign_task_e').set_value(datetime.date(2026, 6, 30))
        app.button(key='btn_confirm_assign_task_pool').click().run()
        self.assert_healthy(app)
        assignments = resource_pool_frames.assignments_frame(self.repo.get_assignments(task_id=1))
        self.assertEqual(len(assignments), 3)
        saved = assignments.iloc[-1]
        self.assertEqual(saved.custom_start_date, '2026-06-20')
        self.assertEqual(saved.custom_end_date, '2026-06-30')


if __name__ == '__main__':
    unittest.main()
