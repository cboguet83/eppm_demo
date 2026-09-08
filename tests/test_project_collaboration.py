"""Real database and Streamlit regression tests for project contacts and logs."""

from contextlib import closing
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from src.database.connection import get_db
from src.database.schema_init import init_db
from src.repositories.project_collaboration_repo import EVENT_STATUSES, ProjectCollaborationRepository
from src.repositories.project_repo import ProjectRepository


@pytest.fixture
def collaboration(tmp_path):
    path = str(tmp_path / "project.db")
    init_db(path)
    ProjectRepository(path).create_project(name="Alpha")
    ProjectRepository(path).create_project(name="Beta")
    with closing(get_db(path)) as conn, conn:
        conn.executemany("INSERT INTO function(function_id,name,hierarchy_level) VALUES (?,?,1)",
                         [(1, "Manager"), (2, "Architect"), (3, "Vacant function")])
        conn.executemany("""INSERT INTO employee(firstname,lastname,email,employee_code,function_id)
            VALUES (?,?,?,?,?)""", [("Alice", "Smith", "alice@example.test", "A", 1),
                                    ("Bob", "Jones", "bob@example.test", "B", 2)])
    return ProjectCollaborationRepository(path)


def event_values(repo):
    return dict(title="Review", description="Review scope", deadline="2027-02-28",
                scope="internal", comment="Initial comment", event_type_id=repo.list_catalog("event_type")[0]["id"])


def test_app_bootstrap_passes_schema_version_as_an_explicit_cache_key():
    """A changed default alone must not leave a hot-reloaded app on old tables."""
    import ast
    from pathlib import Path

    module = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
    bootstrap = next(node for node in module.body if isinstance(node, ast.FunctionDef)
                     and node.name == "bootstrap_database")
    version = ast.literal_eval(bootstrap.args.defaults[0])
    run_app = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "run_app")
    call = next(node for node in ast.walk(run_app) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "bootstrap_database")
    assert {item.arg: ast.literal_eval(item.value) for item in call.keywords}["schema_version"] == version


def test_roles_can_repeat_and_occupants_follow_the_function(collaboration):
    repo = collaboration
    role = repo.save_catalog("role", "Sponsor")
    first = repo.save_contact(1, role, 1)
    repo.save_contact(1, role, 2)
    repo.save_contact(2, role, 1)
    assert [row["person"] for row in repo.list_contacts(1)] == ["Alice Smith", "Bob Jones"]
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_contact(1, role, 1)
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_contact(1, role, 999)
    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_catalog("role", role)
    with pytest.raises(ValueError):
        repo.save_contact(2, role, 3, first)
    repo.save_contact(1, role, 3, first)
    assert repo.list_contacts(1)[0]["person"] == "Vacant function"
    with closing(get_db(repo.db_path)) as conn, conn:
        conn.execute("UPDATE employee SET function_id=3 WHERE employee_code='A'")
    assert repo.list_contacts(1)[0]["person"] == "Alice Smith"
    repo.save_catalog("role", "Executive sponsor", role)
    assert repo.list_contacts(1)[0]["role"] == "Executive sponsor"
    repo.delete_contact(2, first)
    assert len(repo.list_contacts(1)) == 2


def test_migration_is_additive_idempotent_and_catalog_deletions_stick(collaboration):
    repo = collaboration
    assert {r["name"] for r in repo.list_catalog("event_type")} == {
        "General information", "Blocking Point", "Project update"}
    role = repo.save_catalog("role", "Sponsor")
    repo.save_contact(1, role, 1)
    event = repo.save_event(1, **event_values(repo))
    unused = repo.save_catalog("event_type", "Temporary")
    repo.delete_catalog("event_type", unused)
    default_unused = repo.list_catalog("event_type")[-1]["id"]
    repo.delete_catalog("event_type", default_unused)
    init_db(repo.db_path)
    assert len(repo.list_catalog("event_type")) == 2
    assert repo.list_events(1)[0]["id"] == event
    assert repo.list_contacts(1)[0]["role_id"] == role
    assert len(ProjectRepository(repo.db_path).get_all_projects()) == 2
    with closing(get_db(repo.db_path)) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("status", EVENT_STATUSES)
def test_events_support_every_state_and_project_scoped_updates(collaboration, status):
    repo = collaboration
    values = event_values(repo)
    event = repo.save_event(1, **values, status=status)
    assert repo.list_events(1)[0]["status"] == status
    assert repo.list_events(2) == []
    values.update(scope="global", deadline=None, comment="Updated")
    repo.save_event(1, **values, status="closed", event_id=event)
    assert repo.list_events(1)[0]["comment"] == "Updated"
    assert repo.list_events(1)[0]["scope"] == "global"
    with pytest.raises(ValueError):
        repo.save_event(2, **values, event_id=event)
    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_catalog("event_type", values["event_type_id"])


@pytest.mark.parametrize("field,value", [("title", "  "), ("deadline", "2027-02-30"),
                                        ("scope", "private"), ("status", "unknown")])
