"""Real pool dialogs and Settings routing through the migrated services."""

from unittest.mock import patch

import psycopg
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.domain.organization.models import Employee, Team
from app.domain.resources.models import PoolAssignment, ResourcePool, ResourcePoolGroup
from app.application.services.business_access import BusinessAccess
from app.main import create_organization_service, create_resource_pool_service
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.runtime import RuntimeResources
from tests.postgresql.ui import native_screen


@pytest.fixture
def database(authorized) -> RuntimeResources:
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
        connection.execute("INSERT INTO eppm.tag_dictionnary(id,tag) VALUES(1,'Priority')")
        connection.execute("UPDATE eppm.project SET name='<script>project</script>' WHERE id=1")
    return RuntimeResources(authorized.database, authorized.key)


@pytest.fixture
def access(authorized) -> BusinessAccess:
    return authorized.binding(4).access


def dialog(resources: RuntimeResources, access: BusinessAccess, invocation: str) -> AppTest:
    """Keep the production modal open across AppTest's full-script reruns."""
    app = native_screen(
        f"""
from app.main import create_resource_pool_service, create_organization_service
from app.presentation.components import resource_pool_dialogs as dialogs
from app.presentation.components.organization_frames import teams_frame, employees_frame
from app.presentation.i18n import set_current_locale
set_current_locale('en')
service = create_resource_pool_service(runtime, access=access)
org = create_organization_service(runtime, access=access)
teams = teams_frame(org.get_all_teams())
employees = employees_frame(org.get_all_employees())
dialogs.{invocation}
""",
        resources, access,
    ).run()
    assert not app.exception, [item.message for item in app.exception]
    return app


def test_pool_dialogs_create_edit_and_delete_with_tags(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    app = dialog(database, access, "_open_add_pool_dialog(service)")
    app.button[0].click().run()
    assert app.error and service.get_all_pools() == []
    app.text_input[0].input("Delivery")
    app.number_input[0].set_value(2.5)
    app.multiselect[0].set_value([1])
    app.button[0].click().run()
    assert not app.exception
    pool = service.get_all_pools()[0]
    assert pool.capacity_fte == 2.5
    assert service.get_pool_tags(pool.id)[0].tag_name == "Priority"
    app = dialog(database, access, f"_open_edit_pool_dialog(service, {pool.id})")
    app.text_input[0].input("Renamed")
    app.multiselect[0].set_value([])
    app.button[0].click().run()
    assert not app.exception
    assert service.get_pool_by_id(pool.id).name == "Renamed"
    assert service.get_pool_tags(pool.id) == []
    app = dialog(database, access, f"_open_delete_pool_dialog(service, {pool.id}, 'Renamed')")
    app.button[0].click().run()
    assert not app.exception and service.get_all_pools() == []


def test_failed_tag_write_rolls_back_pool_and_displays_safe_error(database: RuntimeResources, access: BusinessAccess, authorized) -> None:
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_pool_tag() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private database detail' USING ERRCODE='23514'; END $$""")
        connection.execute("""CREATE TRIGGER reject_pool_tag BEFORE INSERT ON eppm.resource_pool_tag
            FOR EACH ROW EXECUTE FUNCTION eppm.reject_pool_tag()""")
    app = dialog(database, access, "_open_add_pool_dialog(service)")
    app.text_input[0].input("Failed")
    app.multiselect[0].set_value([1])
    app.button[0].click().run()
    assert not app.exception and app.error
    assert "private database detail" not in app.error[0].value
    assert create_resource_pool_service(database, access=access).get_all_pools() == []


def test_group_dialogs_save_recursive_members_and_exclude_cycle_choices(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool("Delivery"))
    child = service.create_pool_group(ResourcePoolGroup("Child"), pool_ids=[pool])
    app = dialog(database, access, "_open_add_pool_group_dialog(service)")
    app.text_input[0].input("Parent")
    app.multiselect[0].set_value([pool])
    app.multiselect[1].set_value([child])
    app.button[0].click().run()
    assert not app.exception
    parent = next(group.id for group in service.get_all_pool_groups() if group.name == "Parent")
    assert service.get_group_descendant_pool_ids(parent) == [pool]
    app = dialog(database, access, f"_open_edit_pool_group_dialog(service, {child})")
    assert app.multiselect[1].options == []
    app.text_input[0].input("Renamed child")
    app.multiselect[0].set_value([])
    app.button[0].click().run()
    assert not app.exception and service.get_group_direct_member_ids(child) == ([], [])
    app = dialog(database, access, f"_open_delete_pool_group_dialog(service, {parent}, 'Parent')")
    app.button[0].click().run()
    assert not app.exception and service.get_pool_group_by_id(parent) is None
    assert service.get_pool_by_id(pool) is not None


def test_mapping_dialog_preserves_team_and_employee_choices(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool("Delivery"))
    org = create_organization_service(database, access=access)
    team = org.create_team(Team("Team"))
    employee = org.create_employee(Employee("Ada", "Lovelace", "ada@example.invalid", "ADA"))
    app = dialog(database, access, f"_open_add_pool_mapping_dialog(service, {pool}, teams, employees)")
    app.slider[0].set_value(50)
    app.button[0].click().run()
    assert not app.exception
    assert [
        (mapping.target_id, mapping.allocation_pct)
        for mapping in service.get_mappings_by_pool(pool)
    ] == [(team, 50)]
    app.get("button_group")[0].set_value("employee").run()
    app.slider[0].set_value(25)
    app.button[0].click().run()
    assert not app.exception
    assert any(
        mapping.target_type == "employee"
        and mapping.target_id == employee
        and mapping.allocation_pct == 25
        for mapping in service.get_mappings_by_pool(pool)
    )


def test_concurrent_delete_and_read_failures_do_not_report_success(database: RuntimeResources, access: BusinessAccess, authorized) -> None:
    service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool("Delivery"))
    app = dialog(database, access, f"_open_delete_pool_dialog(service, {pool}, 'Delivery')")
    service.delete_pool(pool)
    app.button[0].click().run()
    assert not app.exception and app.error and not app.toast
    assert "no longer exists" in app.error[0].value
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('REVOKE SELECT ON eppm.tag_dictionnary FROM eppm_runtime')
    try:
        app = dialog(database, access, "_open_add_pool_dialog(service)")
        assert app.error and 'tag_dictionnary' not in app.error[0].value
        assert authorized.setup.runtime_url not in app.error[0].value
    finally:
        with psycopg.connect(authorized.setup.operator_url) as connection:
            connection.execute('GRANT SELECT ON eppm.tag_dictionnary TO eppm_runtime')


