"""Real services maintain explicit labels through the shared Settings editor."""

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.main import create_dictionary_service, create_collaboration_service
from tests.postgresql.ui import runtime, access


def dictionary_screen(resources, actor, kind='role', locale='en'):
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_collaboration_service, create_dictionary_service
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.collaboration import render_project_catalog

    set_current_locale(locale)
    policy = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_project_catalog(create_collaboration_service(resources, access=policy),kind,
                           create_dictionary_service(resources, access=policy))


@pytest.mark.parametrize('kind,code', [('role','project_role'),('event_type','project_event_type')])
def test_editor_creates_renames_translates_and_removes_explicit_labels(runtime, access, kind, code):
    service = create_dictionary_service(runtime, access=access)
    app = AppTest.from_function(dictionary_screen,args=(runtime,access.actor,kind)).run()
    assert not app.exception
    prefix = 'project_catalog_' + kind
    app.text_input(key=f'{prefix}_None_name').set_value('UI Sponsor')
    app.text_input(key=f'{prefix}_None_label_fr').set_value('Parrain UI')
    app.button[0].click().run()
    assert not app.exception and not app.error
    identity = next(row['id'] for row in service.list_entries(code) if row['name']=='UI Sponsor')
    assert service.translations(code,identity)['fr'] == 'Parrain UI'
    assert app.text_input(key=f'{prefix}_{identity}_label_de').value == ''
    app.text_input(key=f'{prefix}_{identity}_name').set_value('Renamed UI')
    app.text_input(key=f'{prefix}_{identity}_label_fr').set_value('')
    app.button[0].click().run()
    assert service.translations(code,identity) == {'en':'Renamed UI'}
    assert service.list_entries(code,'fr')[-1]['label'] == 'Renamed UI' or any(
        row['label']=='Renamed UI' for row in service.list_entries(code,'fr'))
    app.checkbox(key=f'{prefix}_confirm_{identity}').check().run()
    app.button(key=prefix+'_delete').click().run()
    assert not app.exception and not app.error
    assert all(row['id']!=identity for row in service.list_entries(code))


def test_settings_dictionary_reads_are_lazy(runtime, access):
    from tests.postgresql.test_settings_lazy_loading import settings_app
    with patch('app.application.services.dictionaries.DictionaryService.translations', side_effect=AssertionError('Hidden dictionary loaded')):
        app = AppTest.from_function(settings_app,args=(runtime,access)).run()
        assert not app.exception


def test_editor_used_role_cannot_be_deleted(runtime, access, authorized):
    import psycopg
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name) VALUES (1,'Manager')")
    dictionary = create_dictionary_service(runtime,access=access)
    identity = dictionary.save_entry('project_role','Used role',translations={'fr':'Rôle utilisé'})
    create_collaboration_service(runtime,access=access).save_contact(1,identity,1)
    app = AppTest.from_function(dictionary_screen,args=(runtime,access.actor)).run()
    app.selectbox(key='project_catalog_role_selection').select(identity).run()
    app.checkbox(key=f'project_catalog_role_confirm_{identity}').check().run()
    app.button(key='project_catalog_role_delete').click().run()
    assert not app.exception and app.error
    assert dictionary.translations('project_role',identity)['fr'] == 'Rôle utilisé'


def test_editor_nonadministrator_submission_is_rejected(runtime, authorized):
    actor = authorized.binding(1).access.actor
    app = AppTest.from_function(dictionary_screen,args=(runtime,actor)).run()
    app.text_input(key='project_catalog_role_None_name').set_value('Denied')
    app.button[0].click().run()
    assert not app.exception and app.error
    assert 'not permitted' in app.error[0].value
