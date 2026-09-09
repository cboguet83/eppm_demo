"""Real administration dialogs preserve storage integrity and application identities."""

from contextlib import closing
from datetime import date
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Button

from app.domain.access.models import Actor
from app.infrastructure.database.connection import get_db
from tests.test_business_transaction_security import business as business


@pytest.fixture
def directory(business):
    path, access, administrator, editor, _ = business
    access.grant(administrator, editor.actor.user_id, "business_admin", {"kind": "all"})
    with closing(get_db(path)) as connection, connection:
        connection.execute("INSERT INTO function_type(function_type_id,function_type) VALUES(10,'Engineering')")
        connection.execute("INSERT INTO function(function_id,name,hierarchy_level,function_type_id) VALUES(10,'Engineer',3,10)")
        connection.execute("INSERT INTO team(team_id,team_name,manager_function_id) VALUES(10,'Delivery',10)")
        connection.execute("INSERT INTO employee(employee_id,firstname,lastname,email,employee_code,function_id) VALUES(10,'Rae','Example','rae@example.test','D10',10),(20,'Robin','Example','robin@example.test','D20',10)")
    return path, editor.actor


def administration_dialog(path: str, actor: Actor, entity: str, action: str, record_id: int = 10) -> None:
    """Keep the actual dialog open across AppTest's full-script submit reruns."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_organization_service, create_resource_pool_service
    from app.presentation.components import organization_dialogs as organization, resource_pool_dialogs as pools
    from app.presentation.components.organization_frames import functions_frame, function_types_frame
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    service = create_organization_service(path, access=access)
    resources = create_resource_pool_service(path, access=access)
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
        ("group", "edit"): lambda: pools._open_edit_pool_group_dialog(resources, record_id),
        ("assignment", "delete"): lambda: pools._confirm_unassign(resources, 1, record_id, "Visible"),
    }
    dialogs[entity, action]()


def open_dialog(directory: tuple[str, Actor], entity: str, action: str, record_id: int = 10) -> AppTest:
    """Open the selected production dialog with the fixture's business administrator."""
    return AppTest.from_function(
        administration_dialog, args=(*directory, entity, action, record_id), default_timeout=30,
    ).run()


def save(app: AppTest) -> Button:
    """Locate the dialog's translated save action."""
    return next(button for button in app.button if "Save" in button.label)


def directory_snapshot(path: str) -> dict[str, list[tuple[object, ...]]]:
    """Capture business and identity rows so failed writes cannot hide partial changes."""
    with closing(get_db(path)) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in (
            "function", "function_type", "team", "team_function", "employee", "employee_calendar_exception",
            "app_user", "app_identity", "app_role_assignment",
        )}


@pytest.mark.parametrize("entity,table", [("function", "function"), ("team", "team"), ("type", "function_type"), ("employee", "employee")])
@pytest.mark.parametrize("action", ["add", "edit"])
def test_shared_directory_storage_failure_leaves_no_partial_changes_or_private_error_details(directory, entity, table, action):
    path, _ = directory
    before = directory_snapshot(path)
    sql_action = "INSERT" if action == "add" else "UPDATE"
    with closing(get_db(path)) as connection, connection:
        connection.execute(f"CREATE TRIGGER storage_failure BEFORE {sql_action} ON {table} BEGIN SELECT RAISE(ABORT,'private storage diagnostics'); END")
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
    assert not app.toast
    assert directory_snapshot(path) == before


@pytest.mark.parametrize("entity", ["function", "team", "type"])
@pytest.mark.parametrize("action", ["add", "edit"])
def test_directory_required_names_are_revalidated_before_saving(directory, entity, action):
    path, _ = directory
    before = directory_snapshot(path)
    app = open_dialog(directory, entity, action)
    app.text_input[0].input("  ")
    save(app).click().run()
    assert not app.exception and app.error and not app.toast
    assert directory_snapshot(path) == before


@pytest.mark.parametrize("field,value", [("Email", "robin@example.test"), ("Employee Code", "D20")])
@pytest.mark.parametrize("action", ["add", "edit"])
def test_duplicate_employee_identity_fields_do_not_modify_either_profile_or_application_users(directory, field, value, action):
    path, _ = directory
    before = directory_snapshot(path)
    app = open_dialog(directory, "employee", action)
    if action == "add":
        next(item for item in app.text_input if "First Name" in item.label).input("Candidate")
        next(item for item in app.text_input if "Last Name" in item.label).input("Record")
        next(item for item in app.text_input if "Email" in item.label).input("candidate@example.test")
    next(item for item in app.text_input if field in item.label).input(value)
    save(app).click().run()
    assert not app.exception and app.error and not app.toast
    assert value in app.error[0].value
    assert directory_snapshot(path) == before


@pytest.mark.parametrize("entity", ["function", "team", "employee", "pool", "group"])
def test_missing_directory_or_pool_record_cannot_open_an_editable_form(directory, entity):
    app = open_dialog(directory, entity, "edit", record_id=999)
    assert not app.exception and app.error
    assert "not found" in app.error[0].value.lower()
    assert not app.text_input and not app.button


