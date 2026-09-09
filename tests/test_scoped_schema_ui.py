"""Real schema administration preserves application identities and fixed grants."""

from contextlib import closing

import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import Actor
from app.infrastructure.database.connection import get_db
from app.main import create_schema_service
from tests.test_business_transaction_security import business as business


def schema_app(path: str, actor: Actor) -> None:
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


def test_business_only_administrator_can_translate_and_clear_aliases_without_changing_grants(business):
    path, service, admin, editor, _ = business
    service.grant(admin, editor.actor.user_id, "business_admin", {"kind": "all"})
    schema = create_schema_service(path, access=editor)
    with closing(get_db(path)) as connection:
        identities = connection.execute("SELECT * FROM app_identity").fetchall()
        grants = connection.execute("SELECT * FROM app_role_assignment ORDER BY id").fetchall()
        options = connection.execute("SELECT * FROM schema_param_options ORDER BY id").fetchall()
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
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT * FROM app_identity").fetchall() == identities
        assert connection.execute("SELECT * FROM app_role_assignment ORDER BY id").fetchall() == grants
        assert connection.execute("SELECT * FROM schema_param_options ORDER BY id").fetchall() == options
        assert connection.execute("SELECT text_value FROM project_property_value WHERE project_id=1 AND param_id='DEPT'").fetchone() == ("Finance",)


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
