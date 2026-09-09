"""Regression tests for lazy, current task-resource-pool dialogs."""

from app.presentation.components import resource_pool_frames

from contextlib import closing

import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.infrastructure.database.schema_init import init_db
from app.main import create_resource_pool_service


def task_pool_app(db_path: str, task_id: int = 1) -> None:
    """Render the real injected dialog against an isolated database."""
    from app.main import create_planning_workspace
    from app.presentation.pages.planning import _manage_task_resource_pools_dialog
    _manage_task_resource_pools_dialog(task_id, 'Test task', 1, create_planning_workspace(db_path))



class TaskPoolDialogTests(unittest.TestCase):
    """Keep modal reads bounded without hiding changes or breaking mutations."""

    def setUp(self) -> None:
        """Create real tasks, duplicate assignments and many unrelated pools."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name) / 'dialog.db')
        init_db(self.path)
        self.repo = create_resource_pool_service(self.path)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO project(id,name) VALUES(1,'Project')")
            conn.executemany(
                'INSERT INTO project_task(id,project_id,task_name,start_date,end_date) '
                'VALUES(?,1,?,?,?)',
                [(1, 'Assigned task', '2026-01-01', '2026-12-31'),
                 (2, 'Empty task', '2026-02-01', '2026-02-28')],
            )
            conn.execute(
                'INSERT INTO employee(employee_id,firstname,lastname,email,employee_code) '
                "VALUES(1,'Test','Employee','test@example.invalid','TEST')"
            )
            conn.executemany(
                'INSERT INTO resource_pool(id,name,capacity_fte) VALUES(?,?,?)',
                [(1, 'Employee pool', 2), (2, 'Fallback pool', 3), (3, 'Zero pool', 0)]
                + [(pid, f'Unrelated pool {pid}', 4) for pid in range(5, 105)],
            )
            conn.execute(
                'INSERT INTO resource_pool_mapping(pool_id,target_type,target_id) '
                "VALUES(1,'employee',1)"
            )
            conn.executemany(
                'INSERT INTO resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) '
                'VALUES(1,1,1,?)', [(0.25,), (0.25,)],
            )

    def app(self, task_id: int = 1) -> AppTest:
        """Build a dialog test session.

        Args:
            task_id: Selected task ID.

        Returns:
            Test session backed by the fixture database.
        """
        return AppTest.from_function(task_pool_app, args=(self.path, task_id), default_timeout=30)

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
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO resource_pool(id,name) VALUES(4,'Legacy pool')")
            conn.execute(
                'INSERT INTO resource_pool_mapping(pool_id,target_type,target_id) '
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
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                'INSERT INTO employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) '
                "VALUES(1,'2026-06-15','2026-06-15',0)"
            )
            conn.execute("UPDATE resource_pool SET capacity_fte=5 WHERE id=2")
        app.run()
        self.assert_healthy(app)
        self.assertEqual(sum('Overassigned (Peak: 0.50' in item.value for item in app.markdown), 2)
        self.assertIn('🏊 Fallback pool (Cap: 5.00 FTE)', app.selectbox[0].options)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('DELETE FROM resource_pool_assignment WHERE task_id=1')
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
