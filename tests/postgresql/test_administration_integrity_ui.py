"""Real administration dialogs preserve storage integrity and application identities."""

from datetime import date
from unittest.mock import patch

import psycopg
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Button

from app.domain.access.models import Actor
from app.runtime import RuntimeResources
from tests.postgresql.test_portfolio_project_modal import business, dashboard_business, runtime


@pytest.fixture
def directory(authorized, business):
    runtime_resources, access, administrator, editor, _ = business
    access.grant(administrator, editor.actor.user_id, "business_admin", {"kind": "all"})
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function_type(function_type_id,function_type) VALUES(10,'Engineering')")
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level,function_type_id) VALUES(10,'Engineer',3,10)")
        connection.execute("INSERT INTO eppm.team(team_id,team_name,manager_function_id) VALUES(10,'Delivery',10)")
        connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email) VALUES(10,'Rae','Example','rae@example.test'),(20,'Robin','Example','robin@example.test')")
        connection.execute("INSERT INTO eppm.employee_function(employee_id,function_id,allocation_pct) VALUES(10,10,100),(20,10,100)")
    return runtime_resources, editor.actor


def administration_dialog(runtime_resources: RuntimeResources, actor: Actor, entity: str, action: str, record_id: int = 10) -> None:
    """Keep the actual dialog open across AppTest's full-script submit reruns."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_organization_service, create_resource_pool_service
    from app.presentation.components import organization_dialogs as organization, resource_pool_dialogs as pools
    from app.presentation.components.organization_frames import functions_frame, function_types_frame
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    service = create_organization_service(runtime_resources, access=access)
    resources = create_resource_pool_service(runtime_resources, access=access)
    functions = functions_frame(service.get_all_functions())
    types = function_types_frame(service.get_all_function_types())
    dialogs = {
        ("function", "add"): lambda: organization._open_add_function_dialog(service, functions, types),
        ("function", "edit"): lambda: organization._open_edit_function_dialog(service, record_id, functions, types),
        ("function", "delete"): lambda: organization._open_delete_function_dialog(service, record_id, "Engineer"),
        ("team", "add"): lambda: organization._open_add_team_dialog(service, functions),
        ("team", "edit"): lambda: organization._open_edit_team_dialog(service, record_id, functions),
        ("type", "add"): lambda: organization._open_add_function_type_dialog(service),
        ("type", "edit"): lambda: organization._open_edit_function_type_dialog(service, record_id, "Engineering"),
        ("employee", "add"): lambda: organization._open_add_employee_dialog(service, functions),
        ("employee", "edit"): lambda: organization._open_edit_employee_dialog(service, record_id, functions),
        ("pool", "edit"): lambda: pools._open_edit_pool_dialog(resources, record_id),
        ("assignment", "delete"): lambda: pools._confirm_unassign(resources, 1, record_id, "Visible"),
    }
    dialogs[entity, action]()


def open_dialog(directory: tuple[RuntimeResources, Actor], entity: str, action: str, record_id: int = 10) -> AppTest:
    """Open the selected production dialog with the fixture's business administrator."""
    return AppTest.from_function(
        administration_dialog, args=(*directory, entity, action, record_id), default_timeout=30,
    ).run()


def save(app: AppTest) -> Button:
    """Locate the dialog's translated save action."""
    return next(button for button in app.button if "Save" in button.label)


def directory_snapshot(operator_url: str) -> dict[str, list[tuple[object, ...]]]:
    """Capture business and identity rows so failed writes cannot hide partial changes."""
    with psycopg.connect(operator_url) as connection:
        return {table: connection.execute(f"SELECT * FROM eppm.{table} ORDER BY 1").fetchall() for table in (
            "function", "function_type", "team", "team_function", "employee", "employee_function", "employee_calendar_exception",
            "app_user", "app_identity", "app_role_assignment",
        )}


