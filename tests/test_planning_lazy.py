"""Planning summary, bounded hydration and targeted edit regression tests."""

import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from src.database.seeder import seed_default_data_if_empty
from src.repositories.project_repo import ProjectRepository
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.portfolio_repo import portfolio_revision
from src.services.planning_data import ensure_planning_indexes, load_project_summaries


def lazy_app(db_path):
    import streamlit as st
    from src.repositories.project_repo import ProjectRepository
    from src.repositories.milestone_repo import MilestoneRepository
    from src.views.planning_view import render_planning_milestones, _handle_gantt_component_change
    event = st.session_state.pop('test_event', None)
    if event:
        st.session_state['planning_lazy_gantt'] = event
        _handle_gantt_component_change('planning_lazy_gantt', MilestoneRepository(db_path))
    render_planning_milestones(ProjectRepository(db_path), MilestoneRepository(db_path))


class LazyPlanningTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / 'test.db')
        seed_default_data_if_empty(self.path)
        self.projects = ProjectRepository(self.path)
        self.tasks = MilestoneRepository(self.path)
        self.pids = [self.projects.create_project(name='Lazy '+str(i), dynamic_attributes={}) for i in range(3)]
        self.a = self.tasks.create_milestone(self.pids[0], 'Predecessor', 'General', '2026-01-01', '2026-01-10', 0)
        self.b = self.tasks.create_milestone(self.pids[1], 'Successor', 'General', '2026-01-05', '2026-01-06', 0,
            dependencies=[{'predecessor_task_id':self.a, 'link_type':'FS','lag_days':0}])
        self.c = self.tasks.create_milestone(self.pids[2], 'Unrelated', 'General', '2026-02-01', '2026-02-02', 0)

    def test_persistent_summaries_invalidate_the_project_and_linked_successors(self):
        ensure_planning_indexes(self.path)
        rows = load_project_summaries(self.path, portfolio_revision(self.path), tuple(self.pids))
        self.assertTrue(next(p for p in rows if p['id']==self.pids[1])['hasViolations'])
        self.tasks.update_dates(self.a, '2026-01-01', '2026-01-03')
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT project_id FROM planning_summary_cache').fetchall(), [(self.pids[2],)])
        rows = load_project_summaries(self.path, portfolio_revision(self.path), tuple(self.pids))
        self.assertFalse(next(p for p in rows if p['id']==self.pids[1])['hasViolations'])

    def test_summary_first_hydration_and_edit_patch_never_resend_unrelated_projects(self):
        app = AppTest.from_function(lazy_app, args=(self.path,), default_timeout=30)
        app.session_state['ms_multi_projects'] = self.pids
        with patch('src.views.planning_view._interactive_gantt', return_value=None) as component:
            app.run()
            self.assertEqual(list(app.exception), [])
            initial = component.call_args.kwargs
            self.assertEqual(initial['tasks'], [])
            self.assertEqual(len(initial['project_summaries']), 3)
            token = initial['scope_token']
            app.session_state['test_event'] = {'action':'load_project_tasks','project_ids':self.pids,'scope_token':token,'nonce':'load'}
            app.run()
            self.assertEqual(list(app.exception), [])
            payload = component.call_args.kwargs['patch']
            self.assertEqual(len(payload['tasks']), 3)
            app.session_state['test_event'] = {'action':'update_dates','id':self.a,'start_date':'2026-01-01','end_date':'2026-01-03','nonce':'move'}
            with patch.object(MilestoneRepository,'get_milestones_for_projects', wraps=self.tasks.get_milestones_for_projects) as reads:
                app.run()
                self.assertEqual(list(app.exception), [])
                touched = {pid for call in reads.call_args_list for pid in call.args[0]}
                self.assertNotIn(self.pids[2], touched)
            payload = component.call_args.kwargs
            self.assertNotIn('all_projects', payload)
            self.assertNotIn('resource_pools', payload)
            delta = payload['patch']
            self.assertEqual(set(delta['replace_projects']), set(self.pids[:2]))
            successor = next(t for t in delta['tasks'] if int(t['id'])==self.b)
            self.assertEqual(successor['violations'], [])
            self.assertNotIn('resource_pools', delta, 'no pool assignments means no pool recalculation')
            app.session_state['test_event'] = {'action':'load_project_tasks','project_ids':self.pids,'scope_token':'old','nonce':'stale'}
            app.run()
            self.assertNotIn('patch', component.call_args.kwargs)
            app.session_state['test_event'] = {'action':'initialize_planning','nonce':'remount'}
            app.run()
            self.assertEqual(len(component.call_args.kwargs['project_summaries']), 3)
            self.assertNotEqual(component.call_args.kwargs['scope_token'], token)
