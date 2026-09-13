"""Streamlit interaction tests for effective templates and unsaved drafts."""

from app.domain.projects.property_values import SUPPORTED_PROPERTY_TYPES
from app.presentation.components import project_type_frames

import unittest
import psycopg
import pytest

from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.seeder import install_default_data
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import native_screen, runtime as runtime, access as access

from streamlit.testing.v1 import AppTest

from app.presentation.i18n import t, set_current_locale
from app.main import create_project_service
from app.main import create_project_type_service
from app.main import create_schema_service


class ProjectTypeViewTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def native_setup(self, authorized: AuthorizedFixture, runtime: RuntimeResources, access: BusinessAccess) -> None:
        """Start these UI workflows with an empty project catalog and known IDs."""
        set_current_locale("en")
        self.setup, self.resources, self.access = authorized.setup, runtime, access
        with psycopg.connect(self.setup.operator_url) as connection:
            connection.execute('DELETE FROM eppm.project')
            connection.execute("SELECT setval(pg_get_serial_sequence('eppm.project','id'),1,false)")
        self.types = create_project_type_service(runtime, access=access)
        self.schema = create_schema_service(runtime, access=access)
        self.repo = create_project_service(runtime, access=access)

    def app(self, body: str) -> AppTest:
        return native_screen(f'''
import streamlit as st
from app.presentation.i18n import set_current_locale
from app.main import create_project_service
from app.main import create_schema_service
from app.main import create_project_workspace
from app.presentation.components.project_dialogs import open_create_project_dialog, open_edit_project_dialog
set_current_locale("en")
workspace = create_project_workspace(runtime, access=access)
repo = workspace.projects
schema = create_schema_service(runtime, access=access)
{body}
''', self.resources, self.access).run()

    def assert_clean(self, app: AppTest) -> None:
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
        with psycopg.connect(self.setup.operator_url) as connection:
            install_default_data(connection, force=False, include_projects=True, year=2026)
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

        def field_in_tab(app, prefix, kind, widget):
            # Property tabs render on selection; exercise each actual control.
            for label in [tab.label for tab in app.tabs]:
                app.session_state[prefix + '_tabs'] = label
                app.run()
                self.assert_clean(app)
                matches = [item for item in app.get(widget) if item.key == prefix + '_' + kind]
                if matches:
                    return matches[0]
            self.fail(f'{kind} is missing from all property tabs')

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
            field_in_tab(app, 'portfolio_create_1', kind, 'text_input')
        for kind, widget, expected in [
            ('DATE', 'date_input', datetime.date(2026, 9, 8)), ('NUMBER', 'number_input', 0),
            ('ENUM', 'selectbox', 'Option A'), ('MULTI_ENUM', 'multiselect', ['Option A']),
            ('TAGS', 'multiselect', ['Free tag']),
        ]:
            self.assertEqual(field_in_tab(app, 'portfolio_create_1', kind, widget).value, expected)
        # An explicitly cleared value must stay empty even if its tab is hidden
        # on save; an untouched, unset property is independently nullable.
        field_in_tab(app, 'portfolio_create_1', 'blank', 'text_input').input('Temporary').run()
        field_in_tab(app, 'portfolio_create_1', 'blank', 'text_input').input('').run()
        self.assertNotIn('portfolio_create_1_other', [w.key for w in app.text_input])
        next(w for w in app.text_input if w.label == t('master_data.field_name')).input('Complete project').run()
        next(b for b in app.button if b.label == 'Create project').click().run()
        self.assert_clean(app)
        self.assertEqual(self.repo.get_project_by_id(1).dynamic_attributes, {**values, 'blank': ''})

        app = self.app('open_edit_project_dialog(1, workspace)')
        self.assert_clean(app)
        field_in_tab(app, 'portfolio_edit_1', 'blank', 'text_input').input('Previously empty').run()
        field_in_tab(app, 'portfolio_edit_1', 'NUMBER', 'number_input').set_value(42).run()
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
            rendered += '\n'.join(w.proto.body for w in details.get('html'))
        for kind in SUPPORTED_PROPERTY_TYPES:
            self.assertIn(f'Alias {kind}:', rendered)
            self.assertNotIn(f'Custom {kind} (Alias {kind})', rendered)
        self.assertIn('Unfilled property:</span><span>Previously empty', rendered)
        self.assertIn('target="_blank" rel="noopener noreferrer"', rendered)
        self.assertNotIn('Other template only:', rendered)
