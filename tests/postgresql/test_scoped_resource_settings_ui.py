"""Resource Settings entry points retain role, pool and allocation boundaries."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psycopg
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.domain.access.models import Actor
from app.runtime import RuntimeResources
from tests.postgresql.business import business


def resource_settings_app(path: RuntimeResources, actor: Actor) -> None:
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
def pool_tree_component() -> Iterator[Mock]:
    """Send real tree actions while retaining production payload validation."""
    component = Mock(return_value=SimpleNamespace(action=None))
    register = st.components.v2.component

    def register_component(name: str, **kwargs: object) -> object:
        if name == 'eppm_resource_pool_tree':
            return component
        return register(name, **kwargs)

    with patch('streamlit.components.v2.component', side_effect=register_component):
        yield component


@pytest.mark.parametrize("action", ["create_pool", "edit_pool", "delete_pool", "add_mapping"])
def test_business_administrator_resource_controls_open_actual_dialogs_without_premature_writes(pg_database, business, pool_tree_component, action):
    path, _, _, _, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.tag_dictionnary(id,tag) VALUES(1,'Priority')")
        connection.execute("INSERT INTO eppm.resource_pool_tag(pool_id,tag_id) VALUES(1,1)")
        connection.execute("UPDATE eppm.resource_pool SET description='Pool details' WHERE id=1")
        before = {table: connection.execute(f"SELECT * FROM eppm.{table} ORDER BY 1").fetchall() for table in (
            "resource_pool", "resource_pool_assignment", "resource_pool_mapping", "app_role_assignment",
        )}
    app = AppTest.from_function(resource_settings_app, args=(path, manager.actor), default_timeout=30).run()
    assert not app.exception and not app.error
    if action == 'create_pool':
        app.button(key='create_root_pool').click().run()
    else:
        tree_action = {'edit_pool': 'edit', 'delete_pool': 'delete', 'add_mapping': 'map'}[action]
        pool_tree_component.return_value = SimpleNamespace(action={'id': 1, 'action': tree_action})
        app.run()
    assert not app.exception and not app.error and app.get("dialog")
    if action == "add_mapping":
        assert app.multiselect(key='mapping_teams_1').options == []
        assert not app.number_input
    elif action in {"delete_pool", "delete_group"}:
        assert app.warning
    else:
        assert app.get("dialog")[0].text_input
    with psycopg.connect(pg_database.operator_url) as connection:
        assert {table: connection.execute(f"SELECT * FROM eppm.{table} ORDER BY 1").fetchall() for table in before} == before


def test_pool_tree_keeps_real_members_without_retired_group_selector(business, pool_tree_component):
    path, _, _, _, manager = business
    app = AppTest.from_function(resource_settings_app, args=(path, manager.actor), default_timeout=30).run()
    assert not app.exception and not app.error
    assert any("Summary counts exclude containers and deleted pools" in item.value for item in app.caption)
    assert not any(item.key == "selected_resource_pool_group" for item in app.selectbox)
    assert {row['id'] for row in pool_tree_component.call_args.kwargs['data']['rows']} == {1}


def test_mapping_dialog_empty_employee_branch_prevents_saving_an_invalid_target(pg_database, business):
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
    app.checkbox(key='direct_employee_mapping_mode_1').check().run()
    assert not app.exception and not app.error
    assert app.multiselect(key='mapping_employees_1').options == []
    assert not app.number_input and not app.selectbox
    next(item for item in app.button if item.label == 'Save mappings').click().run()
    assert not app.exception and not app.error
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT * FROM eppm.resource_pool_mapping").fetchall() == []


@pytest.mark.parametrize("target", [1, 3])
def test_allocation_row_unassignment_can_only_open_for_an_assignment_in_the_selected_pool(pg_database, business, target):
    import streamlit as st
    path, _, _, _, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(2,'Other pool',1)")
        connection.execute('INSERT INTO eppm.resource_pool_assignment(id,pool_id,project_id,fte_assigned,project_plan_id) VALUES (3,2,1,1,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))')
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
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT id FROM eppm.resource_pool_assignment ORDER BY id").fetchall() == [(1,), (2,), (3,)]
