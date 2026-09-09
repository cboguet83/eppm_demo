"""Project use-case, transaction integrity, and new UI regressions."""

from app.main import create_project_service
from app.main import create_schema_service

from app.application.exceptions import ProjectConflictError, ProjectStorageError

from app.infrastructure.repositories.projects import SqliteProjectGateway
import pandas as pd

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.application.services.projects import ProjectService
from app.domain.projects.project import normalize_project_name, prepare_project_values
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.seed_projects import create_seed_project
from app.main import create_project_type_service, create_portfolio_service
from app.infrastructure.database.schema_init import init_db


@pytest.fixture
def database(tmp_path: Path) -> str:
    """Exercise the actual SQLite migrations in an isolated database."""
    path = str(tmp_path / "projects.db")
    init_db(path)
    return path


def test_core_rejects_blank_names_without_storage_and_copies_default_lists() -> None:
    class UnavailableGateway:
        def transaction(self, *, write=False):
            raise AssertionError("No storage access for an invalid create")

    with pytest.raises(ValueError, match="name is required"):
        ProjectService(UnavailableGateway()).create_project(name="  ")
    assert normalize_project_name("  Rail  ") == "Rail"
    template = [{"param_id": "p", "param_name": "Tags", "param_type": "TAGS",
                 "mandatory": False, "has_default": True, "default_value": ["Rail"]}]
    result = prepare_project_values(template, {}, {}, creating=True)
    result["p"].append("Road")
    assert template[0]["default_value"] == ["Rail"]
    assert prepare_project_values(template, {}, {}, creating=False) == {}
    for empty in (None, "", []):
        assert prepare_project_values(template, {}, {"p": empty}, creating=True) == {"p": empty}
    with pytest.raises(ValueError, match="do not apply"):
        prepare_project_values(template, {}, {"other": "value"}, creating=True)
    template[0]["mandatory"] = True
    with pytest.raises(ValueError, match="Required property: Tags"):
        prepare_project_values(template, {}, {"p": []}, creating=True)


def test_type_switches_restore_values_without_reapplying_creation_defaults(database: str) -> None:
    schema = create_schema_service(database)
    types = create_project_type_service(database)
    special = types.create_type("Rail")
    schema.create_parameter("p", None, "Rail code", "TEXT", applies_to_all=False, project_type_ids=[special])
    types.save_rule(special, "p", True, has_default=True, default_value="Initial")
    projects = create_project_service(database)
    pid = projects.create_project(name="Line", project_type_id=special)
    assert projects.get_project_by_id(pid).dynamic_attributes == {"p": "Initial"}
    projects.update_project(pid, "Line", "Draft", 10, 2, {"p": "Edited"})
    projects.update_project(pid, "Line", "Draft", 10, 2, {}, project_type_id=1)
    assert projects.get_project_by_id(pid).dynamic_attributes == {"p": "Edited"}
    assert pd.DataFrame(create_project_service(database).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(database).get_all_parameters()))).iloc[0].dynamic_attributes == {}
    projects.update_project(pid, "Line", "Draft", 10, 2, {}, project_type_id=special)
    assert projects.get_project_by_id(pid).dynamic_attributes == {"p": "Edited"}
    fresh = projects.create_project(name="No rail history")
    with pytest.raises(ValueError, match="Required property"):
        projects.update_project(fresh, "Changed", "Draft", 0, 0, {}, project_type_id=special)
    assert projects.get_project_by_id(fresh).name == "No rail history"
    assert projects.update_project(999, "", "Draft", 0, 0, {}) is False
    assert projects.delete_project(999) is False
    assert projects.get_project_by_id(999) is None


def test_partial_property_write_rolls_back_master_and_all_prior_values(database: str) -> None:
    schema = create_schema_service(database)
    for pid in ("a", "b"):
        schema.create_parameter(pid, None, pid, "TEXT")
    service = create_project_service(database)
    pid = service.create_project(name="Original", dynamic_attributes={"a": "old", "b": "old"})
    with closing(get_db(database)) as conn, conn:
        conn.execute("""CREATE TRIGGER reject_second_value BEFORE INSERT ON project_property_value
            WHEN NEW.param_id='b' AND NEW.text_value='reject'
            BEGIN SELECT RAISE(ABORT, 'internal failure detail'); END""")
    for operation in (
        lambda: service.create_project(name="Must roll back", dynamic_attributes={"a": "new", "b": "reject"}),
        lambda: service.update_project(pid, "Must roll back", "Draft", 99, 22, {"a": "new", "b": "reject"}),
    ):
        with pytest.raises(ProjectConflictError) as error:
            operation()
        assert isinstance(error.value.__cause__, sqlite3.IntegrityError)
        assert "internal failure" not in str(error.value)
    project = service.get_project_by_id(pid)
    assert (project.name, project.planned_budget, project.dynamic_attributes) == (
        "Original", 0, {"a": "old", "b": "old"},
    )
    assert create_portfolio_service(database).get_metrics().total_projects == 1
    with pytest.raises(ProjectConflictError):
        create_project_service(database).create_project(project_id=pid, name="Duplicate")


