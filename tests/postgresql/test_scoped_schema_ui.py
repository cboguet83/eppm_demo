"""Real schema administration preserves application identities and fixed grants."""

from unittest.mock import patch

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import Actor
from app.runtime import RuntimeResources
from app.main import create_schema_service
from tests.postgresql.business import business


def schema_app(path: RuntimeResources, actor: Actor) -> None:
    """Render the actual schema screen with a trusted application actor."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_schema_service, create_project_type_service
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.schema import render_schema_definition

    set_current_locale("en")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_schema_definition(create_schema_service(path, access=access), create_project_type_service(path, access=access))


@pytest.mark.parametrize("grant", ["project_editor", "access_admin"])
def test_schema_administration_denies_non_business_roles_before_loading_catalogs(business, grant):
    path, service, admin, editor, _ = business
    if grant == "access_admin":
        for assignment in service.assignments(admin, editor.actor.user_id):
            service.revoke(admin, assignment["id"])
        service.grant(admin, editor.actor.user_id, grant, {"kind": "all"})
    app = AppTest.from_function(schema_app, args=(path, editor.actor), default_timeout=30).run()
    assert not app.exception and "not permitted" in app.error[0].value
    assert not app.text_input and not app.selectbox and not app.dataframe


def test_business_only_administrator_can_translate_and_clear_aliases_without_changing_grants(pg_database, business):
    path, service, admin, editor, _ = business
    service.grant(admin, editor.actor.user_id, "business_admin", {"kind": "all"})
    schema = create_schema_service(path, access=editor)
    with psycopg.connect(pg_database.operator_url) as connection:
        identities = connection.execute("SELECT * FROM eppm.app_identity").fetchall()
        grants = connection.execute("SELECT * FROM eppm.app_role_assignment ORDER BY id").fetchall()
        options = connection.execute("SELECT * FROM eppm.schema_param_options ORDER BY id").fetchall()
    app = AppTest.from_function(schema_app, args=(path, editor.actor), default_timeout=30).run()
    app.selectbox(key="schema_alias_property").select("DEPT").run()
    app.selectbox(key="schema_alias_locale").select("fr").run()
    next(widget for widget in app.text_input if widget.label == "Translated alias").input("Département")
    next(button for button in app.button if button.label == "Save alias translation").click().run()
    assert not app.exception and not app.error
    assert schema.get_alias_translations("fr") == {"DEPT": "Département"}
    assert schema.get_alias_translations("en") == {}
    next(widget for widget in app.text_input if widget.label == "Translated alias").input(" ")
    next(button for button in app.button if button.label == "Save alias translation").click().run()
    assert not app.exception and not app.error
    assert schema.get_alias_translations("fr") == {}
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT * FROM eppm.app_identity").fetchall() == identities
        assert connection.execute("SELECT * FROM eppm.app_role_assignment ORDER BY id").fetchall() == grants
        assert connection.execute("SELECT * FROM eppm.schema_param_options ORDER BY id").fetchall() == options
        assert connection.execute("SELECT text_value FROM eppm.project_property_value WHERE project_id=1 AND param_id='DEPT'").fetchone() == ("Finance",)


def test_empty_choice_properties_render_without_fabricating_scope_values(business):
    path, service, admin, editor, _ = business
    service.grant(admin, editor.actor.user_id, "business_admin", {"kind": "all"})
    schema = create_schema_service(path, access=editor)
    group_id = schema.create_group("Workflow", 1)
    grouped = schema.create_parameter(None, group_id, "Empty grouped category", "ENUM")
    ungrouped = schema.create_parameter(None, None, "Empty ungrouped category", "ENUM")
    app = AppTest.from_function(schema_app, args=(path, editor.actor), default_timeout=30).run()
    # The options editor has its own unkeyed selector; select by its actual label.
    target = next(widget for widget in app.selectbox if widget.label == "Select Parameter to Configure")
    target.select(grouped).run()
    assert not app.exception and not app.error
    assert any("No options configured" in item.value for item in app.caption)
    assert sum("No options defined" in item.value for item in app.markdown) == 2
    assert not [option for option in schema.get_all_options() if option.param_id in {grouped, ungrouped}]


@pytest.mark.parametrize("entity", ["group", "property"])
def test_schema_save_does_not_recreate_a_definition_deleted_by_another_session(pg_database, business, entity):
    from app.application.services.schema import SchemaService

    path, _, _, _, manager = business
    schema = create_schema_service(path, access=manager)
    group_id = schema.create_group("Concurrent group", 1)
    parameter_id = schema.create_parameter("UNUSED", group_id, "Unused property", "TEXT")
    with psycopg.connect(pg_database.operator_url) as connection:
        grants = connection.execute("SELECT * FROM eppm.app_role_assignment ORDER BY id").fetchall()
        values = connection.execute("SELECT * FROM eppm.project_property_value").fetchall()
    app = AppTest.from_function(schema_app, args=(path, manager.actor), default_timeout=30).run()
    if entity == "property":
        next(widget for widget in app.selectbox if widget.label == "Edit custom property").select(parameter_id).run()
    method = "update_group" if entity == "group" else "update_parameter"
    original = getattr(SchemaService, method)

    def delete_then_save(instance, *args, **kwargs):
        if entity == "group":
            schema.delete_group(group_id)
        else:
            schema.delete_parameter(parameter_id)
        return original(instance, *args, **kwargs)

    with patch.object(SchemaService, method, autospec=True, side_effect=delete_then_save):
        suffix = "Save Changes" if entity == "group" else "Save property"
        next(button for button in app.button if button.label.endswith(suffix)).click().run()
    assert not app.exception and not app.success
    expected = "The selected group no longer exists." if entity == "group" else "Unknown property"
    assert app.error[0].value == expected
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT * FROM eppm.app_role_assignment ORDER BY id").fetchall() == grants
        assert connection.execute("SELECT * FROM eppm.project_property_value").fetchall() == values
    if entity == "group":
        assert schema.get_all_groups() == []
        assert next(item for item in schema.get_all_parameters() if item.param_id == parameter_id).group_id is None
    else:
        assert parameter_id not in {item.param_id for item in schema.get_all_parameters()}
