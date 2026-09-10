"""Resource Settings entry points retain role, pool and allocation boundaries."""

from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.domain.access.models import Actor
from app.infrastructure.database.connection import get_db
from tests.test_business_transaction_security import business as business


def resource_settings_app(path: str, actor: Actor) -> None:
    """Run the production resource Settings page with an explicit application actor."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_resource_pool_service, create_pool_capacity_service, create_organization_service
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.resource_pools import render_resource_pools

    set_current_locale("en")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_resource_pools(
        create_resource_pool_service(path, access=access),
        create_pool_capacity_service(path, access=access),
        create_organization_service(path, access=access), "2. Planning & Step Loader",
    )


@pytest.fixture
def expanded_groups():
    """Adapt only expander scheduling: AppTest does not serialize native expanders."""
    real_expander = st.expander

    def expanded(*args, **kwargs):
        return real_expander(*args, **{**kwargs, "expanded": True})

    with patch("streamlit.expander", side_effect=expanded):
        yield


@pytest.mark.parametrize("action", ["create_pool", "edit_pool", "delete_pool", "new_group", "edit_group", "delete_group", "add_mapping"])
def test_business_administrator_resource_controls_open_actual_dialogs_without_premature_writes(business, expanded_groups, action):
    path, _, _, _, manager = business
    with closing(get_db(path)) as connection, connection:
        connection.execute("INSERT INTO resource_pool_group(id,name) VALUES(1,'Delivery group')")
        connection.execute("INSERT INTO tag_dictionnary(id,tag) VALUES(1,'Priority')")
        connection.execute("INSERT INTO resource_pool_tag(pool_id,tag_id) VALUES(1,1)")
        connection.execute("UPDATE resource_pool SET description='Pool details' WHERE id=1")
        before = {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in (
            "resource_pool", "resource_pool_group", "resource_pool_assignment", "resource_pool_mapping", "app_role_assignment",
        )}
    app = AppTest.from_function(resource_settings_app, args=(path, manager.actor), default_timeout=30).run()
    assert not app.exception and not app.error
    if action in {"edit_pool", "delete_pool", "add_mapping"}:
        key = {"edit_pool": "btn_edit_pool_1", "delete_pool": "btn_del_pool_1", "add_mapping": "btn_add_map_1"}[action]
        button = app.button(key=key)
    else:
        suffix = {"create_pool": "Create Pool", "new_group": "New group", "edit_group": "Edit", "delete_group": "Delete"}[action]
        button = next(item for item in app.button if item.label.endswith(suffix))
    button.click().run()
    assert not app.exception and not app.error and app.get("dialog")
    if action == "add_mapping":
        assert any("No teams available" in item.value for item in app.warning)
    elif action in {"delete_pool", "delete_group"}:
        assert app.warning
    else:
        assert app.get("dialog")[0].text_input
    with closing(get_db(path)) as connection:
        assert {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in before} == before


def test_empty_resource_group_inspector_does_not_invent_members_or_offer_editing(business, expanded_groups):
    path, _, _, _, manager = business
    app = AppTest.from_function(resource_settings_app, args=(path, manager.actor), default_timeout=30).run()
    assert not app.exception and not app.error
    assert any("No pool groups yet" in item.value for item in app.info)
    assert not any(item.key == "selected_resource_pool_group" for item in app.selectbox)
    assert app.button(key="btn_edit_pool_1")


def test_mapping_dialog_empty_employee_branch_prevents_saving_an_invalid_target(business):
    path, _, _, _, manager = business

    def dialog(path, actor):
        import pandas as pd
        from app.application.services.access import AuthorizationPolicy, SessionLimits
        from app.application.services.business_access import BusinessAccess
        from app.main import create_resource_pool_service
        from app.presentation.components.resource_pool_dialogs import _open_add_pool_mapping_dialog

        access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
        _open_add_pool_mapping_dialog(create_resource_pool_service(path, access=access), 1, pd.DataFrame(), pd.DataFrame())

    app = AppTest.from_function(dialog, args=(path, manager.actor)).run()
    app.get("button_group")[0].set_value("employee").run()
    assert not app.exception and not app.error
    assert any("No employees available" in item.value for item in app.warning)
    assert not app.button and not app.selectbox
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT * FROM resource_pool_mapping").fetchall() == []


@pytest.mark.parametrize("target", [1, 3])
def test_allocation_row_unassignment_can_only_open_for_an_assignment_in_the_selected_pool(business, target):
    import streamlit as st
    path, _, _, _, manager = business
    with closing(get_db(path)) as connection, connection:
        connection.execute("INSERT INTO resource_pool(id,name,capacity_fte) VALUES(2,'Other pool',1)")
        connection.execute("INSERT INTO resource_pool_assignment(id,pool_id,project_id,fte_assigned) VALUES(3,2,1,1)")
    component = Mock(return_value=SimpleNamespace(action={"id": target, "action": "unassign"}))
    register = st.components.v2.component
    with patch("streamlit.components.v2.component", side_effect=lambda name, **kwargs:
               component if name == "eppm_action_table" else register(name, **kwargs)):
        app = AppTest.from_function(resource_settings_app, args=(path, manager.actor), default_timeout=30)
        app.session_state["target_resource_pool_id"] = 1
        app.run()
    assert not app.exception and not app.error
    assert {row["id"] for row in component.call_args.kwargs["data"]["rows"]} == {1, 2}
    assert bool(app.get("dialog")) == (target == 1)
    if target == 1:
        assert app.button(key="confirm_unassign_1")
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT id FROM resource_pool_assignment ORDER BY id").fetchall() == [(1,), (2,), (3,)]
