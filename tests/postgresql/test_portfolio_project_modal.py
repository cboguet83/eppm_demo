"""Project modal saves, typed drafts and current authorization with real storage."""

from unittest.mock import patch

import psycopg

import pytest
from streamlit.testing.v1 import AppTest

from app.main import create_project_service
from tests.postgresql.test_dashboard_ui import business as dashboard_business, runtime
from tests.test_fragment_reruns import FragmentRun
from tests.test_portfolio_project_modal import open_form, submit, workflow_app


@pytest.fixture
def business(dashboard_business, authorized):
    """Retain scoped Department properties in the native two-project fixture."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES('DEPT','Department','ENUM')")
        connection.execute("INSERT INTO eppm.schema_param_options(param_id,option_value) VALUES('DEPT','Finance'),('DEPT','Delivery')")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES(1,'DEPT','text','Finance')")
    return dashboard_business

@pytest.mark.parametrize("operation", ["create", "edit"])
def test_project_save_closes_modal_and_refreshes_grid_and_selection_once(business, operation):
    from app.presentation.pages.portfolio import _portfolio_grid, _portfolio_selection

    path, _, _, _, manager = business
    app = open_form(path, manager.actor, operation)
    with patch("app.presentation.pages.portfolio._portfolio_grid", wraps=_portfolio_grid) as grid, \
         patch("app.presentation.pages.portfolio._portfolio_selection", wraps=_portfolio_selection) as selection:
        submit(app, changes={"name": "Saved locally"}, links=[{"alias": "Custom link", "url": "https://example.com"}])
    assert grid.call_count == selection.call_count == 2  # initial full run + one targeted refresh
    assert "portfolio_project_modal_state" not in app.session_state
    service = create_project_service(path, access=manager)
    identity = app.session_state["selected_portfolio_project_id"] if operation == "create" else 1
    assert service.get_project_by_id(identity).name == "Saved locally"
    assert service.get_links(identity) == [{"alias": "Custom link", "url": "https://example.com"}]
    assert app.session_state["selected_portfolio_project_id"] == identity


@pytest.mark.parametrize("changes,links,error", [
    ({"name": ""}, None, "required"),
    ({"planned_budget": ""}, None, "budget"),
    ({"planned_budget": None}, None, "Invalid project field"),
    ({"planned_budget": True}, None, "Invalid project field"),
    ({"planned_budget": 10 ** 400}, None, "Invalid project field"),
    ({"name": "Retained"}, [{"url": "javascript:alert(1)", "alias": "Invalid"}], "URL"),
])
def test_failed_project_save_keeps_draft_and_does_not_write(business, changes, links, error):
    path, _, _, _, manager = business
    app = open_form(path, manager.actor)
    submit(app, changes=changes, links=links)
    draft = app.session_state["portfolio_project_modal_state"]
    assert error.lower() in draft.form["error"].lower()
    assert create_project_service(path, access=manager).get_project_by_id(1).name == "Visible"


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_retained_project_save_rechecks_disabled_account(business, operation):
    path, service, admin, editor, _ = business
    service.grant(admin, editor.actor.user_id, "business_admin", {"kind": "all"})
    app = open_form(path, editor.actor, operation)
    submit(app, changes={"name": "Forbidden"}, before=lambda: service.set_status(admin, editor.actor.user_id, "disabled"))
    assert "not permitted" in app.session_state["portfolio_project_modal_state"].form["error"]


@pytest.mark.parametrize("kind,changes", [("delete", {}), ("save", {"p:DEPT": "Delivery"})])
def test_editor_cannot_forge_delete_or_scope_fields(business, kind, changes):
    path, _, _, editor, _ = business
    app = open_form(path, editor.actor)
    assert not app.session_state["portfolio_project_modal_state"].form["can_delete"]
    submit(app, kind=kind, changes=changes)
    assert "not permitted" in app.session_state["portfolio_project_modal_state"].form["error"]
    assert create_project_service(path, access=editor).get_project_by_id(1)


@pytest.mark.parametrize("kind", ["cancel", "delete"])
def test_project_cancel_and_delete_have_local_closure(business, kind):
    path, _, _, _, manager = business
    app = open_form(path, manager.actor)
    submit(app, kind=kind)
    assert "portfolio_project_modal_state" not in app.session_state
    project = create_project_service(path, access=manager).get_project_by_id(1)
    assert (project is None) == (kind == "delete")


def test_project_type_change_preserves_edited_drafts_and_uses_new_creation_defaults(business):
    from app.main import create_schema_service, create_project_type_service

    path, _, _, _, manager = business
    schema, types = create_schema_service(path, access=manager), create_project_type_service(path, access=manager)
    schema.create_parameter("note", None, "Note", "TEXT")
    schema.create_parameter("due", None, "Due", "DATE")
    first = types.create_type("First")
    second = types.create_type("Second")
    types.save_rule(first, "note", has_default=True, default_value="First default")
    types.save_rule(second, "note", has_default=True, default_value="Second default")
    app = open_form(path, manager.actor, "create")
    submit(app, "type", {"project_type_id": str(first)})
    assert app.session_state["portfolio_project_modal_state"].form["values"]["p:note"] == "First default"
    submit(app, "type", {"project_type_id": str(second), "p:due": "2027-04-12"})
    assert app.session_state["portfolio_project_modal_state"].form["values"]["p:note"] == "Second default"
    submit(app, "type", {"project_type_id": str(first), "p:note": "User draft"})
    submit(app, changes={"name": "Typed project"})
    project = create_project_service(path, access=manager).get_project_by_id(app.session_state["selected_portfolio_project_id"])
    assert project.dynamic_attributes == {"DEPT": "", "note": "User draft", "due": "2027-04-12"}


@pytest.mark.parametrize("mutate", [
    lambda event: event.update(values={}),
    lambda event: event.update(links=[{"alias": "Only alias"}]),
    lambda event: event.update(dirty=["unknown"]),
    lambda event: event["values"].update(name=[]),
])
def test_malformed_project_payloads_are_rejected_without_losing_the_form(business, mutate):
    path, _, _, _, manager = business
    app = open_form(path, manager.actor)
    submit(app, mutate=mutate)
    assert app.session_state["portfolio_project_modal_state"].form["error"]


def test_obsolete_project_form_token_cannot_submit_a_different_draft(business):
    path, _, _, _, manager = business
    app = open_form(path, manager.actor)
    submit(app, changes={"name": "Stale"}, mutate=lambda event: event.update(token="obsolete"))
    assert create_project_service(path, access=manager).get_project_by_id(1).name == "Visible"


@pytest.mark.parametrize("kind", ["save", "delete"])
def test_project_deleted_while_its_form_is_open_is_not_recreated(business, kind):
    path, _, _, _, manager = business
    app = open_form(path, manager.actor)
    service = create_project_service(path, access=manager)
    submit(app, kind=kind, before=lambda: service.delete_project(1))
    assert ("not permitted" if kind == "save" else "no longer exists") in app.session_state["portfolio_project_modal_state"].form["error"]
    assert service.get_project_by_id(1) is None


@pytest.mark.parametrize("kind,error", [("delete", "Create the project"), ("unknown", "")])
def test_unavailable_project_form_actions_cannot_create_or_delete(business, authorized, kind, error):
    path, _, _, _, manager = business
    app = open_form(path, manager.actor, "create")
    submit(app, kind=kind)
    message = app.session_state["portfolio_project_modal_state"].form["error"]
    assert error in message if error else message == ""
    assert authorized.query('SELECT id FROM eppm.project ORDER BY id', user_id=4) == [(1,), (2,)]


@pytest.mark.parametrize("revoked", [False, True])
def test_template_request_rechecks_permission_and_template_identity(business, revoked):
    path, service, admin, editor, _ = business
    app = open_form(path, editor.actor)

    def revoke():
        for assignment in service.assignments(admin, editor.actor.user_id):
            service.revoke(admin, assignment["id"])
        service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})

    submit(app, "type", {"project_type_id": "999"}, before=revoke if revoked else None)
    assert ("permission" if revoked else "valid project template") in app.session_state["portfolio_project_modal_state"].form["error"]


@pytest.mark.parametrize("missing", [False, True])
def test_opening_rechecks_stale_button_permission_and_project_identity(business, missing):
    from app.application.services.projects import ProjectService

    path, service, admin, editor, manager = business
    actor = manager if missing else editor
    app = AppTest.from_function(workflow_app, args=(path, actor.actor), default_timeout=30)
    app.session_state["selected_portfolio_project_id"] = 1
    original = ProjectService.get_project_by_id
    dispatched = False

    def prepare():
        nonlocal dispatched
        dispatched = True
        if not missing:
            for assignment in service.assignments(admin, editor.actor.user_id):
                service.revoke(admin, assignment["id"])
            service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})

    def concurrent_delete(owner, project_id):
        if dispatched and missing:
            owner.delete_project(project_id)
        return original(owner, project_id)

    with patch.object(ProjectService, "get_project_by_id", concurrent_delete):
        FragmentRun("btn_edit_details_1", prepare, widget_trigger=True).run(app)
    assert "portfolio_project_modal_state" not in app.session_state
    assert any(("no longer exists" if missing else "permission") in error.value for error in app.error)


def test_project_multivalue_properties_and_mandatory_labels_survive_a_save(business):
    from app.main import create_schema_service, create_project_type_service

    path, _, _, _, manager = business
    schema = create_schema_service(path, access=manager)
    schema.create_parameter("labels", None, "Labels", "TAGS")
    schema.create_parameter("choices", None, "Choices", "MULTI_ENUM")
    types = create_project_type_service(path, access=manager)
    template = types.create_type("Required tags")
    types.save_rule(template, "labels", mandatory_override=True)
    app = open_form(path, manager.actor, "create")
    submit(app, "type", {"project_type_id": str(template)})
    assert any(field["label"] == "Labels *" for field in app.session_state["portfolio_project_modal_state"].form["fields"])
    submit(app, changes={"name": "Tagged", "p:labels": ["First", "Second"], "p:choices": []})
    project = create_project_service(path, access=manager).get_project_by_id(app.session_state["selected_portfolio_project_id"])
    assert project.dynamic_attributes["labels"] == ["First", "Second"]


def test_project_save_does_not_close_or_report_success_for_an_unchanged_record(business):
    from app.application.services.projects import ProjectService

    path, _, _, _, manager = business
    app = open_form(path, manager.actor)
    with patch.object(ProjectService, "update_project", return_value=False):
        submit(app, changes={"name": "Unwritten"})
    assert "no longer exists" in app.session_state["portfolio_project_modal_state"].form["error"]
    assert create_project_service(path, access=manager).get_project_by_id(1).name == "Visible"
