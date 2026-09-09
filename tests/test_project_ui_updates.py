"""Persistence, dialog, and menu regressions for project usability changes."""

from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.application.exceptions import CollaborationConflictError
from app.domain.projects.links import normalize_link
from app.domain.resources.models import PoolAssignment, ResourcePool
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.flush import flush_database
from app.infrastructure.database.project_links_migration import migrate_project_links
from app.infrastructure.database.schema_init import init_db
from app.main import create_collaboration_service, create_project_service, create_resource_pool_service
from app.presentation.components.context_menu import CONTEXT_MENU_CSS


@pytest.fixture
def database(tmp_path: Path) -> str:
    path = str(tmp_path / "ui.db")
    init_db(path)
    create_project_service(path).create_project(name="First")
    create_project_service(path).create_project(name="Second")
    return path


def test_links_have_no_fixed_slot_limit_and_updates_are_project_scoped(database: str) -> None:
    service = create_collaboration_service(database)
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
    with pytest.raises(CollaborationConflictError):
        service.save_link(999, "https://example.test", "Missing project")
    create_project_service(database).delete_project(1)
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


def test_link_migration_is_repeatable_preserves_data_and_flush_removes_links(database: str) -> None:
    service = create_collaboration_service(database)
    service.save_link(1, "https://example.test", "Kept")
    init_db(database)
    assert service.list_links(1)[0]["alias"] == "Kept"
    with closing(get_db(database)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT count(*) FROM schema_migration WHERE version='project-links-v1'").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError), connection:
            connection.execute("INSERT INTO project_link(project_id,url,alias) VALUES(1,'https://example.test',' ')")
    flush_database(database)
    assert service.list_links(1) == []


def test_link_migration_failure_rolls_back_table_and_version(database: str) -> None:
    with closing(get_db(database)) as connection:
        with connection:
            connection.execute("DROP TABLE project_link")
            connection.execute("DELETE FROM schema_migration WHERE version='project-links-v1'")
            connection.execute("CREATE INDEX idx_project_link_project ON project(id)")
        with pytest.raises(sqlite3.OperationalError), connection:
            connection.execute("BEGIN")
            migrate_project_links(connection)
        assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='project_link'").fetchone()
        assert not connection.execute("SELECT 1 FROM schema_migration WHERE version='project-links-v1'").fetchone()


def test_links_inspection_has_no_management_widgets(database: str) -> None:
    service = create_collaboration_service(database)
    service.save_link(1, "https://example.test", "Custom reference")
    app = AppTest.from_string(f'''
from app.main import create_collaboration_service
from app.presentation.pages.collaboration import render_project_links
render_project_links(1, create_collaboration_service({database!r}))
''').run()
    assert not app.exception
    assert not app.text_input and not app.selectbox and not app.button
    assert "Custom reference" in app.get("html")[0].proto.body
    assert len(app.get("divider")) == 1


def test_pool_popup_reuses_settings_fields_and_go_to_action(database: str) -> None:
    service = create_resource_pool_service(database)
    pool = service.create_pool(ResourcePool("Selected pool", capacity_fte=2))
    identity = service.create_assignment(PoolAssignment(pool, 1, .5, notes="Pool note"))
    other = service.create_pool(ResourcePool("Other pool", capacity_fte=1))
    service.create_assignment(PoolAssignment(other, 2, 1))
    with patch("app.presentation.components.action_table.action_table", return_value=None) as table:
        app = AppTest.from_string(f'''
from app.main import create_planning_workspace
from app.presentation.pages.planning import _pool_allocations_dialog
_pool_allocations_dialog({pool}, create_planning_workspace({database!r}))
''').run()
    assert not app.exception and not app.error
    rows, columns, actions = table.call_args.args
    assert [row["id"] for row in rows] == [identity]
    assert rows[0]["notes"] == "Pool note"
    assert {key for key, _ in columns} == {"id", "project", "task", "fte", "period", "notes"}
    assert actions == {"open": "Go to"}


@pytest.mark.parametrize("action", ["import_csv_template", "export_csv_template"])
def test_csv_menu_opens_only_the_requested_project_dialog(database: str, action: str) -> None:
    from app.presentation.pages.planning import _schedule_csv_dialog

    with patch("app.presentation.pages.planning._interactive_gantt", return_value={
        "action": action, "project_id": 2, "nonce": action,
    }), patch("app.presentation.pages.planning._schedule_csv_dialog", wraps=_schedule_csv_dialog) as dialog:
        app = AppTest.from_string(f'''
from app.main import create_planning_workspace
from app.presentation.pages.planning import render_planning_milestones
render_planning_milestones(create_planning_workspace({database!r}))
''', default_timeout=20).run()
    assert not app.exception and not app.error
    if action == "import_csv_template":
        assert dialog.call_args.args[1:] == (2, action)
        assert "Nothing is deleted" in app.warning[0].value
    else:
        dialog.assert_not_called()
        assert len(app.get("bidi_component")) > 0
    assert not any(widget.key == "sb_manage_target_project" for widget in app.selectbox)
    assert len(app.get("download_button")) == 0
    assert len(app.get("file_uploader")) == (1 if action == "import_csv_template" else 0)


def test_every_existing_context_menu_uses_the_shared_visual_standard() -> None:
    for path in Path("app/presentation/assets/components").glob("*/index.html"):
        assert CONTEXT_MENU_CSS in path.read_text(encoding="utf-8"), path
