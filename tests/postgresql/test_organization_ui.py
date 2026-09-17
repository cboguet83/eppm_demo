"""Organization dialogs and the actual Settings route through application services."""

from unittest.mock import patch

import psycopg
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.domain.organization.models import FunctionType, OrgFunction
from app.application.services.business_access import BusinessAccess
from app.main import create_organization_service
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.runtime import RuntimeResources
from tests.postgresql.ui import native_screen


@pytest.fixture
def database(authorized) -> RuntimeResources:
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
    return RuntimeResources(authorized.database, authorized.key)


@pytest.fixture
def access(authorized) -> BusinessAccess:
    return authorized.binding(4).access


def dialog(resources: RuntimeResources, access: BusinessAccess, invocation: str) -> AppTest:
    """Keep the production dialog open across AppTest's full script reruns."""
    app = native_screen(f'''
import streamlit as st
from app.main import create_organization_service
from app.presentation.components import organization_dialogs as dialogs
from app.presentation.components.organization_frames import functions_frame, function_types_frame
from app.presentation.i18n import set_current_locale
set_current_locale("en")
service = create_organization_service(runtime, access=access)
functions = functions_frame(service.get_all_functions())
types = function_types_frame(service.get_all_function_types())
dialogs.{invocation}
''', resources, access).run()
    assert not app.exception, [error.message for error in app.exception]
    return app


def button(app: AppTest, text: str):
    """Locate a production button while preserving its translated label."""
    return next(widget for widget in app.button if text in widget.label)


