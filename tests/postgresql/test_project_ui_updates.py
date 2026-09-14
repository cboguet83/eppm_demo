"""Persistence, dialog, and menu regressions for project usability changes."""

from pathlib import Path
import psycopg
from unittest.mock import patch

import pytest

from app.domain.access.models import AccessDenied
from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.migration import migrate
from app.operator_services import create_maintenance_service
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import native_screen, runtime as runtime, access as access
from app.domain.projects.links import normalize_link
from app.domain.resources.models import PoolAssignment, ResourcePool
from app.main import create_collaboration_service, create_project_service, create_resource_pool_service
from app.presentation.components.context_menu import CONTEXT_MENU_CSS


@pytest.fixture
def database(runtime: RuntimeResources, access: BusinessAccess) -> RuntimeResources:
    """Name fixture projects through the native project service."""
    projects = create_project_service(runtime, access=access)
    projects.update_project(1, "First", "Draft", 0, 0, {})
    projects.update_project(2, "Second", "Draft", 0, 0, {})
    return runtime


def test_links_have_no_fixed_slot_limit_and_updates_are_project_scoped(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_collaboration_service(database, access=access)
    ids = [service.save_link(1, f"https://example.test/{i}", f"Link {i}") for i in range(120)]
    assert len(service.list_links(1)) == 120
    assert service.list_links(2) == []
    service.save_link(1, " https://example.test/new ", " New alias ", ids[0])
    assert service.list_links(1)[0] == {"id": ids[0], "url": "https://example.test/new", "alias": "New alias"}
    with pytest.raises(ValueError, match="this project"):
        service.save_link(2, "https://example.test", "Wrong project", ids[0])
    service.delete_link(2, ids[0])
    assert len(service.list_links(1)) == 120
    service.delete_link(1, ids[0])
    assert len(service.list_links(1)) == 119
    with pytest.raises(AccessDenied):
        service.save_link(999, "https://example.test", "Missing project")
    create_project_service(database, access=access).delete_project(1)
    assert service.list_links(1) == []


@pytest.mark.parametrize("url,alias", [
    ("javascript:alert(1)", "Unsafe"), ("//example.test", "Relative"),
    ("https://user:password@example.test", "Credentials"), ("https://", "Empty host"),
    ("https://example.test/a b", "Whitespace"), ("https://example.test:bad", "Port"),
    ("https://[", "Host"), ("https://example.test", "  "), (None, "Missing"),
])
def test_link_validation_rejects_non_navigable_values(url: str, alias: str) -> None:
    with pytest.raises(ValueError):
        normalize_link(url, alias)


def test_link_migration_reentry_preserves_data_and_backed_up_flush_removes_links(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture, clients, tmp_path: Path,
) -> None:
    service = create_collaboration_service(database, access=access)
    link_id = service.save_link(1, "https://example.test", "Kept")
    assert migrate(authorized.setup.operator_url) == ()
    assert migrate(authorized.setup.operator_url) == ()
    assert service.list_links(1) == [{"id": link_id, "url": "https://example.test", "alias": "Kept"}]
    with psycopg.connect(authorized.setup.operator_url) as connection:
        with pytest.raises(psycopg.IntegrityError), connection.transaction():
            connection.execute("INSERT INTO eppm.project_link(project_id,url,alias) VALUES(1,'https://example.test',' ')")
    maintenance = create_maintenance_service(
        authorized.setup.operator_url, backup_directory=tmp_path, archive_tools=clients,
    )
    maintenance.flush()
    assert service.list_links(1) == []
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.project_link").fetchone()[0] == 0
    assert len(list(tmp_path.glob("*.dump"))) == 1


def test_links_inspection_has_no_management_widgets(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_collaboration_service(database, access=access)
    service.save_link(1, "https://example.test", "Custom reference")
    app = native_screen(f'''
from app.main import create_collaboration_service
from app.presentation.pages.collaboration import render_project_links
render_project_links(1, create_collaboration_service(runtime, access=access))
''', database, access).run()
    assert not app.exception
    assert not app.text_input and not app.selectbox and not app.button
    assert "Custom reference" in app.get("html")[0].proto.body
    assert len(app.get("divider")) == 1


def test_pool_popup_reuses_settings_fields_and_go_to_action(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool("Selected pool", capacity_fte=2))
    identity = service.create_assignment(PoolAssignment(pool, 1, .5, notes="Pool note"))
    other = service.create_pool(ResourcePool("Other pool", capacity_fte=1))
    service.create_assignment(PoolAssignment(other, 2, 1))
    with patch("app.presentation.components.action_table.action_table", return_value=None) as table:
        app = native_screen(f'''
from app.main import create_planning_workspace
from app.presentation.pages.planning import _pool_allocations_dialog
_pool_allocations_dialog({pool}, create_planning_workspace(runtime, access=access))
''', database, access).run()
    assert not app.exception and not app.error
    rows, columns, actions = table.call_args.args
    assert [row["id"] for row in rows] == [identity]
    assert rows[0]["notes"] == "Pool note"
    assert {key for key, _ in columns} == {"id", "project", "task", "fte", "period", "notes"}
    assert actions == {"open": "Go to"}


@pytest.mark.parametrize("action", ["import_csv_template", "export_csv_template"])
def test_csv_menu_opens_only_the_requested_project_dialog(database: RuntimeResources, access: BusinessAccess, action: str) -> None:
    from app.presentation.pages.planning import _schedule_csv_dialog

    with patch("app.presentation.pages.planning._interactive_gantt", return_value={
        "action": action, "project_id": 2, "nonce": action,
    }), patch("app.presentation.pages.planning._schedule_csv_dialog", wraps=_schedule_csv_dialog) as dialog:
        app = native_screen(f'''
from app.main import create_planning_workspace
from app.presentation.pages.planning import render_planning_milestones
import streamlit as st
st.session_state['planning_statuses'] = ['Draft']
render_planning_milestones(create_planning_workspace(runtime, access=access))
''', database, access).run()
    assert not app.exception and not app.error
    if action == "import_csv_template":
        assert dialog.call_args.args[1:] == (2, action)
        assert "Nothing is deleted" in app.warning[0].value
        assert any("eppm_csv_upload" in str(widget.proto) for widget in app.get("bidi_component"))
    else:
        dialog.assert_not_called()
        assert len(app.get("bidi_component")) > 0
    assert not any(widget.key == "sb_manage_target_project" for widget in app.selectbox)
    assert len(app.get("download_button")) == 0
    assert not app.get("file_uploader")


def test_every_existing_context_menu_uses_the_shared_visual_standard() -> None:
    for path in Path("app/presentation/assets/components").glob("*/index.html"):
        assert CONTEXT_MENU_CSS in path.read_text(encoding="utf-8"), path
