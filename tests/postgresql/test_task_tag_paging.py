"""Paged tag data and deferred editor lookups, including real Streamlit reruns."""

import unittest
from unittest.mock import patch

import psycopg
import pytest
from streamlit.testing.v1 import AppTest
from app.domain.tags.models import TaskTag
from app.main import create_tag_service, create_planning_service
from tests.postgresql.test_settings_lazy_loading import settings_app
from tests.postgresql.ui import runtime as runtime, access as access
from app.application.services.tags import TagService
from app.application.services.planning import PlanningService
from app.presentation.components.tag_frames import page_frame


def add_tag_app(resources, access):
    from app.main import create_tag_service
    from app.presentation.components.tag_dialogs import _open_add_task_tag_dialog
    _open_add_task_tag_dialog(create_tag_service(resources, access=access))


class TaskTagPagingTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def native_setup(self, authorized, runtime, access):
        self.resources, self.access = runtime, access
        with psycopg.connect(authorized.setup.operator_url) as connection, connection.cursor() as cursor:
            connection.execute("UPDATE eppm.project SET name='Search Project' WHERE id=1")
            cursor.executemany("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date) VALUES(%s,1,%s,'2026-01-01','2026-01-02')",
                               [(i, f'Task {i}') for i in range(1, 351)])
            cursor.executemany('INSERT INTO eppm.task_tag(task_id,free_tag) VALUES(%s,%s)',
                               [(i, 'Rare 100%_tag' if i == 1 else 'Common') for i in range(1, 351)])
        self.repo = create_tag_service(runtime, access=access)

    def test_paging_and_filters_search_all_rows_with_stable_sort(self):
        first, second = page_frame(self.repo.get_task_tags_page()), page_frame(self.repo.get_task_tags_page(page=2))
        self.assertEqual(len(first['rows']), 100)
        self.assertEqual(first['total'], 350)
        self.assertEqual(first['pages'], 4)
        self.assertFalse(set(first['rows']['id']) & set(second['rows']['id']))
        filtered = page_frame(self.repo.get_task_tags_page(filters={'free_tag': '100%_', 'project_name': 'search'}))
        self.assertEqual(filtered['rows']['task_id'].tolist(), [1])
        self.assertEqual(page_frame(self.repo.get_task_tags_page(search="' OR 1=1 --"))['filtered_total'], 0)
        self.assertEqual(page_frame(self.repo.get_task_tags_page(sort='bad SQL'))['rows']['id'].tolist(), first['rows']['id'].tolist())
        self.assertEqual(page_frame(self.repo.get_task_tags_page(page=99))['page'], 4)
        self.assertEqual(page_frame(self.repo.get_task_tags_page(sort='free_tag', ascending=True))['rows']['id'].tolist(), list(range(2, 102)))
        self.repo.update_task_tag(TaskTag(id=1, task_id=1, free_tag='Changed'))
        self.assertEqual(page_frame(self.repo.get_task_tags_page(search='Changed'))['filtered_total'], 1)
        self.repo.delete_task_tag(1)
        self.assertEqual(page_frame(self.repo.get_task_tags_page(search='Changed'))['filtered_total'], 0)

    def test_task_choices_are_bounded_and_can_find_an_old_task_by_id(self):
        repo = create_planning_service(self.resources, access=self.access)
        self.assertEqual(len(repo.search_task_choices()), 50)
        self.assertEqual(repo.search_task_choices('#1')[0]['id'], 1)
        self.assertEqual(len(repo.search_task_choices('Search Project')), 50)

    def test_settings_loads_one_page_and_no_editor_data_until_opened(self):
        app = AppTest.from_function(settings_app, args=(self.resources, self.access))
        app.session_state['settings_tab_selection'] = '📋 Task Tags'
        with patch.object(TagService, 'get_all_task_tags', side_effect=AssertionError('All tags loaded')), \
             patch.object(PlanningService, 'get_all_milestones', side_effect=AssertionError('All tasks loaded')), \
             patch.object(TagService, 'get_task_tag_group_tags', side_effect=AssertionError('Unopened editor loaded')), \
             patch('app.presentation.pages.tags._interactive_task_tag_table', return_value=None) as table:
            app.run()
            self.assertEqual(list(app.exception), [])
            self.assertEqual(len(table.call_args.kwargs['task_tags']), 100)
            app.session_state['task_tag_query'] = {'page': 2}
            app.run()
            self.assertEqual(list(app.exception), [])
            self.assertEqual(table.call_args.kwargs['page_info']['page'], 2)
            self.assertEqual(table.call_args.kwargs['task_tags'][0]['id'], 250)

    def test_editor_can_search_and_assign_a_tag_without_loading_all_tasks(self):
        with patch.object(PlanningService, 'get_all_milestones', side_effect=AssertionError('All tasks loaded')):
            app = AppTest.from_function(add_tag_app, args=(self.resources, self.access)).run()
            self.assertEqual(list(app.exception), [])
            app.text_input(key='add_task_tag_search').set_value('#1').run()
            app.selectbox(key='add_task_tag_task').set_value(1).run()
            [field for field in app.text_input if 'Free-form' in field.label][0].set_value('Lazy editor test').run()
            [button for button in app.button if 'Save' in button.label or 'Assign' in button.label][0].click().run()
            self.assertEqual(list(app.exception), [])
        result = page_frame(self.repo.get_task_tags_page(search='Lazy editor test'))
        self.assertEqual(result['rows']['task_id'].tolist(), [1])