def test_event_validation_rolls_back_invalid_updates(collaboration, field, value):
    repo = collaboration
    values = event_values(repo)
    event = repo.save_event(1, **values)
    with pytest.raises(ValueError):
        repo.save_event(1, **{**values, field: value}, event_id=event)
    assert repo.list_events(1)[0]["title"] == "Review"
    assert repo.list_events(1)[0]["scope"] == "internal"


def test_catalog_validation_translations_and_project_deletion_cascade(collaboration):
    repo = collaboration
    role = repo.save_catalog("role", "Sponsor")
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_catalog("role", "sponsor")
    with pytest.raises(ValueError):
        repo.save_catalog("role", " ")
    with pytest.raises(ValueError):
        repo.list_catalog("untrusted_table")
    with closing(get_db(repo.db_path)) as conn, conn:
        conn.execute("INSERT INTO project_role_translation VALUES (?, 'fr', 'Parrain')", (role,))
    repo.save_contact(1, role, 1)
    assert repo.list_contacts(1, "fr")[0]["role"] == "Parrain"
    assert repo.list_contacts(1, "de")[0]["role"] == "Sponsor"
    repo.save_event(1, **event_values(repo))
    with closing(get_db(repo.db_path)) as conn, conn:
        conn.execute("DELETE FROM project WHERE id=1")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert repo.list_contacts(1) == repo.list_events(1) == []
    repo.delete_catalog("role", role)


def test_log_paging_and_seed_flush_leave_no_orphans(collaboration):
    from scripts.flush_database import flush_database
    repo = collaboration
    for index in range(55):
        repo.save_event(1, **{**event_values(repo), "title": str(index)})
    assert len(repo.list_events(1)) == 50
    assert [r["title"] for r in repo.list_events(1, offset=50)] == ["4", "3", "2", "1", "0"]
    role = repo.save_catalog("role", "Sponsor")
    repo.save_contact(1, role, 1)
    flush_database(repo.db_path)
    assert repo.list_contacts(1) == repo.list_events(1) == []
    assert len(repo.list_catalog("role")) == 1
    flush_database(repo.db_path, flush_all=True)
    assert repo.list_catalog("role") == []
    assert len(repo.list_catalog("event_type")) == 3
    with closing(get_db(repo.db_path)) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def ui_app(repo, body):
    return AppTest.from_string(f'''
from src.i18n import set_current_locale
from src.views.project_collaboration_view import render_project_contacts, render_project_log, render_project_catalog
set_current_locale('en')
db_path = {repo.db_path!r}
{body}
''', default_timeout=15).run()


def test_contact_ui_adds_edits_and_removes_function_assignments(collaboration):
    repo = collaboration
    role = repo.save_catalog("role", "Sponsor")
    app = ui_app(repo, "render_project_contacts(1, db_path)")
    assert not app.exception
    next(b for b in app.button if b.label == "Save contact").click().run()
    assert not app.exception
    contact = repo.list_contacts(1)[0]
    assert contact["role_id"] == role and contact["person"] == "Alice Smith"
    app.selectbox(key="project_contacts_1_selection").select(contact["id"]).run()
    next(w for w in app.selectbox if w.label == "Function").select(2)
    next(b for b in app.button if b.label == "Save contact").click().run()
    assert not app.exception
    assert repo.list_contacts(1)[0]["person"] == "Bob Jones"
    next(b for b in app.button if b.label == "Remove contact").click().run()
    assert not app.exception
    assert repo.list_contacts(1) == []


def test_log_ui_creates_and_edits_all_fields(collaboration):
    repo = collaboration
    app = ui_app(repo, "render_project_log(1, db_path)")
    assert not app.exception
    app.text_input[0].set_value("Approval")
    app.text_area[0].set_value("Needs approval")
    app.text_area[1].set_value("Review tomorrow")
    next(w for w in app.selectbox if w.label == "Scope").select("global")
    next(b for b in app.button if b.label == "Save event").click().run()
    assert not app.exception
    event = repo.list_events(1)[0]
    assert event["title"] == "Approval" and event["scope"] == "global"
    app.selectbox(key="project_log_1_selection").select(event["id"]).run()
    next(w for w in app.selectbox if w.label == "State").select("completed")
    next(b for b in app.button if b.label == "Save event").click().run()
    assert not app.exception
    assert repo.list_events(1)[0]["status"] == "completed"


def test_settings_catalog_ui_protects_used_entries_and_deletes_unused(collaboration):
    repo = collaboration
    app = ui_app(repo, "render_project_catalog(db_path, 'role')")
    app.text_input[0].set_value("Sponsor")
    next(b for b in app.button if b.label == "Save").click().run()
    assert not app.exception
    role = repo.list_catalog("role")[0]["id"]
    repo.save_contact(1, role, 1)
    app.selectbox[0].select(role).run()
    app.checkbox[0].check().run()
    next(b for b in app.button if b.label == "Delete").click().run()
    assert not app.exception and app.error
    repo.delete_contact(1, repo.list_contacts(1)[0]["id"])
    next(b for b in app.button if b.label == "Delete").click().run()
    assert not app.exception
    assert repo.list_catalog("role") == []
