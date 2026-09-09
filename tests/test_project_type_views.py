"""Streamlit interaction tests for effective templates and unsaved drafts."""

from app.domain.projects.property_values import SUPPORTED_PROPERTY_TYPES
from app.presentation.components import project_type_frames

import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.infrastructure.database.schema_init import init_db
from app.presentation.i18n import t, set_current_locale
from app.infrastructure.database.seeder import seed_default_data_if_empty
from app.main import create_project_service
from app.main import create_project_type_service
from app.main import create_schema_service


class ProjectTypeViewTests(unittest.TestCase):
    def setUp(self):
        set_current_locale("en")
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "views.db")
        init_db(self.path)
        self.types = create_project_type_service(self.path)
        self.schema = create_schema_service(self.path)
        self.repo = create_project_service(self.path)

    def app(self, body):
        return AppTest.from_string(f'''
import streamlit as st
from app.presentation.i18n import set_current_locale
from app.main import create_project_service
from app.main import create_schema_service
from app.main import create_project_workspace
from app.presentation.components.project_dialogs import open_create_project_dialog, open_edit_project_dialog
set_current_locale("en")
workspace = create_project_workspace({self.path!r})
repo = workspace.projects
schema = create_schema_service({self.path!r})
{body}
''', default_timeout=15).run()

    def assert_clean(self, app):
        self.assertFalse(app.exception, [e.message for e in app.exception])

    def test_creation_defaults_and_user_input_survive_type_switches(self):
        a = self.types.create_type("A")
        self.schema.create_parameter("p", None, "Shared", "TEXT")
        self.schema.create_parameter("q", None, "Only A", "TEXT", applies_to_all=False, project_type_ids=[a])
        self.types.save_rule(a, "p", has_default=True, default_value="A default")
        app = self.app('open_create_project_dialog(workspace)')
        self.assert_clean(app)
        app.selectbox(key="create_type_1").select(a).run()
        self.assert_clean(app)
        self.assertEqual(app.text_input(key="portfolio_create_1_p").value, "A default")
        app.text_input(key="portfolio_create_1_p").input("My draft").run()
        app.text_input(key="portfolio_create_1_q").input("Local draft").run()
        next(w for w in app.text_input if w.label == t("master_data.field_name")).input("New project").run()
        app.selectbox(key="create_type_1").select(1).run()
        self.assert_clean(app)
        self.assertEqual(app.text_input(key="portfolio_create_1_p").value, "My draft")
        self.assertNotIn("portfolio_create_1_q", [w.key for w in app.text_input])
        app.selectbox(key="create_type_1").select(a).run()
        self.assertEqual(app.text_input(key="portfolio_create_1_q").value, "Local draft")
        self.assertEqual(next(w for w in app.text_input if w.label == t("master_data.field_name")).value, "New project")
        next(b for b in app.button if b.label == "Create project").click().run()
        self.assert_clean(app)
        saved = self.repo.get_project_by_id(1)
        self.assertEqual(saved.name, "New project")
        self.assertEqual(saved.project_type_id, a)
        self.assertEqual(saved.dynamic_attributes, {"p": "My draft", "q": "Local draft"})

    def test_edit_type_does_not_apply_defaults_and_validates_required(self):
        a = self.types.create_type("A")
        self.schema.create_parameter("p", None, "Required A", "TEXT", applies_to_all=False, project_type_ids=[a])
        self.types.save_rule(a, "p", True, has_default=True, default_value="Creation only")
        self.repo.create_project(name="Existing")
        app = self.app('open_edit_project_dialog(1, workspace)')
        app.selectbox(key="edit_type_1").select(a).run()
        self.assert_clean(app)
        self.assertEqual(app.text_input(key="portfolio_edit_1_p").value, "")
        from app.presentation.i18n import t
        next(b for b in app.button if b.label == t("master_data.btn_update")).click().run()
        self.assertTrue(app.error)
        self.assertEqual(self.repo.get_project_by_id(1).project_type_id, 1)
        app.text_input(key="portfolio_edit_1_p").input("Entered").run()
        next(b for b in app.button if b.label == t("master_data.btn_update")).click().run()
        self.assert_clean(app)
        self.assertEqual(self.repo.get_project_by_id(1).project_type_id, a)

    def test_configuration_and_portfolio_render_seed_catalog(self):
        seed_default_data_if_empty(self.path)
        config_app = self.app('from app.presentation.pages.schema import render_schema_definition\nrender_schema_definition(schema, workspace.types)')
        self.assert_clean(config_app)
        self.assertIn("Project templates", [tab.label for tab in config_app.tabs])
        types = dict(zip(project_type_frames.types_frame(self.types.get_all_types()).name, project_type_frames.types_frame(self.types.get_all_types()).id))
        config_app.selectbox(key="template_type").select(types["Infrastructure"]).run()
        self.assert_clean(config_app)
        # Each AppTest has its own component registry; register in that runtime.
        portfolio = self.app('import importlib\nimport app.presentation.components.portfolio_table as component\nimportlib.reload(component)\nfrom app.presentation.pages.portfolio import render_portfolio_overview\nst.session_state["selected_portfolio_project_id"] = 1\nrender_portfolio_overview(workspace)')
        self.assert_clean(portfolio)
        self.assertNotIn("Filter by project template", [w.label for w in portfolio.multiselect])
        self.assertIn("Project Contacts", [tab.label for tab in portfolio.tabs])
        self.assertIn("Project log", [tab.label for tab in portfolio.tabs])
        self.assertFalse(portfolio.expander)
        self.assertFalse(portfolio.metric)

    def test_all_template_property_types_are_exposed_in_create_edit_and_details(self):
        import datetime

        template = self.types.create_type('Complete template')
        group = self.schema.create_group('Custom template group', 1)
        values = {'TEXT': 'Text value', 'ENUM': 'Option A', 'MULTI_ENUM': ['Option A'],
                  'TAGS': ['Free tag'], 'URL': 'https://example.com', 'DATE': '2026-09-08',
                  'NUMBER': 0, 'HYPERLINK': 'https://example.com/details'}
        for index, kind in enumerate(SUPPORTED_PROPERTY_TYPES):
            self.schema.create_parameter(kind, group if index % 2 else None, f'Custom {kind}', kind,
                alias=f'Alias {kind}', applies_to_all=False, project_type_ids=[template])
            if kind in ('ENUM', 'MULTI_ENUM'):
                self.schema.add_option(kind, 'Option A', 1)
            self.types.save_rule(template, kind, has_default=True, default_value=values[kind])
        self.schema.create_parameter('blank', None, 'Unfilled property', 'TEXT',
                                     applies_to_all=False, project_type_ids=[template])
        self.schema.create_parameter('other', None, 'Other template only', 'TEXT',
                                     applies_to_all=False, project_type_ids=[1])
        app = self.app('open_create_project_dialog(workspace)')
        app.selectbox(key='create_type_1').select(template).run()
        self.assert_clean(app)
        for kind in ('TEXT', 'URL', 'HYPERLINK', 'blank'):
            self.assertIn(f'portfolio_create_1_{kind}', [w.key for w in app.text_input])
        self.assertEqual(app.date_input(key='portfolio_create_1_DATE').value, datetime.date(2026, 9, 8))
        self.assertEqual(app.number_input(key='portfolio_create_1_NUMBER').value, 0)
        self.assertEqual(app.selectbox(key='portfolio_create_1_ENUM').value, 'Option A')
        self.assertEqual(app.multiselect(key='portfolio_create_1_MULTI_ENUM').value, ['Option A'])
        self.assertEqual(app.multiselect(key='portfolio_create_1_TAGS').value, ['Free tag'])
        self.assertNotIn('portfolio_create_1_other', [w.key for w in app.text_input])
        next(w for w in app.text_input if w.label == t('master_data.field_name')).input('Complete project').run()
        next(b for b in app.button if b.label == 'Create project').click().run()
        self.assert_clean(app)
        self.assertEqual(self.repo.get_project_by_id(1).dynamic_attributes, {**values, 'blank': ''})

        app = self.app('open_edit_project_dialog(1, workspace)')
        self.assert_clean(app)
        app.text_input(key='portfolio_edit_1_blank').input('Previously empty').run()
        app.number_input(key='portfolio_edit_1_NUMBER').set_value(42).run()
        next(b for b in app.button if b.label == t('master_data.btn_update')).click().run()
        self.assert_clean(app)
        self.assertEqual(self.repo.get_project_by_id(1).dynamic_attributes,
                         {**values, 'blank': 'Previously empty', 'NUMBER': 42})
        details = self.app('import importlib\nimport app.presentation.components.portfolio_table as component\nimportlib.reload(component)\nfrom app.presentation.pages.portfolio import render_portfolio_overview\nst.session_state["selected_portfolio_project_id"] = 1\nrender_portfolio_overview(workspace)')
        self.assert_clean(details)
        rendered = ''
        for tab in details.tabs:
            details.session_state['project_details_tabs_1'] = tab.label
            details.run()
            self.assert_clean(details)
            rendered += '\n'.join(w.value for w in details.markdown)
        for kind in SUPPORTED_PROPERTY_TYPES:
            self.assertIn(f'Alias {kind}:', rendered)
            self.assertNotIn(f'Custom {kind} (Alias {kind})', rendered)
        self.assertIn('Unfilled property: Previously empty', rendered)
        self.assertNotIn('Other template only:', rendered)