@pytest.mark.parametrize("entity,table", [("function", "function"), ("team", "team"), ("type", "function_type"), ("employee", "employee")])
@pytest.mark.parametrize("action", ["add", "edit"])
@pytest.mark.parametrize("failure", ["RAISE EXCEPTION 'private storage diagnostics' USING ERRCODE='23514'", "PERFORM * FROM eppm.private_unavailable_storage"])
def test_shared_directory_storage_failure_leaves_no_partial_changes_or_private_error_details(authorized, directory, entity, table, action, failure):
    runtime_resources, _ = directory
    before = directory_snapshot(authorized.setup.operator_url)
    sql_action = "INSERT" if action == "add" else "UPDATE"
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute(f"""CREATE FUNCTION eppm.reject_directory_write() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN {failure}; RETURN NEW; END $$""")
        connection.execute(f"CREATE TRIGGER storage_failure BEFORE {sql_action} ON eppm.{table} "
                           "FOR EACH ROW EXECUTE FUNCTION eppm.reject_directory_write()")
    app = open_dialog(directory, entity, action)
    assert not app.exception and not app.error
    if entity == "employee":
        next(item for item in app.text_input if "First Name" in item.label).input("Candidate")
        if action == "add":
            next(item for item in app.text_input if "Last Name" in item.label).input("Record")
            next(item for item in app.text_input if "Email" in item.label).input("candidate@example.test")
    else:
        app.text_input[0].input("Candidate record")
    save(app).click().run()
    assert not app.exception and app.error
    assert "private storage diagnostics" not in app.error[0].value
    assert "private_unavailable_storage" not in app.error[0].value
    assert not app.toast
    assert directory_snapshot(authorized.setup.operator_url) == before


@pytest.mark.parametrize("entity", ["function", "team", "type"])
@pytest.mark.parametrize("action", ["add", "edit"])
def test_directory_required_names_are_revalidated_before_saving(authorized, directory, entity, action):
    runtime_resources, _ = directory
    before = directory_snapshot(authorized.setup.operator_url)
    app = open_dialog(directory, entity, action)
    app.text_input[0].input("  ")
    save(app).click().run()
    assert not app.exception and app.error and not app.toast
    assert directory_snapshot(authorized.setup.operator_url) == before


@pytest.mark.parametrize("field,value", [("Email", "robin@example.test")])
@pytest.mark.parametrize("action", ["add", "edit"])
def test_duplicate_employee_identity_fields_do_not_modify_either_profile_or_application_users(authorized, directory, field, value, action):
    runtime_resources, _ = directory
    before = directory_snapshot(authorized.setup.operator_url)
    app = open_dialog(directory, "employee", action)
    if action == "add":
        next(item for item in app.text_input if "First Name" in item.label).input("Candidate")
        next(item for item in app.text_input if "Last Name" in item.label).input("Record")
        next(item for item in app.text_input if "Email" in item.label).input("candidate@example.test")
    next(item for item in app.text_input if field in item.label).input(value)
    save(app).click().run()
    assert not app.exception and app.error and not app.toast
    assert value in app.error[0].value
    assert directory_snapshot(authorized.setup.operator_url) == before


@pytest.mark.parametrize("entity", ["function", "team", "employee", "pool"])
def test_missing_directory_or_pool_record_cannot_open_an_editable_form(directory, entity):
    app = open_dialog(directory, entity, "edit", record_id=999)
    assert not app.exception and app.error
    assert "not found" in app.error[0].value.lower()
    assert not app.text_input and not app.button


@pytest.mark.parametrize("failure", ["RAISE EXCEPTION 'private calendar diagnostics' USING ERRCODE='23514'", "PERFORM * FROM eppm.private_calendar_storage"])
def test_employee_calendar_creation_rejects_invalid_periods_and_storage_failure_then_saves_atomically(authorized, directory, failure):
    runtime_resources, _ = directory
    before = directory_snapshot(authorized.setup.operator_url)
    app = open_dialog(directory, "employee", "edit")
    next(button for button in app.button if button.label == "Add calendar exception").click().run()
    next(widget for widget in app.date_input if widget.label == "Start date").set_value(date(2026, 10, 5))
    next(widget for widget in app.date_input if widget.label == "End date").set_value(date(2026, 10, 4))
    save(app).click().run()
    assert not app.exception and app.error
    assert directory_snapshot(authorized.setup.operator_url) == before
    next(widget for widget in app.date_input if widget.label == "End date").set_value(date(2026, 10, 9))
    next(widget for widget in app.number_input if widget.label == "Availability (%)").set_value(50.0)
    next(widget for widget in app.text_input if widget.label == "Reason").input("Reduced capacity")
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute(f"""CREATE FUNCTION eppm.reject_calendar_write() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN {failure}; RETURN NEW; END $$""")
        connection.execute("CREATE TRIGGER reject_calendar BEFORE INSERT ON eppm.employee_calendar_exception "
                           "FOR EACH ROW EXECUTE FUNCTION eppm.reject_calendar_write()")
    save(app).click().run()
    assert not app.exception and app.error and "private calendar" not in app.error[0].value
    assert "private_calendar_storage" not in app.error[0].value
    assert directory_snapshot(authorized.setup.operator_url) == before
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DROP TRIGGER reject_calendar ON eppm.employee_calendar_exception")
    rerun = st.rerun
    with patch("streamlit.rerun", side_effect=lambda **_: rerun()):
        save(app).click().run()
    assert not app.exception and not app.error
    after = directory_snapshot(authorized.setup.operator_url)
    assert len(after.pop("employee_calendar_exception")) == 1
    before.pop("employee_calendar_exception")
    assert after == before
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT employee_id,start_date,end_date,occupation_percentage,reason FROM eppm.employee_calendar_exception").fetchall() == [
            (10, date(2026, 10, 5), date(2026, 10, 9), 50, "Reduced capacity"),
        ]
        assert connection.execute("""SELECT count(*) FROM eppm.employee_calendar_exception exception
            LEFT JOIN eppm.employee employee USING(employee_id) WHERE employee.employee_id IS NULL""").fetchone() == (0,)


