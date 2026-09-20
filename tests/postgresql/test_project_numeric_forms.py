"""Native numeric project properties survive the custom form JSON boundary."""

from decimal import Decimal
import json

import pytest

from app.main import create_project_service, create_project_type_service, create_schema_service
from tests.postgresql.test_portfolio_project_modal import business, dashboard_business, runtime
from tests.test_portfolio_project_modal import open_form, submit


PRECISE = "9007199254740993.1234567890123456789"


@pytest.fixture
def numeric_business(business):
    """Persist a numeric value and creation default through the native services."""
    path, _, _, _, manager = business
    schema = create_schema_service(path, access=manager)
    projects = create_project_service(path, access=manager)
    types = create_project_type_service(path, access=manager)
    schema.create_parameter("quantity", None, "Quantity", "NUMBER")
    project = projects.get_project_by_id(1)
    projects.update_project(
        project_id=project.id, name=project.name, status=project.status,
        project_type_id=project.project_type_id, function_id=project.function_id,
        dynamic_attributes=project.dynamic_attributes | {"quantity": Decimal(PRECISE)},
    )
    types.save_rule(project.project_type_id, "quantity", has_default=True,
                    default_value=Decimal(PRECISE))
    assert projects.get_project_by_id(1).dynamic_attributes["quantity"] == Decimal(PRECISE)
    return business


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_native_numeric_values_serialize_the_complete_form_as_an_object(numeric_business, operation):
    path, _, _, _, manager = numeric_business
    app = open_form(path, manager.actor, operation)
    assert not app.exception
    component = next(item for item in app.get("bidi_component")
                     if item.proto.id.endswith("-portfolio_project_form"))
    payload = json.loads(component.proto.json)
    assert isinstance(payload, dict), "Numeric values must not stringify the entire form."
    assert payload["values"]["p:quantity"] == PRECISE


@pytest.mark.parametrize("operation", ["create", "edit"])
@pytest.mark.parametrize("quantity", [None, "-0.000000000000000000123456789", ""])
def test_numeric_values_remain_exact_when_unchanged_edited_or_cleared(numeric_business, operation, quantity):
    path, _, _, _, manager = numeric_business
    app = open_form(path, manager.actor, operation)
    changes = {"name": "Exact numeric property"}
    if quantity is not None:
        changes["p:quantity"] = quantity
    submit(app, changes=changes)
    assert "portfolio_project_modal_state" not in app.session_state
    project_id = app.session_state["selected_portfolio_project_id"] if operation == "create" else 1
    saved = create_project_service(path, access=manager).get_project_by_id(project_id)
    expected = None if quantity == "" else Decimal(PRECISE if quantity is None else quantity)
    assert saved.name == "Exact numeric property"
    assert saved.dynamic_attributes["quantity"] == expected


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-Infinity", "not a number"])
def test_invalid_numeric_text_keeps_the_form_open_and_the_database_unchanged(numeric_business, quantity):
    path, _, _, _, manager = numeric_business
    app = open_form(path, manager.actor)
    submit(app, changes={"name": "Must not persist", "p:quantity": quantity})
    draft = app.session_state["portfolio_project_modal_state"]
    assert draft.form["error"] == "Enter a finite numeric property value."
    assert draft.form["values"]["p:quantity"] == quantity
    saved = create_project_service(path, access=manager).get_project_by_id(1)
    assert saved.name != "Must not persist"
    assert saved.dynamic_attributes["quantity"] == Decimal(PRECISE)
    submit(app, changes={"p:quantity": "123.45678901234567890123456789"})
    saved = create_project_service(path, access=manager).get_project_by_id(1)
    assert saved.dynamic_attributes["quantity"] == Decimal("123.45678901234567890123456789")


@pytest.mark.parametrize("quantity", [None, 1, 0.1, True])
def test_numeric_property_boundary_rejects_non_text_json_values(numeric_business, quantity):
    path, _, _, _, manager = numeric_business
    app = open_form(path, manager.actor)
    submit(app, mutate=lambda event: event["values"].update({"p:quantity": quantity}))
    assert app.session_state["portfolio_project_modal_state"].form["error"] == "Invalid project field value."
    saved = create_project_service(path, access=manager).get_project_by_id(1)
    assert saved.dynamic_attributes["quantity"] == Decimal(PRECISE)
