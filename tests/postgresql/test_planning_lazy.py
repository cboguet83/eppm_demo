"""Planning summary, bounded hydration and targeted edit regression tests."""

from datetime import date
from unittest import TestCase
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest
from app.main import create_project_service, create_planning_service, create_planning_workspace
from app.application.services.planning import PlanningService
from app.infrastructure.postgresql.derived_cache import PostgresDerivedCache
from app.presentation.components.planning_data import load_project_summaries
from tests.postgresql.ui import runtime as runtime, access as access


def lazy_app(resources, access):
    import streamlit as st
    from app.main import create_planning_workspace
    from app.presentation.pages.planning import render_planning_milestones, _handle_gantt_component_change
    workspace = create_planning_workspace(resources, access=access)
    event = st.session_state.pop('test_event', None)
    if event:
        st.session_state['planning_lazy_gantt'] = event
        _handle_gantt_component_change('planning_lazy_gantt', workspace)
    render_planning_milestones(workspace)



class LazyPlanningTests(TestCase):
    @pytest.fixture(autouse=True)
    def native_setup(self, runtime, access):
        self.resources, self.access = runtime, access
        self.projects = create_project_service(runtime, access=access)
        self.tasks = create_planning_service(runtime, access=access)
        self.pids = [self.projects.create_project(name='Lazy '+str(i), dynamic_attributes={}) for i in range(3)]
        self.a = self.tasks.create_milestone(self.pids[0], 'Predecessor', 'General', '2026-01-01', '2026-01-10', 0)
        self.b = self.tasks.create_milestone(self.pids[1], 'Successor', 'General', '2026-01-05', '2026-01-06', 0,
            dependencies=[{'predecessor_task_id':self.a, 'link_type':'FS','lag_days':0}])
        self.c = self.tasks.create_milestone(self.pids[2], 'Unrelated', 'General', '2026-02-01', '2026-02-02', 0)

    def test_persistent_summaries_invalidate_the_project_and_linked_successors(self):
        workspace = create_planning_workspace(self.resources, access=self.access)
        rows = load_project_summaries(workspace, workspace.revision(), tuple(self.pids))
        self.assertTrue(next(p for p in rows if p['id']==self.pids[1])['hasViolations'])
        cache = PostgresDerivedCache(self.resources.database, self.resources.key, self.resources.caches,
                                     access=self.access)
        before = cache.read('planning', self.pids, date(2000, 1, 1), False, [])
        self.assertEqual({row[0] for row in before if row[3]}, set(self.pids))
        self.tasks.update_dates(self.a, '2026-01-01', '2026-01-03')
        # Current source tokens reject affected entries; unrelated data stays valid.
        after = cache.read('planning', self.pids, date(2000, 1, 1), False, [])
        self.assertEqual({row[0] for row in after if row[3]}, {self.pids[2]})
        rows = load_project_summaries(workspace, workspace.revision(), tuple(self.pids))
        self.assertFalse(next(p for p in rows if p['id']==self.pids[1])['hasViolations'])

    def test_summary_first_hydration_and_edit_patch_never_resend_unrelated_projects(self):
        app = AppTest.from_function(lazy_app, args=(self.resources, self.access), default_timeout=30)
        app.session_state['ms_multi_projects'] = self.pids
        with patch('app.presentation.pages.planning._interactive_gantt', return_value=None) as component:
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
            with patch.object(PlanningService,'read_task_bundle', wraps=self.tasks.read_task_bundle) as reads:
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
