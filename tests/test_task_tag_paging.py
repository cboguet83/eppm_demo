"""Paged tag data and deferred editor lookups, including real Streamlit reruns."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from src.database.schema_init import init_db
from src.models.tag import TaskTag
from src.repositories.tag_repo import TagRepository
from src.repositories.milestone_repo import MilestoneRepository
from tests.test_settings_lazy_loading import settings_app


def add_tag_app(path):
    from src.repositories.tag_repo import TagRepository
    from src.repositories.milestone_repo import MilestoneRepository
    from src.views.settings_view import _open_add_task_tag_dialog
    _open_add_task_tag_dialog(TagRepository(path), MilestoneRepository(path))


class TaskTagPagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "test.db")
        init_db(self.path)
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO project(id,name) VALUES(1,'Search Project')")
            conn.executemany("INSERT INTO project_task(id,project_id,task_name,start_date,end_date) VALUES(?,1,?,'2026-01-01','2026-01-02')",
                             [(i, f'Task {i}') for i in range(1, 351)])
            conn.executemany("INSERT INTO task_tag(task_id,free_tag) VALUES(?,?)",
                             [(i, 'Rare 100%_tag' if i == 1 else 'Common') for i in range(1, 351)])
        self.repo = TagRepository(self.path)

    def test_paging_and_filters_search_all_rows_with_stable_sort(self):
        first, second = self.repo.get_task_tags_page(), self.repo.get_task_tags_page(page=2)
        self.assertEqual(len(first['rows']), 100)
        self.assertEqual(first['total'], 350)
        self.assertEqual(first['pages'], 4)
        self.assertFalse(set(first['rows']['id']) & set(second['rows']['id']))
        filtered = self.repo.get_task_tags_page(filters={'free_tag': '100%_', 'project_name': 'search'})
        self.assertEqual(filtered['rows']['task_id'].tolist(), [1])
        self.assertEqual(self.repo.get_task_tags_page(search="' OR 1=1 --")['filtered_total'], 0)
        self.assertEqual(self.repo.get_task_tags_page(sort='bad SQL')['rows']['id'].tolist(), first['rows']['id'].tolist())
        self.assertEqual(self.repo.get_task_tags_page(page=99)['page'], 4)
        self.assertEqual(self.repo.get_task_tags_page(sort='free_tag', ascending=True)['rows']['id'].tolist(), list(range(2, 102)))
        self.repo.update_task_tag(TaskTag(id=1, task_id=1, free_tag='Changed'))
        self.assertEqual(self.repo.get_task_tags_page(search='Changed')['filtered_total'], 1)
        self.repo.delete_task_tag(1)
        self.assertEqual(self.repo.get_task_tags_page(search='Changed')['filtered_total'], 0)

    def test_task_choices_are_bounded_and_can_find_an_old_task_by_id(self):
        repo = MilestoneRepository(self.path)
        self.assertEqual(len(repo.search_task_choices()), 50)
        self.assertEqual(repo.search_task_choices('#1')[0]['id'], 1)
        self.assertEqual(len(repo.search_task_choices('Search Project')), 50)

    def test_settings_loads_one_page_and_no_editor_data_until_opened(self):
        app = AppTest.from_function(settings_app, args=(self.path,))
        app.session_state['settings_tab_selection'] = '📋 Task Tags'
        with patch.object(TagRepository, 'get_all_task_tags', side_effect=AssertionError('All tags loaded')), \
             patch.object(MilestoneRepository, 'get_all_milestones', side_effect=AssertionError('All tasks loaded')), \
             patch.object(TagRepository, 'get_task_tag_group_tags', side_effect=AssertionError('Unopened editor loaded')), \
             patch('src.views.settings_view._interactive_task_tag_table', return_value=None) as table:
            app.run()
            self.assertEqual(list(app.exception), [])
            self.assertEqual(len(table.call_args.kwargs['task_tags']), 100)
            app.session_state['task_tag_query'] = {'page': 2}
            app.run()
            self.assertEqual(list(app.exception), [])
            self.assertEqual(table.call_args.kwargs['page_info']['page'], 2)
            self.assertEqual(table.call_args.kwargs['task_tags'][0]['id'], 250)

    def test_editor_can_search_and_assign_a_tag_without_loading_all_tasks(self):
        with patch.object(MilestoneRepository, 'get_all_milestones', side_effect=AssertionError('All tasks loaded')):
            app = AppTest.from_function(add_tag_app, args=(self.path,)).run()
            self.assertEqual(list(app.exception), [])
            app.text_input(key='add_task_tag_search').set_value('#1').run()
            app.selectbox(key='add_task_tag_task').set_value(1).run()
            [field for field in app.text_input if 'Free-form' in field.label][0].set_value('Lazy editor test').run()
            [button for button in app.button if 'Save' in button.label or 'Assign' in button.label][0].click().run()
            self.assertEqual(list(app.exception), [])
        result = self.repo.get_task_tags_page(search='Lazy editor test')
        self.assertEqual(result['rows']['task_id'].tolist(), [1])
