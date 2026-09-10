"""Streamlit workflows through injected schema services and the legacy settings route."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.operator_services import create_schema_service, create_project_service, create_project_type_service
from app.infrastructure.database.schema_init import init_db


@pytest.fixture
def french_host_locale():
    """Protect callbacks when an English app is driven from a French host."""
    from app.presentation.i18n import get_current_locale, set_current_locale

    previous = get_current_locale()
    set_current_locale("fr")
    try:
        yield
    finally:
        set_current_locale(previous)


def editor(path: str) -> AppTest:
    """Exercise the new screen directly without a legacy repository dependency."""
    app = AppTest.from_string(f'''
from app.operator_services import create_schema_service, create_project_type_service
from app.presentation.pages.schema import render_schema_definition
from app.presentation.i18n import set_current_locale
set_current_locale("en")
render_schema_definition(create_schema_service({path!r}), create_project_type_service({path!r}))
''', default_timeout=15).run()
    assert not app.exception, [error.message for error in app.exception]
    return app


def widget(elements, label: str, index: int = 0):
    """Select a labeled control, including identical labels in separate forms."""
    return [element for element in elements if element.label == label][index]


def test_schema_editor_group_property_options_and_reference_guards(tmp_path: Path) -> None:
    path = str(tmp_path / "schema-ui.db")
    init_db(path)
    schema = create_schema_service(path)
    types = create_project_type_service(path)
    special = types.create_type("Rail")
    app = editor(path)

    widget(app.text_input, "Group Name *").input("Custom group")
    widget(app.button, "📁 Create Group").click().run()
    assert not app.exception
    group = schema.get_all_groups()[0]
    widget(app.text_input, "Group Name *", 1).input("Renamed group")
    widget(app.button, "💾 Save Changes").click().run()
    assert schema.get_all_groups()[0].group_name == "Renamed group"

    widget(app.selectbox, "Parameter Data Type *").select("ENUM").run()
    widget(app.selectbox, "Assign to Group (Optional)").select(group.id).run()
    app.selectbox(key="new_property_scope").select(False).run()
    app.multiselect(key="new_property_types").select(special).run()
    widget(app.text_input, "Parameter Label / Name *").input("Route")
    widget(app.text_input, "Initial Option / Tag Values (comma-separated)").input(" A, B ")
    widget(app.button, "➕ Add Parameter").click().run()
    assert not app.exception, [error.message for error in app.exception]
    parameter = schema.get_all_parameters()[0]
    assert (parameter.param_id, parameter.group_id, parameter.param_type) == ("PRM_001", group.id, "ENUM")
    assert [option.option_value for option in schema.get_all_options()] == ["A", "B"]
    assert types.get_applicability(parameter.param_id).type_ids == (special,)

    app.text_input(key="edit_alias_PRM_001").input("Route alias")
    app.checkbox(key="edit_required_PRM_001").check()
    widget(app.button, "Save property").click().run()
    assert schema.get_all_parameters()[0].alias == "Route alias"
    assert schema.get_all_parameters()[0].mandatory is True

    widget(app.text_input, "New Option Value *").input("C")
    widget(app.button, "➕ Add Option").click().run()
    assert [option.option_value for option in schema.get_all_options()] == ["A", "B", "C"]
    option_c = schema.get_all_options()[-1]
    widget(app.selectbox, "Delete Option").select(option_c.id).run()
    widget(app.button, "🗑️ Delete Selected Option").click().run()
    assert [option.option_value for option in schema.get_all_options()] == ["A", "B"]

    project = create_project_service(path).create_project(
        name="Uses route", project_type_id=special, dynamic_attributes={"PRM_001": "A"},
    )
    widget(app.selectbox, "Delete Option").select(schema.get_all_options()[0].id).run()
    widget(app.button, "🗑️ Delete Selected Option").click().run()
    assert not app.exception
    assert any("referenced" in error.value for error in app.error)
    assert len(schema.get_all_options()) == 2
    app.run()
    app.checkbox(key="chk_confirm_del_grp").check().run()
    app.button(key="btn_del_grp").click().run()
    assert not app.exception
    assert schema.get_all_groups() == []
    assert schema.get_all_parameters()[0].group_id is None
    assert create_project_service(path).get_project_by_id(project).dynamic_attributes == {"PRM_001": "A"}
    assert any("Route" in element.value for element in app.markdown)
    app.button(key="btn_del_param").click().run()
    assert any("stored values" in error.value for error in app.error)
    create_project_service(path).delete_project(project)
    app.run()
    app.button(key="btn_del_param").click().run()
    assert not app.exception
    assert schema.get_snapshot().parameters == schema.get_snapshot().options == []


def test_schema_editor_shows_safe_errors_and_keeps_failed_creation_atomic(tmp_path: Path) -> None:
    path = str(tmp_path / "failed-schema-ui.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("""CREATE TRIGGER reject_option BEFORE INSERT ON schema_param_options
            WHEN NEW.option_value='Reject' BEGIN SELECT RAISE(ABORT,'private storage details'); END""")
    app = editor(path)
    widget(app.selectbox, "Parameter Data Type *").select("ENUM").run()
    widget(app.text_input, "Parameter Label / Name *").input("Failed property")
    widget(app.text_input, "Initial Option / Tag Values (comma-separated)").input("A, Reject")
    widget(app.button, "➕ Add Parameter").click().run()
    assert not app.exception
    assert any("conflicts" in error.value for error in app.error)
    assert all("private storage" not in error.value for error in app.error)
    snapshot = create_schema_service(path).get_snapshot()
    assert snapshot.parameters == snapshot.options == []


def test_settings_route_composes_the_schema_screen(
    tmp_path: Path, french_host_locale: None,
) -> None:
    path = str(tmp_path / "settings.db")
    init_db(path)
    app = AppTest.from_string(f'''
import streamlit as st
from app.presentation.i18n import set_current_locale
from app.operator_services import create_organization_service
from app.operator_services import create_schema_service
from app.presentation.pages.settings import render_settings_view
from app.operator_services import create_settings_workspace
set_current_locale("en")
st.session_state["rb_settings_section"] = "param_def"
render_settings_view(create_settings_workspace({path!r}))
''', default_timeout=15).run()
    assert not app.exception, [error.message for error in app.exception]
    assert "Project templates" in [tab.label for tab in app.tabs]
    widget(app.text_input, "Group Name *").input("From settings")
    widget(app.button, "📁 Create Group").click().run()
    assert not app.exception
    assert create_schema_service(path).get_all_groups()[0].group_name == "From settings"
