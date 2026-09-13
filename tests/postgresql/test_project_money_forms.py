"""Project money stays decimal text from native forms through PostgreSQL saves."""

from decimal import Decimal
import json

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import AccessDenied
from app.domain.projects.project import Project
from app.main import create_project_workspace
from app.presentation.components.portfolio_project_dialog import ProjectDraft, _accept_values, _project_form, _save
from app.presentation.components.project_dialogs import _dialog_references
from app.presentation.components.project_workspace import ProjectWorkspace
from app.runtime import RuntimeResources


PLANNED = '9007199254740993.1234567890123456789'
ACTUAL = '-0.000000000000000000123456789'


@pytest.fixture
def money_workspace(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project SET planned_budget=%s,actual_budget=%s WHERE id=1',
                           (Decimal(PLANNED), Decimal(ACTUAL)))
    return create_project_workspace(RuntimeResources(authorized.database, authorized.key),
                                    access=authorized.binding(4).access)


def prepared_draft(workspace: ProjectWorkspace, project_id: int | None = 1) -> ProjectDraft:
    """Prepare the actual modal using real native catalog and permission reads."""
    project = workspace.projects.get_project_by_id(project_id) if project_id else Project(
        name='New precise project', planned_budget=Decimal(PLANNED), actual_budget=Decimal(ACTUAL),
    )
    draft = ProjectDraft(project_id, project, _dialog_references(workspace))
    draft.form = _project_form(workspace, draft, project.project_type_id)
    return draft


def event(draft: ProjectDraft, **changes) -> dict:
    """Round-trip a browser action through JSON, preserving the money strings."""
    return json.loads(json.dumps(dict(values=draft.form['values'] | changes, links=[], wbs=[], dirty=list(changes))))


@pytest.mark.parametrize('project_id', [None, 1])
def test_custom_create_and_edit_forms_save_exact_decimal_strings(money_workspace, project_id):
    draft = prepared_draft(money_workspace, project_id)
    fields = {field['key']: field['kind'] for field in draft.form['fields']}
    assert fields['planned_budget'] == fields['actual_budget'] == 'money'
    assert draft.form['values']['planned_budget'] == PLANNED
    assert Decimal(draft.form['values']['actual_budget']) == Decimal(ACTUAL)
    values = _accept_values(draft, event(draft, name='Saved exact euros', planned_budget=PLANNED, actual_budget=ACTUAL))
    saved = money_workspace.projects.get_project_by_id(_save(money_workspace, draft, values))
    assert saved.name == 'Saved exact euros'
    assert saved.planned_budget == Decimal(PLANNED) and saved.actual_budget == Decimal(ACTUAL)


@pytest.mark.parametrize('value', [1, 0.1, None, True])
def test_custom_money_boundary_rejects_json_numbers_instead_of_accepting_rounded_values(money_workspace, value):
    draft = prepared_draft(money_workspace)
    with pytest.raises(ValueError, match='Invalid project field value'):
        _accept_values(draft, event(draft, planned_budget=value))
    assert money_workspace.projects.get_project_by_id(1).planned_budget == Decimal(PLANNED)


@pytest.mark.parametrize('value', ['', ' ', 'NaN', 'Infinity', 'not an amount'])
def test_invalid_money_text_is_rejected_on_save_without_changing_the_project(money_workspace, value):
    draft = prepared_draft(money_workspace)
    values = _accept_values(draft, event(draft, name='Must not persist', planned_budget=value))
    with pytest.raises(ValueError, match='budget amounts|finite numbers'):
        _save(money_workspace, draft, values)
    saved = money_workspace.projects.get_project_by_id(1)
    assert saved.name == 'Editable' and saved.planned_budget == Decimal(PLANNED)


def test_exact_money_save_still_rechecks_the_native_actor_session(money_workspace, authorized):
    draft = prepared_draft(money_workspace)
    values = _accept_values(draft, event(draft, planned_budget='12.34'))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_session SET revoked=true WHERE session_hash='session-4'")
    with pytest.raises(AccessDenied):
        _save(money_workspace, draft, values)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT planned_budget FROM eppm.project WHERE id=1').fetchone() == (Decimal(PLANNED),)


def native_editor(workspace: ProjectWorkspace, read_only: bool = False) -> None:
    """Exercise the existing native project dialog with real services."""
    from app.presentation.components.project_dialogs import open_edit_project_dialog
    from app.presentation.i18n import set_current_locale

    set_current_locale('en')
    open_edit_project_dialog(1, workspace, read_only=read_only)


@pytest.mark.parametrize('read_only', [False, True])
def test_native_money_widgets_preserve_exact_display_and_read_only_state(money_workspace, read_only):
    app = AppTest.from_function(native_editor, args=(money_workspace, read_only), default_timeout=30).run()
    assert not app.exception
    assert app.text_input(key='portfolio_edit_1_planned').value == PLANNED
    assert Decimal(app.text_input(key='portfolio_edit_1_actual').value) == Decimal(ACTUAL)
    assert app.text_input(key='portfolio_edit_1_planned').disabled is read_only
    assert app.text_input(key='portfolio_edit_1_actual').disabled is read_only


def test_native_money_inputs_allow_incomplete_drafts_but_validate_before_exact_save(money_workspace):
    app = AppTest.from_function(native_editor, args=(money_workspace,), default_timeout=30).run()
    app.text_input(key='portfolio_edit_1_planned').set_value('').run()
    assert not app.exception and not app.error
    app.button(key='save_project_1').click().run()
    assert not app.exception and app.error
    assert money_workspace.projects.get_project_by_id(1).planned_budget == Decimal(PLANNED)
    new_planned, new_actual = '9007199254740999.987654321987654321', '0.000000000000000001'
    app.text_input(key='portfolio_edit_1_planned').set_value(new_planned)
    app.text_input(key='portfolio_edit_1_actual').set_value(new_actual)
    app.button(key='save_project_1').click().run()
    assert not app.exception and not app.error
    saved = money_workspace.projects.get_project_by_id(1)
    assert saved.planned_budget == Decimal(new_planned) and saved.actual_budget == Decimal(new_actual)
