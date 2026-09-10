"""Organization dialogs and the actual Settings route through application services."""

from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.domain.organization.models import FunctionType, OrgFunction
from app.operator_services import create_organization_service
from app.infrastructure.database.schema_init import init_db


@pytest.fixture
def database(tmp_path: Path) -> str:
    path = str(tmp_path / "organization-ui.db")
    init_db(path)
    return path


def dialog(path: str, invocation: str) -> AppTest:
    """Keep the production dialog open across AppTest's full script reruns."""
    app = AppTest.from_string(f'''
import streamlit as st
from app.operator_services import create_organization_service
from app.presentation.components import organization_dialogs as dialogs
from app.presentation.components.organization_frames import functions_frame, function_types_frame
from app.presentation.i18n import set_current_locale
set_current_locale("en")
service = create_organization_service({path!r})
functions = functions_frame(service.get_all_functions())
types = function_types_frame(service.get_all_function_types())
dialogs.{invocation}
''', default_timeout=15).run()
    assert not app.exception, [error.message for error in app.exception]
    return app


def button(app: AppTest, text: str):
    """Locate a production button while preserving its translated label."""
    return next(widget for widget in app.button if text in widget.label)


def test_team_dialog_saves_details_and_membership_then_edits_and_deletes(database: str) -> None:
    service = create_organization_service(database)
    member = service.create_function(OrgFunction("Engineer", 3))
    app = dialog(database, "_open_add_team_dialog(service, functions)")
    app.text_input[0].input("Delivery")
    app.multiselect[0].set_value([member])
    button(app, "Save").click().run()
    assert not app.exception
    team = service.get_all_teams()[0]
    assert team.team_name == "Delivery"
    assert service.get_team_functions(team.team_id) == [member]

    app = dialog(database, f"_open_edit_team_dialog(service, {team.team_id}, functions)")
    app.text_input[0].input("Delivery renamed")
    app.multiselect[0].set_value([])
    button(app, "Save").click().run()
    assert not app.exception
    assert service.get_team_by_id(team.team_id).team_name == "Delivery renamed"
    assert service.get_team_functions(team.team_id) == []
    app = dialog(database, f"_open_delete_team_dialog(service, {team.team_id}, 'Delivery renamed')")
    button(app, "Yes, Delete").click().run()
    assert not app.exception and service.get_all_teams() == []


def test_employee_dialog_initial_exception_is_atomic_and_calendar_can_be_edited(database: str) -> None:
    service = create_organization_service(database)
    app = dialog(database, "_open_add_employee_dialog(service, functions)")
    app.checkbox(key="new_employee_add_initial_exception").check().run()
    fields = {widget.label: widget for widget in app.text_input}
    next(widget for label, widget in fields.items() if "First Name" in label).input("Ada")
    next(widget for label, widget in fields.items() if "Last Name" in label).input("Lovelace")
    next(widget for label, widget in fields.items() if "Email" in label).input("ada@example.com")
    app.text_input(key="new_employee_exception_reason").input("Leave")
    button(app, "Save").click().run()
    assert not app.exception, [error.message for error in app.exception]
    employee = service.get_all_employees()[0]
    assert employee.firstname == "Ada"
    assert service.get_employee_calendar_exceptions(employee.employee_id)[0].reason == "Leave"

    app = dialog(database, f"_open_edit_employee_dialog(service, {employee.employee_id}, functions)")
    app.radio(key=f"employee_exception_mode_{employee.employee_id}").set_value("edit").run()
    exception_id = service.get_employee_calendar_exceptions(employee.employee_id)[0].exception_id
    app.number_input(key=f"employee_exception_percentage_{employee.employee_id}_edit_{exception_id}").set_value(50)
    # AppTest drives full-script reruns, so adapt only the fragment scheduling
    # boundary; the production widgets, services, and database remain real.
    rerun = st.rerun
    with patch("streamlit.rerun", side_effect=lambda **_: rerun()):
        app.button(key=f"save_employee_exception_{employee.employee_id}_edit_{exception_id}").click().run()
        assert not app.exception, [error.message for error in app.exception]
        assert service.get_employee_calendar_exception_by_id(exception_id).occupation_percentage == 50
        app.button(key=f"delete_employee_exception_{employee.employee_id}_{exception_id}").click().run()
    assert not app.exception
    assert service.get_employee_calendar_exceptions(employee.employee_id) == []


