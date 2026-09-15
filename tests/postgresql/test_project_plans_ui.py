"""Real Streamlit project-plan draft and immutable-save interaction."""

from tests.postgresql.test_project_plans import service, draft_task
from tests.postgresql.ui import native_screen
from app.runtime import RuntimeResources


SCREEN = '''
import streamlit as st
st.session_state.setdefault('planning_view_mode', 'Project plans')
from app.main import create_planning_workspace
from app.presentation.pages.planning import render_planning_milestones
render_planning_milestones(create_planning_workspace(runtime, access=access))
'''


def test_plan_gantt_draft_save_preserves_reference_and_current(authorized):
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    content = initial.content
    content.tasks.append(draft_task())
    alternative = plans.save(1, initial.id, initial.revision, 'Option A', content)
    app = native_screen(SCREEN, RuntimeResources(authorized.database, authorized.key), authorized.binding(4).access).run()
    assert not app.exception
    assert not app.error, [error.value for error in app.error]
    app.multiselect(key='plan_projects').set_value([1]).run()
    app.selectbox(key='plan_alternative_1').set_value(alternative.id).run()
    app.button(key='plan_edit_1').click().run()
    assert not app.exception
    app.text_input(key='plan_name_1_0').set_value('Option B').run()
    app.button(key='save_project_plans').click().run()
    assert not app.exception and not app.error
    saved = plans.list_plans(1)
    assert len(saved) == 3 and saved[0].name == 'Option B'
    assert saved[0].content == saved[1].content
    assert saved[-1].is_current and not saved[0].is_current
    assert app.selectbox(key='plan_alternative_1').value == saved[0].id


def test_cancel_draft_does_not_create_a_version(authorized):
    plans = service(authorized, 4)
    plans.initialize(1)
    app = native_screen(SCREEN, RuntimeResources(authorized.database, authorized.key), authorized.binding(4).access).run()
    assert not app.error, [error.value for error in app.error]
    app.multiselect(key='plan_projects').set_value([1]).run()
    app.button(key='plan_edit_1').click().run()
    app.button(key='plan_cancel_1').click().run()
    assert not app.exception
    assert len(plans.list_plans(1)) == 1
