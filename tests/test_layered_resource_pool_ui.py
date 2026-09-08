"""Real pool dialogs and Settings routing through the migrated services."""

from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.domain.organization.models import Employee, Team
from app.domain.resources.models import PoolAssignment, ResourcePool, ResourcePoolGroup
from app.main import create_organization_service, create_resource_pool_service
from src.database.schema_init import init_db


@pytest.fixture
def database(tmp_path: Path) -> str:
    path = str(tmp_path / "pool-ui.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO tag_dictionnary(id,tag) VALUES(1,'Priority')")
        connection.execute("INSERT INTO project(id,name) VALUES(1,'<script>project</script>')")
    return path


def dialog(path: str, invocation: str) -> AppTest:
    """Keep the production modal open across AppTest's full-script reruns."""
    app = AppTest.from_string(
        f"""
from app.main import create_resource_pool_service, create_organization_service
from app.presentation.components import resource_pool_dialogs as dialogs
from app.presentation.components.organization_frames import teams_frame, employees_frame
from src.i18n import set_current_locale
set_current_locale('en')
service = create_resource_pool_service({path!r})
org = create_organization_service({path!r})
teams = teams_frame(org.get_all_teams())
employees = employees_frame(org.get_all_employees())
dialogs.{invocation}
""",
        default_timeout=15,
    ).run()
    assert not app.exception, [item.message for item in app.exception]
    return app


def test_pool_dialogs_create_edit_and_delete_with_tags(database: str) -> None:
    service = create_resource_pool_service(database)
    app = dialog(database, "_open_add_pool_dialog(service)")
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
    app = dialog(database, f"_open_edit_pool_dialog(service, {pool.id})")
    app.text_input[0].input("Renamed")
    app.multiselect[0].set_value([])
    app.button[0].click().run()
    assert not app.exception
    assert service.get_pool_by_id(pool.id).name == "Renamed"
    assert service.get_pool_tags(pool.id) == []
    app = dialog(database, f"_open_delete_pool_dialog(service, {pool.id}, 'Renamed')")
    app.button[0].click().run()
    assert not app.exception and service.get_all_pools() == []


def test_failed_tag_write_rolls_back_pool_and_displays_safe_error(database: str) -> None:
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "CREATE TRIGGER reject_pool_tag BEFORE INSERT ON resource_pool_tag BEGIN SELECT RAISE(ABORT, 'private database detail'); END"
        )
    app = dialog(database, "_open_add_pool_dialog(service)")
    app.text_input[0].input("Failed")
    app.multiselect[0].set_value([1])
    app.button[0].click().run()
    assert not app.exception and app.error
    assert "private database detail" not in app.error[0].value
    assert create_resource_pool_service(database).get_all_pools() == []


def test_group_dialogs_save_recursive_members_and_exclude_cycle_choices(database: str) -> None:
    service = create_resource_pool_service(database)
    pool = service.create_pool(ResourcePool("Delivery"))
    child = service.create_pool_group(ResourcePoolGroup("Child"), pool_ids=[pool])
    app = dialog(database, "_open_add_pool_group_dialog(service)")
    app.text_input[0].input("Parent")
    app.multiselect[0].set_value([pool])
    app.multiselect[1].set_value([child])
    app.button[0].click().run()
    assert not app.exception
    parent = next(group.id for group in service.get_all_pool_groups() if group.name == "Parent")
    assert service.get_group_descendant_pool_ids(parent) == [pool]
    app = dialog(database, f"_open_edit_pool_group_dialog(service, {child})")
    assert app.multiselect[1].options == []
    app.text_input[0].input("Renamed child")
    app.multiselect[0].set_value([])
    app.button[0].click().run()
    assert not app.exception and service.get_group_direct_member_ids(child) == ([], [])
    app = dialog(database, f"_open_delete_pool_group_dialog(service, {parent}, 'Parent')")
    app.button[0].click().run()
    assert not app.exception and service.get_pool_group_by_id(parent) is None
    assert service.get_pool_by_id(pool) is not None


def test_mapping_dialog_preserves_team_and_employee_choices(database: str) -> None:
    service = create_resource_pool_service(database)
    pool = service.create_pool(ResourcePool("Delivery"))
    org = create_organization_service(database)
    team = org.create_team(Team("Team"))
    employee = org.create_employee(Employee("Ada", "Lovelace", "ada@example.invalid", "ADA"))
    app = dialog(database, f"_open_add_pool_mapping_dialog(service, {pool}, teams, employees)")
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


def test_concurrent_delete_and_read_failures_do_not_report_success(database: str) -> None:
    service = create_resource_pool_service(database)
    pool = service.create_pool(ResourcePool("Delivery"))
    app = dialog(database, f"_open_delete_pool_dialog(service, {pool}, 'Delivery')")
    service.delete_pool(pool)
    app.button[0].click().run()
    assert not app.exception and app.error and not app.toast
    assert "no longer exists" in app.error[0].value
    with patch(
        "app.infrastructure.repositories.resource_pools.get_db",
        side_effect=sqlite3.OperationalError("private file path"),
    ):
        app = dialog(database, "_open_add_pool_dialog(service)")
    assert app.error and "private file path" not in app.error[0].value


def test_settings_pool_route_escapes_assignment_labels_and_retains_actions(database: str) -> None:
    service = create_resource_pool_service(database)
    pool = service.create_pool(ResourcePool("Delivery", capacity_fte=2))
    assignment = service.create_assignment(
        PoolAssignment(pool, 1, 1, notes="<img src=x onerror=alert(1)>")
    )
    app = AppTest.from_string(
        f"""
from src.repositories.organization_repo import OrganizationRepository
from src.views.settings_view import render_settings_view
render_settings_view(OrganizationRepository({database!r}))
""",
        default_timeout=15,
    )
    app.session_state["settings_active_tab"] = "resource_pools"
    with patch(
        "app.application.services.resource_pools.ResourcePoolService.get_all_pool_groups",
        side_effect=AssertionError("Closed groups loaded"),
    ):
        app.run()
    assert not app.exception and len(app.metric) == 5
    markup = "\n".join(item.value for item in app.markdown)
    assert "&lt;script&gt;project&lt;/script&gt;" in markup
    assert "&lt;img src=x onerror=alert(1)&gt;" in markup
    assert "<script>project</script>" not in markup
    assert "?nav=planning&project_id=1" in markup
    app.button(key=f"btn_unassign_{pool}").click().run()
    assert not app.exception and service.get_assignment_by_id(assignment) is None


def test_open_group_inspector_shows_deduplicated_members(database: str) -> None:
    service = create_resource_pool_service(database)
    pool = service.create_pool(ResourcePool("Delivery"))
    service.create_pool_group(ResourcePoolGroup("Group"), pool_ids=[pool])
    real_expander = st.expander

    def expanded(*args, **kwargs):
        kwargs["expanded"] = True
        return real_expander(*args, **kwargs)

    # Control only expander visibility; the widgets and application queries are real.
    with patch("streamlit.expander", side_effect=expanded):
        app = dialog(database, "_render_pool_groups_management(service)")
    assert app.dataframe[0].value.iloc[0]["recursive_pool_count"] == 1
    assert any("Pool: Delivery" in item.value for item in app.caption)
