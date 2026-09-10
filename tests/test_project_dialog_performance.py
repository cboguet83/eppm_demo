"""Project dialog isolation, retained drafts and current scoped editing controls."""

from unittest.mock import patch
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from app.application.services.portfolio import PortfolioService
from app.application.services.project_types import ProjectTypeService
from app.application.services.schema import SchemaService
from app.application.services.projects import ProjectService
from tests.test_business_transaction_security import business as business
from tests.test_fragment_reruns import FragmentRun
from tests.test_scoped_portfolio_collaboration_ui import project_details_fragment_app


def project_screen(path, actor, operation):
    """Put production project actions/dialogs beside an independently retained shell."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_workspace
    from app.presentation.components.project_dialogs import open_create_project_dialog, open_edit_project_dialog
    from app.presentation.pages.portfolio import _render_project_create_action, _render_project_edit_action
    from app.presentation.components.portfolio_project_dialog import render_project_modal

    st.session_state["shell_runs"] = st.session_state.get("shell_runs", 0) + 1
    st.sidebar.caption("Navigation and account")
    st.write("Project summary remains mounted")
    workspace = create_project_workspace(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))
    if operation == "create":
        open_create_project_dialog(workspace)
    elif operation == "edit":
        open_edit_project_dialog(1, workspace)
    elif operation == "create_action":
        _render_project_create_action(workspace)
    else:
        _render_project_edit_action(1, workspace)
    if operation.endswith("action"):
        render_project_modal(workspace)


@pytest.mark.parametrize("role,project_id,visible", [
    ("project_viewer", 1, False), ("project_approver", 1, False),
    ("project_editor", 1, True), ("project_editor", 2, False),
    ("business_admin", None, True), ("access_admin", None, False),
])
def test_edit_details_is_limited_to_existing_business_edit_permissions(business, role, project_id, visible):
    path, service, admin, editor, _ = business
    for assignment in service.assignments(admin, editor.actor.user_id):
        service.revoke(admin, assignment["id"])
    scope = {"kind": "all"} if project_id is None else {"kind": "projects", "project_ids": [project_id]}
    service.grant(admin, editor.actor.user_id, role, scope)
    app = AppTest.from_function(project_details_fragment_app, args=(path, editor.actor)).run()
    assert not app.exception
    actions = [button for button in app.button if button.key == "btn_edit_details_1"]
    assert bool(actions) == visible
    if visible:
        assert actions[0].label == "Edit details"


@pytest.mark.parametrize("operation,key", [("create_action", "btn_create_project_from_portfolio"), ("edit_action", "btn_edit_details_1")])
def test_opening_project_dialog_reruns_only_its_action_and_dialog(business, operation, key):
    path, _, _, _, manager = business
    app = AppTest.from_function(project_screen, args=(path, manager.actor, operation))
    rerun = FragmentRun(key, widget_trigger=True)
    rerun.run(app)
    assert app.session_state["shell_runs"] == 1
    assert app.session_state["portfolio_project_modal_state"].form["can_save"]
    deltas = [message for message in rerun.messages if message.WhichOneof("type") == "delta"]
    assert deltas and all(message.metadata.delta_path[0] != 1 for message in deltas)
    assert all(message.delta.fragment_id for message in deltas)


@pytest.mark.parametrize("operation,key", [("create", "portfolio_create_manager_3"), ("edit", "portfolio_edit_manager_1")])
def test_dialog_field_interaction_does_not_reload_reference_data_or_other_fields(business, operation, key):
    path, _, _, _, manager = business
    app = AppTest.from_function(project_screen, args=(path, manager.actor, operation))
    counts = {"catalog": 0, "types": 0, "template": 0, "aliases": 0, "project": 0}

    def counted(name, original):
        def read(*args, **kwargs):
            counts[name] += 1
            return original(*args, **kwargs)
        return read

    before = []
    rerun = FragmentRun(key, lambda: before.append(dict(counts)))
    with patch.object(PortfolioService, "get_catalog", counted("catalog", PortfolioService.get_catalog)), \
         patch.object(ProjectTypeService, "type_choices", counted("types", ProjectTypeService.type_choices)), \
         patch.object(ProjectTypeService, "template_reference", counted("template", ProjectTypeService.template_reference)), \
         patch.object(SchemaService, "alias_references", counted("aliases", SchemaService.alias_references)), \
         patch.object(ProjectService, "get_project_by_id", counted("project", ProjectService.get_project_by_id)):
        rerun.run(app)
    rerun.assert_isolated()
    assert counts == before[0]
    assert counts["catalog"] == counts["types"] == counts["template"] == counts["aliases"] == 1
    assert app.session_state["shell_runs"] == 1
    assert not any(message.delta.new_element.WhichOneof("type") == "dataframe" for message in rerun.messages)


@pytest.mark.parametrize("operation,key", [("create", "portfolio_create_manager_3"), ("edit", "portfolio_edit_manager_1")])
def test_retained_project_fields_deny_a_disabled_actor(business, operation, key):
    path, service, admin, editor, manager = business
    actor = manager.actor if operation == "create" else editor.actor
    app = AppTest.from_function(project_screen, args=(path, actor, operation))

    def disable():
        with service.gateway.transaction(write=True) as store:
            store.set_status(actor.user_id, "disabled", 1000)

    rerun = FragmentRun(key, disable)
    rerun.run(app)
    rerun.assert_isolated()
    assert "not permitted" in app.error[0].value
    assert app.session_state["shell_runs"] == 1


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_lazy_property_tabs_preserve_text_and_date_drafts_when_saved_from_another_tab(business, operation):
    from app.main import create_schema_service, create_project_service

    path, _, _, _, manager = business
    schema = create_schema_service(path, access=manager)
    first = schema.create_group("First section", 1)
    second = schema.create_group("Second section", 2)
    schema.create_parameter("note", first, "Note", "TEXT")
    schema.create_parameter("due", second, "Due", "DATE")
    identity = 3 if operation == "create" else 1
    prefix = f"portfolio_{operation}_{identity}"
    app = AppTest.from_function(project_screen, args=(path, manager.actor, operation)).run()
    assert app.text_input(key=prefix + "_note")
    assert not any(widget.key == prefix + "_due" for widget in app.date_input)
    app.text_input(key=prefix + "_name").set_value("Preserved draft")
    app.text_input(key=prefix + "_note").set_value("First tab draft").run()
    app.session_state[prefix + "_tabs"] = "Second section"
    app.run()
    app.date_input(key=prefix + "_due").set_value(date(2027, 4, 12)).run()
    app.session_state[prefix + "_tabs"] = "First section"
    app.run()
    assert app.text_input(key=prefix + "_note").value == "First tab draft"
    next(button for button in app.button if "Create project" in button.label or "Update Project" in button.label).click().run()
    assert not app.exception and not app.error
    saved = create_project_service(path, access=manager).get_project_by_id(identity)
    assert saved.name == "Preserved draft"
    assert saved.dynamic_attributes["note"] == "First tab draft"
    assert saved.dynamic_attributes["due"] == "2027-04-12"


def test_retained_project_fields_become_read_only_after_editor_is_downgraded(business):
    path, service, admin, editor, _ = business
    app = AppTest.from_function(project_screen, args=(path, editor.actor, "edit"))

    def downgrade():
        for assignment in service.assignments(admin, editor.actor.user_id):
            service.revoke(admin, assignment["id"])
        service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})

    rerun = FragmentRun("portfolio_edit_manager_1", downgrade)
    rerun.run(app)
    rerun.assert_isolated()
    assert app.text_input(key="portfolio_edit_1_name").disabled


@pytest.mark.parametrize("section", ["Project Contacts", "Project log"])
def test_creation_collaboration_tabs_explain_that_a_project_must_be_saved_first(business, section):
    path, _, _, _, manager = business
    app = AppTest.from_function(project_screen, args=(path, manager.actor, "create"))
    app.session_state["portfolio_create_3_tabs"] = section
    app.run()
    assert not app.exception
    assert any("Create the project to add contacts and log entries" in item.value for item in app.info)


@pytest.mark.parametrize("change", ["disabled", "read_only"])
def test_retained_creation_dialog_rechecks_permission_before_using_its_cached_choices(business, change):
    path, service, admin, _, manager = business
    app = AppTest.from_function(project_screen, args=(path, manager.actor, "create"))

    def remove_creation():
        if change == "disabled":
            with service.gateway.transaction(write=True) as store:
                store.set_status(admin.user_id, "disabled", 1000)
        else:
            service.grant(admin, admin.user_id, "project_viewer", {"kind": "all"})
            for assignment in service.assignments(admin, admin.user_id):
                if assignment["role"] == "business_admin":
                    service.revoke(admin, assignment["id"])

    rerun = FragmentRun("create_type_3", remove_creation)
    rerun.run(app)
    assert app.error
    assert not any(message.delta.new_element.WhichOneof("type") in {"selectbox", "text_input", "dataframe"}
                   for message in rerun.messages)
    assert not app.exception


def test_project_save_validates_empty_names_and_handles_deletion_while_the_dialog_is_open(business):
    from app.main import create_project_service

    path, _, _, _, manager = business
    app = AppTest.from_function(project_screen, args=(path, manager.actor, "edit")).run()
    app.text_input(key="portfolio_edit_1_name").set_value("   ")
    app.button(key="save_project_1").click().run()
    assert app.error and not app.exception
    service = create_project_service(path, access=manager)
    assert service.get_project_by_id(1).name == "Visible"
    app = AppTest.from_function(project_screen, args=(path, manager.actor, "edit"))
    rerun = FragmentRun("save_project_1", lambda: service.delete_project(1), widget_trigger=True)
    rerun.run(app)
    assert "not permitted" in app.error[0].value
    assert service.get_project_by_id(1) is None