def test_delete_rolls_back_dependencies_if_final_delete_fails(database: str) -> None:
    service = create_project_service(database)
    pid = service.create_project(name="Project with tasks")
    with closing(get_db(database)) as conn, conn:
        conn.execute("INSERT INTO project_task(project_id,task_name,start_date,end_date) VALUES (?,?,?,?)",
                     (pid, "First task", "2026-09-01", "2026-09-02"))
        conn.execute("""CREATE TRIGGER reject_project_delete BEFORE DELETE ON project
            BEGIN SELECT RAISE(ABORT, 'blocked'); END""")
    with pytest.raises(ProjectConflictError):
        service.delete_project(pid)
    with closing(get_db(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM project_task WHERE project_id=?", (pid,)).fetchone()[0] == 1
        conn.execute("DROP TRIGGER reject_project_delete")
    assert service.delete_project(pid)
    assert not service.exists(pid)


def test_bulk_seeding_uses_the_same_rules_without_committing_its_caller(database: str) -> None:
    with closing(get_db(database)) as conn:
        conn.execute("BEGIN")
        create_seed_project(conn, name="Outer transaction")
        with pytest.raises(ValueError, match="name is required"):
            create_seed_project(conn, name=" ")
        assert conn.in_transaction
        conn.rollback()
    assert create_portfolio_service(database).get_metrics().total_projects == 0


def test_gateway_closes_connections_and_reserves_the_writer_before_reads(
    database: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections = []

    def tracked(path):
        conn = get_db(path)
        connections.append(conn)
        return conn

    monkeypatch.setattr("app.infrastructure.database.project_transactions.get_db", tracked)
    service = create_project_service(database)
    service.create_project(name="Valid")
    with pytest.raises(ValueError, match="Unknown project type"):
        service.create_project(name="Invalid", project_type_id=999)
    with SqliteProjectGateway(database).transaction(write=True) as store:
        assert store.exists(1)
        with closing(sqlite3.connect(database, timeout=0)) as other:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("UPDATE project SET name='Racing' WHERE id=1")
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_project_storage_errors_are_safe_across_services_and_readers(tmp_path: Path) -> None:
    path = str(tmp_path / "missing" / "private.db")
    with pytest.raises(ProjectStorageError) as error:
        create_project_service(path).exists(1)
    assert path not in str(error.value)
    assert isinstance(error.value.__cause__, sqlite3.OperationalError)
    with pytest.raises(ProjectStorageError):
        create_portfolio_service(path, include_allocations=False).get_page([], {})
    with pytest.raises(ProjectStorageError):
        create_project_service(path).get_planning_catalog(())


def test_create_dialog_retains_draft_when_another_user_takes_the_preview_id(database: str) -> None:
    create_schema_service(database).create_parameter("p", None, "Notes", "TEXT")
    app = AppTest.from_string(f'''
from app.main import create_project_workspace
from app.presentation.components.project_dialogs import open_create_project_dialog
from app.presentation.i18n import set_current_locale
set_current_locale("en")
open_create_project_dialog(create_project_workspace({database!r}))
''', default_timeout=15).run()
    assert not app.exception
    app.text_input(key="portfolio_create_1_p").input("Draft notes").run()
    next(w for w in app.text_input if w.label == "Project Title *").input("My project").run()
    create_project_service(database).create_project(name="Another user's project")
    next(b for b in app.button if b.label == "Create project").click().run()
    assert not app.exception
    project = create_project_service(database).get_project_by_id(2)
    assert (project.name, project.dynamic_attributes) == ("My project", {"p": "Draft notes"})
    assert app.session_state["selected_portfolio_project_id"] == 2
