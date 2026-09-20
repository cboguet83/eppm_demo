"""Native and custom project forms edit priority, while finance is derived."""

import json

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import AccessDenied
from app.domain.projects.project import Project
from app.main import create_project_workspace
from app.presentation.components.portfolio_project_dialog import ProjectDraft, _accept_values, _project_form, _save
from app.presentation.components.project_dialogs import _dialog_references
from app.runtime import RuntimeResources


@pytest.fixture
def workspace(authorized):
    return create_project_workspace(RuntimeResources(authorized.database, authorized.key),
                                    access=authorized.binding(4).access)


def prepared_draft(workspace, project_id=1):
    project = workspace.projects.get_project_by_id(project_id) if project_id else Project(name='New project')
    draft = ProjectDraft(project_id, project, _dialog_references(workspace))
    draft.form = _project_form(workspace, draft, project.project_type_id)
    return draft


def event(draft, **changes):
    return json.loads(json.dumps(dict(values=draft.form['values'] | changes, links=[], wbs=[], dirty=list(changes))))


@pytest.mark.parametrize('project_id', [None, 1])
def test_custom_forms_create_edit_and_clear_priority_without_money_inputs(workspace, project_id):
    draft = prepared_draft(workspace, project_id)
    fields = {field['key']: field['kind'] for field in draft.form['fields']}
    assert fields['strategic_priority_id'] == 'select'
    assert not {'planned_budget', 'actual_budget'} & fields.keys()
    values = _accept_values(draft, event(draft, name='Strategic project', strategic_priority_id='1'))
    identity = _save(workspace, draft, values)
    assert workspace.projects.get_project_by_id(identity).strategic_priority_id == 1
    draft = prepared_draft(workspace, identity)
    _save(workspace, draft, _accept_values(draft, event(draft, strategic_priority_id='')))
    assert workspace.projects.get_project_by_id(identity).strategic_priority_id is None


def test_priority_save_rechecks_actor_session(workspace, authorized):
    draft = prepared_draft(workspace)
    values = _accept_values(draft, event(draft, strategic_priority_id='2'))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_session SET revoked=true WHERE session_hash='session-4'")
    with pytest.raises(AccessDenied):
        _save(workspace, draft, values)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT strategic_priority_id FROM eppm.project WHERE id=1').fetchone() == (None,)


def native_editor(workspace, read_only=False):
    from app.presentation.components.project_dialogs import open_edit_project_dialog
    from app.presentation.i18n import set_current_locale
    set_current_locale('en')
    open_edit_project_dialog(1, workspace, read_only=read_only)


@pytest.mark.parametrize('read_only', [False, True])
def test_native_priority_selector_preserves_read_only_state(workspace, read_only):
    app = AppTest.from_function(native_editor, args=(workspace, read_only), default_timeout=30).run()
    assert not app.exception
    assert app.selectbox(key='portfolio_edit_1_priority').disabled is read_only
    assert not any(widget.key in {'portfolio_edit_1_planned', 'portfolio_edit_1_actual'} for widget in app.text_input)
    if not read_only:
        app.selectbox(key='portfolio_edit_1_priority').select(2)
        app.button(key='save_project_1').click().run()
        assert not app.exception and not app.error
        assert workspace.projects.get_project_by_id(1).strategic_priority_id == 2