def test_business_administrator_can_soft_delete_an_unreferenced_function_without_touching_identities(authorized, directory):
    runtime_resources, _ = directory
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level) VALUES(30,'Vacant function',4)")
    before = directory_snapshot(authorized.setup.operator_url)
    app = open_dialog(directory, "function", "delete", record_id=30)
    app.button[0].click().run()
    assert not app.exception and not app.error
    after = directory_snapshot(authorized.setup.operator_url)
    previous_functions = before.pop("function")
    saved_functions = after.pop("function")
    assert len(saved_functions) == len(previous_functions)
    assert [row for row in saved_functions if row[0] != 30] == [row for row in previous_functions if row[0] != 30]
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT deleted_flag FROM eppm.function WHERE function_id=30").fetchone() == (True,)
    assert before == after


def settings_app(runtime_resources: RuntimeResources, actor: Actor) -> None:
    """Render Settings through the same explicit actor composition as the application."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_settings_workspace
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.settings import render_settings_view

    set_current_locale("en")
    workspace = create_settings_workspace(runtime_resources, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))
    render_settings_view(workspace)


@pytest.mark.parametrize("tab", ["📁 Tag Groups", "📚 Tag Dictionary", "📌 Project Tags", "📋 Task Tags"])
def test_business_administrator_settings_opens_only_the_selected_tag_catalog(directory, tab):
    with patch("app.application.services.pool_capacity.PoolCapacityService.get_summaries", side_effect=AssertionError("Unselected pool data fetched")):
        app = AppTest.from_function(settings_app, args=directory, default_timeout=30)
        app.session_state["settings_tab_selection"] = tab
        app.run()
    assert not app.exception and not app.error
    assert len(app.get("component_instance")) == 1


@pytest.mark.parametrize("kind,tab", [("role", "Project roles"), ("event_type", "Event types")])
def test_project_configuration_catalog_crud_does_not_change_fixed_application_roles(authorized, directory, kind, tab):
    runtime_resources, _ = directory
    before = directory_snapshot(authorized.setup.operator_url)
    app = AppTest.from_function(settings_app, args=directory, default_timeout=30)
    app.session_state["rb_settings_section"] = "project_configuration"
    app.session_state["project_configuration_tab"] = tab
    app.run()
    assert not app.exception and not app.error
    prefix = "project_catalog_" + kind
    app.text_input(key=prefix + "_None_name").input("Custom project catalog item")
    save(app).click().run()
    assert not app.exception and not app.error
    entry_id = app.selectbox(key=prefix + "_selection").value
    assert entry_id is not None
    app.text_input(key=f"{prefix}_{entry_id}_name").input("Renamed project catalog item")
    save(app).click().run()
    assert not app.exception and not app.error
    app.checkbox(key=f"{prefix}_confirm_{entry_id}").check().run()
    app.button(key=prefix + "_delete").click().run()
    assert not app.exception and not app.error
    assert app.selectbox(key=prefix + "_selection").value is None
    assert directory_snapshot(authorized.setup.operator_url) == before


@pytest.mark.parametrize("change", ["deleted", "moved"])
def test_unassignment_confirmation_rechecks_the_selected_pool_and_current_record(authorized, directory, change):
    runtime_resources, _ = directory
    app = open_dialog(directory, "assignment", "delete", record_id=1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        if change == "deleted":
            connection.execute("DELETE FROM eppm.resource_pool_assignment WHERE id=1")
        else:
            connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES(2,'Other pool')")
            connection.execute("UPDATE eppm.resource_pool_assignment SET pool_id=2 WHERE id=1")
    app.button(key="confirm_unassign_1").click().run()
    assert not app.exception and app.error
    assert "no longer exists in this pool" in app.error[0].value
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT id,pool_id FROM eppm.resource_pool_assignment ORDER BY id").fetchall() == (
            [(2, 1)] if change == "deleted" else [(1, 2), (2, 1)]
        )