def test_employee_calendar_creation_rejects_invalid_periods_and_storage_failure_then_saves_atomically(directory):
    path, _ = directory
    before = directory_snapshot(path)
    app = open_dialog(directory, "employee", "edit")
    app.date_input(key="employee_exception_start_10_add").set_value(date(2026, 10, 5))
    app.date_input(key="employee_exception_end_10_add").set_value(date(2026, 10, 4))
    app.button(key="save_employee_exception_10_add").click().run()
    assert not app.exception and app.error
    assert directory_snapshot(path) == before
    app.date_input(key="employee_exception_end_10_add").set_value(date(2026, 10, 9))
    app.number_input(key="employee_exception_percentage_10_add").set_value(50.0)
    app.text_input(key="employee_exception_reason_10_add").input("Reduced capacity")
    with closing(get_db(path)) as connection, connection:
        connection.execute("CREATE TRIGGER reject_calendar BEFORE INSERT ON employee_calendar_exception BEGIN SELECT RAISE(ABORT,'private calendar diagnostics'); END")
    app.button(key="save_employee_exception_10_add").click().run()
    assert not app.exception and app.error and "private calendar" not in app.error[0].value
    assert directory_snapshot(path) == before
    with closing(get_db(path)) as connection, connection:
        connection.execute("DROP TRIGGER reject_calendar")
    rerun = st.rerun
    with patch("streamlit.rerun", side_effect=lambda **_: rerun()):
        app.button(key="save_employee_exception_10_add").click().run()
    assert not app.exception and not app.error
    after = directory_snapshot(path)
    assert len(after.pop("employee_calendar_exception")) == 1
    before.pop("employee_calendar_exception")
    assert after == before
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT employee_id,start_date,end_date,occupation_percentage,reason FROM employee_calendar_exception").fetchall() == [
            (10, "2026-10-05", "2026-10-09", 50, "Reduced capacity"),
        ]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_business_administrator_can_delete_an_unreferenced_function_without_touching_identities(directory):
    path, _ = directory
    with closing(get_db(path)) as connection, connection:
        connection.execute("INSERT INTO function(function_id,name,hierarchy_level) VALUES(30,'Vacant function',4)")
    before = directory_snapshot(path)
    app = open_dialog(directory, "function", "delete", record_id=30)
    app.button[0].click().run()
    assert not app.exception and not app.error
    after = directory_snapshot(path)
    assert len(after.pop("function")) == len(before.pop("function")) - 1
    assert before == after


def settings_app(path: str, actor: Actor) -> None:
    """Render Settings through the same explicit actor composition as the application."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_settings_workspace
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.settings import render_settings_view

    set_current_locale("en")
    workspace = create_settings_workspace(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))
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
def test_project_configuration_catalog_crud_does_not_change_fixed_application_roles(directory, kind, tab):
    path, _ = directory
    before = directory_snapshot(path)
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
    assert directory_snapshot(path) == before


def test_resource_inspector_updates_and_removes_mappings_without_changing_project_allocations(directory):
    path, _ = directory
    with closing(get_db(path)) as connection, connection:
        connection.execute("UPDATE resource_pool SET capacity_fte=0.5,description='Delivery capacity' WHERE id=1")
        connection.execute("INSERT INTO team_function(team_id,function_id) VALUES(10,10)")
        connection.execute("INSERT INTO resource_pool_mapping(id,pool_id,target_type,target_id,allocation_pct) VALUES(1,1,'function',10,50),(2,1,'employee',10,40),(3,1,'team',10,25)")
    before = directory_snapshot(path)
    app = AppTest.from_function(settings_app, args=directory, default_timeout=30)
    app.session_state["settings_active_tab"] = "resource_pools"
    app.run()
    assert not app.exception
    assert any("OVERASSIGNMENT" in item.value for item in app.error)
    text = "\n".join(item.value for item in app.markdown)
    assert "Legacy function" in text and "Rae Example" in text and "Delivery" in text
    # Native tab containers are not serialized as widgets by Streamlit 1.63 AppTest.
    app.session_state["settings_active_tab"] = "resource_pools"
    app.number_input(key="num_alloc_pct_1").set_value(75).run()
    assert not app.exception
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT allocation_pct FROM resource_pool_mapping WHERE id=1").fetchone()[0] == 75
    app.session_state["settings_active_tab"] = "resource_pools"
    app.button(key="btn_del_map_3").click().run()
    assert not app.exception
    with closing(get_db(path)) as connection:
        mappings = connection.execute("SELECT id,allocation_pct FROM resource_pool_mapping ORDER BY id").fetchall()
        assert mappings == [(1, 75), (2, 40)], {
            "mappings": mappings, "widgets": [(item.key, item.value) for item in app.number_input],
            "errors": [item.value for item in app.error],
        }
        assert connection.execute("SELECT id FROM resource_pool_assignment ORDER BY id").fetchall() == [(1,), (2,)]
    assert directory_snapshot(path) == before


@pytest.mark.parametrize("change", ["deleted", "moved"])
def test_unassignment_confirmation_rechecks_the_selected_pool_and_current_record(directory, change):
    path, _ = directory
    app = open_dialog(directory, "assignment", "delete", record_id=1)
    with closing(get_db(path)) as connection, connection:
        if change == "deleted":
            connection.execute("DELETE FROM resource_pool_assignment WHERE id=1")
        else:
            connection.execute("INSERT INTO resource_pool(id,name) VALUES(2,'Other pool')")
            connection.execute("UPDATE resource_pool_assignment SET pool_id=2 WHERE id=1")
    app.button(key="confirm_unassign_1").click().run()
    assert not app.exception and app.error
    assert "no longer exists in this pool" in app.error[0].value
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT id,pool_id FROM resource_pool_assignment ORDER BY id").fetchall() == (
            [(2, 1)] if change == "deleted" else [(1, 2), (2, 1)]
        )