def test_settings_pool_route_supplies_safe_row_data_and_individual_actions(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool("Delivery", capacity_fte=2))
    assignment = service.create_assignment(
        PoolAssignment(pool, 1, 1, notes="<img src=x onerror=alert(1)>")
    )
    app = native_screen(
        f"""
from app.main import create_organization_service
from app.presentation.pages.settings import render_settings_view
from app.main import create_settings_workspace
render_settings_view(create_settings_workspace(runtime, access=access))
""",
        database, access,
    )
    app.session_state["settings_active_tab"] = "resource_pools"
    with patch(
        "app.application.services.resource_pools.ResourcePoolService.get_all_pool_groups",
        side_effect=AssertionError("Closed groups loaded"),
    ), patch("app.presentation.components.action_table.action_table", return_value=None) as table:
        app.run()
    assert not app.exception and len(app.metric) == 5
    rows, columns, actions = table.call_args.args
    assert rows[0]["project"] == "<script>project</script>"
    assert rows[0]["notes"] == "<img src=x onerror=alert(1)>"
    assert rows[0]["id"] == assignment
    assert actions == {"open": "Go to", "unassign": "Unassign"}
    assert not any(button.key == f"btn_unassign_{pool}" for button in app.button)
    assert service.get_assignment_by_id(assignment)
    app = dialog(database, access, f"_confirm_unassign(service, {pool}, {assignment}, 'Project')")
    app.button(key=f"confirm_unassign_{assignment}").click().run()
    assert not app.exception and service.get_assignment_by_id(assignment) is None


def test_open_group_inspector_shows_deduplicated_members(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool("Delivery"))
    service.create_pool_group(ResourcePoolGroup("Group"), pool_ids=[pool])
    real_expander = st.expander

    def expanded(*args, **kwargs):
        kwargs["expanded"] = True
        return real_expander(*args, **kwargs)

    # Control only expander visibility; the widgets and application queries are real.
    with patch("streamlit.expander", side_effect=expanded):
        app = dialog(database, access, "_render_pool_groups_management(service)")
    assert app.dataframe[0].value.iloc[0]["recursive_pool_count"] == 1
    assert any("Pool: Delivery" in item.value for item in app.caption)