def test_employee_dialog_failure_leaves_no_partial_profile(database: str) -> None:
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""CREATE TRIGGER reject_exception BEFORE INSERT ON employee_calendar_exception
                              BEGIN SELECT RAISE(ABORT, 'private database details'); END""")
    app = dialog(database, "_open_add_employee_dialog(service, functions)")
    app.checkbox(key="new_employee_add_initial_exception").check().run()
    next(widget for widget in app.text_input if "First Name" in widget.label).input("Ada")
    next(widget for widget in app.text_input if "Last Name" in widget.label).input("Lovelace")
    next(widget for widget in app.text_input if "Email" in widget.label).input("ada@example.com")
    button(app, "Save").click().run()
    assert not app.exception
    assert app.error and "private database details" not in app.error[0].value
    assert create_organization_service(database).get_all_employees() == []


def test_function_and_type_dialogs_preserve_validation_and_reference_errors(database: str) -> None:
    service = create_organization_service(database)
    app = dialog(database, "_open_add_function_type_dialog(service)")
    app.text_input[0].input("Engineering")
    button(app, "Save").click().run()
    assert not app.exception
    type_id = service.get_all_function_types()[0].function_type_id
    app = dialog(database, "_open_add_function_dialog(service, functions, types)")
    button(app, "Save").click().run()
    assert not app.exception and app.error
    app.text_input[0].input("Engineer")
    app.selectbox[0].set_value(type_id)
    button(app, "Save").click().run()
    assert not app.exception
    function_id = service.get_all_functions()[0].function_id
    app = dialog(database, f"_open_edit_function_dialog(service, {function_id}, functions, types)")
    app.text_input[0].input("Lead engineer")
    button(app, "Save").click().run()
    assert not app.exception
    assert service.get_function_by_id(function_id).name == "Lead engineer"
    app = dialog(database, f"_open_delete_function_type_dialog(service, {type_id}, 'Engineering')")
    button(app, "Yes, Delete").click().run()
    assert not app.exception and app.error
    assert "FOREIGN KEY" not in app.error[0].value
    assert service.get_function_type_by_id(type_id) is not None


def test_settings_organization_tabs_use_services_and_keep_other_tabs_lazy(database: str) -> None:
    app = AppTest.from_string(f'''
from app.presentation.i18n import set_current_locale
from app.operator_services import create_organization_service
from app.presentation.pages.settings import render_settings_view
from app.operator_services import create_settings_workspace
set_current_locale("en")
render_settings_view(create_settings_workspace({database!r}))
''', default_timeout=15)
    with patch(
        "app.application.services.pool_capacity.PoolCapacityService.get_summaries",
        side_effect=AssertionError("Hidden resource pools loaded"),
    ):
        for label in ("💼 Functions", "🏷️ Function Types", "🛡️ Teams", "👥 Employees"):
            app.session_state["settings_tab_selection"] = label
            app.run()
            assert not app.exception, [error.message for error in app.exception]
            assert len(app.get("component_instance")) == 1


def test_deleted_record_is_not_reported_as_saved(database: str) -> None:
    service = create_organization_service(database)
    type_id = service.create_function_type(FunctionType("Temporary"))
    app = dialog(database, f"_open_edit_function_type_dialog(service, {type_id}, 'Temporary')")
    service.delete_function_type(type_id)
    app.text_input[0].input("Lost update")
    button(app, "Save").click().run()
    assert not app.exception
    assert any("no longer exists" in error.value for error in app.error)
    assert service.get_all_function_types() == []