def test_team_dialog_saves_details_and_membership_then_edits_and_deletes(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_organization_service(database, access=access)
    member = service.create_function(OrgFunction("Engineer", 3))
    app = dialog(database, access, "_open_add_team_dialog(service, functions)")
    assert not any('Leader' in widget.label for widget in app.selectbox)
    app.text_input[0].input("Delivery")
    app.multiselect[0].set_value([member])
    button(app, "Save").click().run()
    assert not app.exception
    team = service.get_all_teams()[0]
    assert team.team_name == "Delivery"
    assert service.get_team_functions(team.team_id) == [member]

    app = dialog(database, access, f"_open_edit_team_dialog(service, {team.team_id}, functions)")
    assert not any('Leader' in widget.label for widget in app.selectbox)
    app.text_input[0].input("Delivery renamed")
    app.multiselect[0].set_value([])
    button(app, "Save").click().run()
    assert not app.exception
    assert service.get_team_by_id(team.team_id).team_name == "Delivery renamed"
    assert service.get_team_functions(team.team_id) == []
    app = dialog(database, access, f"_open_delete_team_dialog(service, {team.team_id}, 'Delivery renamed')")
    button(app, "Yes, Delete").click().run()
    assert not app.exception and service.get_all_teams() == []


def test_employee_dialog_initial_exception_is_atomic_and_calendar_can_be_edited(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_organization_service(database, access=access)
    app = dialog(database, access, "_open_add_employee_dialog(service, functions)")
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

    app = dialog(database, access, f"_open_edit_employee_dialog(service, {employee.employee_id}, functions)")
    assert any('Availability (%)' in frame.value.columns for frame in app.dataframe)
    def edit_grid(frame, **kwargs):
        edited = frame.copy()
        if kwargs['key'].startswith('employee_exception_grid_'):
            edited['Availability (%)'] = 50
        return edited
    with patch('streamlit.data_editor', side_effect=edit_grid):
        app.button(key=f'save_employee_exception_grid_{employee.employee_id}').click().run()
    assert not app.exception and not app.error
    assert service.get_employee_calendar_exceptions(employee.employee_id)[0].occupation_percentage == 50
    with patch('streamlit.data_editor', side_effect=lambda frame, **kwargs:
               frame.iloc[0:0] if kwargs['key'].startswith('employee_exception_grid_') else frame):
        app.button(key=f'save_employee_exception_grid_{employee.employee_id}').click().run()
    assert not app.exception and not app.error
    assert service.get_employee_calendar_exceptions(employee.employee_id) == []



def test_employee_dialog_failure_leaves_no_partial_profile(database: RuntimeResources, access: BusinessAccess, authorized) -> None:
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_exception() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private database details' USING ERRCODE='23514'; END $$""")
        connection.execute("""CREATE TRIGGER reject_exception BEFORE INSERT ON eppm.employee_calendar_exception
            FOR EACH ROW EXECUTE FUNCTION eppm.reject_exception()""")
    app = dialog(database, access, "_open_add_employee_dialog(service, functions)")
    app.checkbox(key="new_employee_add_initial_exception").check().run()
    next(widget for widget in app.text_input if "First Name" in widget.label).input("Ada")
    next(widget for widget in app.text_input if "Last Name" in widget.label).input("Lovelace")
    next(widget for widget in app.text_input if "Email" in widget.label).input("ada@example.com")
    button(app, "Save").click().run()
    assert not app.exception
    assert app.error and "private database details" not in app.error[0].value
    assert create_organization_service(database, access=access).get_all_employees() == []


def test_function_and_type_dialogs_preserve_validation_and_reference_errors(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_organization_service(database, access=access)
    app = dialog(database, access, "_open_add_function_type_dialog(service)")
    app.text_input[0].input("Engineering")
    button(app, "Save").click().run()
    assert not app.exception
    type_id = service.get_all_function_types()[0].function_type_id
    app = dialog(database, access, "_open_add_function_dialog(service, functions, types)")
    button(app, "Save").click().run()
    assert not app.exception and app.error
    app.text_input[0].input("Engineer")
    app.selectbox[0].set_value(type_id)
    button(app, "Save").click().run()
    assert not app.exception
    function_id = service.get_all_functions()[0].function_id
    app = dialog(database, access, f"_open_edit_function_dialog(service, {function_id}, functions, types)")
    app.text_input[0].input("Lead engineer")
    button(app, "Save").click().run()
    assert not app.exception
    assert service.get_function_by_id(function_id).name == "Lead engineer"
    app = dialog(database, access, f"_open_delete_function_type_dialog(service, {type_id}, 'Engineering')")
    button(app, "Yes, Delete").click().run()
    assert not app.exception and app.error
    assert "FOREIGN KEY" not in app.error[0].value
    assert service.get_function_type_by_id(type_id) is not None


def test_settings_organization_tabs_use_services_and_keep_other_tabs_lazy(database: RuntimeResources, access: BusinessAccess) -> None:
    app = native_screen(f'''
from app.presentation.i18n import set_current_locale
from app.main import create_organization_service
from app.presentation.pages.settings import render_settings_view
from app.main import create_settings_workspace
set_current_locale("en")
render_settings_view(create_settings_workspace(runtime, access=access))
''', database, access)
    with patch(
        "app.application.services.pool_capacity.PoolCapacityService.get_summaries",
        side_effect=AssertionError("Hidden resource pools loaded"),
    ):
        for label in ("Functions", "Function Types", "Teams", "Employees"):
            app.session_state["settings_tab_selection"] = label
            app.run()
            assert not app.exception, [error.message for error in app.exception]
            if label == 'Teams':
                assert len(app.metric) == 3
                assert app.checkbox(key='team_show_deleted').label == 'Show deleted teams'
            else:
                assert len(app.get("component_instance")) == 1


def test_deleted_record_is_not_reported_as_saved(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_organization_service(database, access=access)
    type_id = service.create_function_type(FunctionType("Temporary"))
    app = dialog(database, access, f"_open_edit_function_type_dialog(service, {type_id}, 'Temporary')")
    service.delete_function_type(type_id)
    app.text_input[0].input("Lost update")
    button(app, "Save").click().run()
    assert not app.exception
    assert any("no longer exists" in error.value for error in app.error)
    assert service.get_all_function_types() == []
