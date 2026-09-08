"""Database-side scrolling, global header filters, and lazy portfolio rendering."""

from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from src.database.connection import get_db
from src.database.schema_init import init_db
from src.repositories.portfolio_repo import PortfolioRepository, portfolio_revision
from src.repositories.project_repo import ProjectRepository
from src.repositories.project_type_repo import ProjectTypeRepository
from src.repositories.schema_repo import SchemaRepository


class PortfolioPagingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / 'portfolio.db')
        init_db(self.path)
        self.projects = ProjectRepository(self.path)
        self.repo = PortfolioRepository(self.path)
        self.schema = SchemaRepository(self.path)
        self.types = ProjectTypeRepository(self.path)
        self.special = self.types.create_type('Special')
        self.schema.create_parameter('phase', None, 'phase', 'TEXT', applies_to_all=False,
                                     project_type_ids=[self.special])
        self.columns = [
            {'key': 'name', 'format': 'text'}, {'key': 'project_template', 'format': 'text'},
            {'key': 'planned_budget', 'format': 'currency'},
            {'key': 'property:phase', 'param_id': 'phase', 'format': 'text'},
        ]
        with closing(get_db(self.path)) as conn:
            with conn:
                for i in range(1, 256):
                    ProjectRepository.create_on_connection(conn, name=f'Project {i:03d}',
                        planned_budget=i, project_type_id=self.special if i % 2 else 1,
                        dynamic_attributes={'phase': 'Late' if i > 200 else 'Early'} if i % 2 else {})

    def test_bounded_pages_stable_global_sort_search_and_metrics(self):
        first = self.repo.get_page(self.columns, {})
        second = self.repo.get_page(self.columns, {}, 100)
        last = self.repo.get_page(self.columns, {}, 200)
        self.assertEqual([len(p['rows']) for p in (first, second, last)], [100, 100, 55])
        ids = [r['project_id'] for p in (first, second, last) for r in p['rows']]
        self.assertEqual(ids, list(range(1, 256)))
        self.assertEqual(first['total'], 255)
        self.assertEqual(self.repo.get_metrics().total_planned, sum(range(1, 256)))
        page = self.repo.get_page(self.columns, {'sort': {'column': 'planned_budget', 'direction': 'desc'}})
        self.assertEqual(page['rows'][0]['project_id'], 255)
        page = self.repo.get_page(self.columns, {'search': '255'})
        self.assertEqual([r['project_id'] for r in page['rows']], [255])
        self.assertEqual(self.repo.get_page(self.columns, {'search': '%_" OR 1=1 --'})['total'], 0)
        self.assertEqual(self.repo.get_page(self.columns, {'sort': {'column': 'id; DROP TABLE project;'}})['total'], 255)
        self.assertEqual(self.repo.get_page(self.columns, {}, 100000)['offset'], 200)

    def test_filters_and_statistics_include_unloaded_projects(self):
        query = {'filters': {'property:phase': {'mode': 'include', 'values': ['Late']}}}
        page = self.repo.get_page(self.columns, query)
        self.assertEqual(page['total'], 28)
        self.assertEqual(page['rows'][0]['project_id'], 201)
        facet = self.repo.get_facet(self.columns, query, 'property:phase')
        self.assertEqual(dict(facet['stats'])['Rows'], 255)
        self.assertEqual(dict(facet['stats'])['Empty'], 127)
        self.assertEqual({v['value']: v['count'] for v in facet['values']}, {'': 127, 'Early': 100, 'Late': 28})
        numeric = self.repo.get_facet(self.columns, query, 'planned_budget')
        self.assertEqual(dict(numeric['stats'])['Minimum'], 201)
        self.assertEqual(dict(numeric['stats'])['Maximum'], 255)
        all_names = self.repo.get_facet(self.columns, {}, 'name')
        self.assertEqual(len(all_names['values']), 200)
        self.assertTrue(all_names['has_more'])
        self.assertEqual(self.repo.get_facet(self.columns, {}, 'name', '255')['values'][0]['value'], 'Project 255')
        query = {'templates': ['General'], 'filters': {'planned_budget': {'mode': 'exclude', 'values': [2, 4]}}}
        self.assertEqual(self.repo.get_page(self.columns, query)['total'], 125)
        query = {'filters': {'property:phase': {'mode': 'include', 'values': ['']}}}
        self.assertEqual(self.repo.get_page(self.columns, query)['total'], 127)

    def test_inactive_values_are_hidden_and_cache_revision_tracks_writes(self):
        before = portfolio_revision(self.path)
        self.projects.update_project(255, 'Changed', 'Draft', 255, 0, {}, project_type_id=1)
        self.assertNotEqual(before, portfolio_revision(self.path))
        row = self.repo.get_page(self.columns, {'search': 'Changed'})['rows'][0]
        self.assertIsNone(row['property:phase'])
        self.assertEqual(self.projects.get_project_by_id(255).dynamic_attributes['phase'], 'Late')

    def test_portfolio_does_not_eagerly_load_all_projects(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string(f'''
import importlib
import streamlit as st
from unittest.mock import patch
from src.i18n import set_current_locale
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository
import src.views.portfolio_table_component as component
importlib.reload(component)
from src.views.portfolio_view import render_portfolio_overview
set_current_locale('en')
with patch.object(ProjectRepository, 'get_all_projects', side_effect=AssertionError('eager load')):
    render_portfolio_overview(ProjectRepository({self.path!r}), SchemaRepository({self.path!r}))
''', default_timeout=15).run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        self.assertIn('Projects Master List', [h.value for h in app.subheader])
        self.assertNotIn('Filter by project template', [w.label for w in app.multiselect])
        self.assertFalse(app.header)
        self.assertFalse(app.metric)
        self.assertNotIn('Filter by project type', [w.label for w in app.multiselect])
        self.assertEqual(self.repo.get_metrics().total_projects, 255)


if __name__ == '__main__':
    unittest.main()
