"""Application and real SQLite regressions for the first migrated feature."""

from app.application.exceptions import ProjectTypeConflictError, ProjectTypeStorageError, SchemaConflictError

from app.presentation.components import project_type_frames
from app.presentation.components import schema_frames

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.application.services.project_types import ProjectTypeService
from app.infrastructure.repositories.project_types import SqliteProjectTypeGateway
from app.infrastructure.repositories.project_types import SqliteProjectTypeStore
from app.domain.projects.project_types import make_applicability
from app.main import create_project_type_service
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from app.main import create_project_service
from app.main import create_schema_service


@pytest.fixture
def database(tmp_path: Path) -> str:
    """Provide a real, isolated database using the existing schema migrations."""
    path = str(tmp_path / "project-types.db")
    init_db(path)
    return path


def test_application_validates_inputs_before_opening_storage() -> None:
    """Invalid user input needs no infrastructure and cannot start a write."""
    class UnavailableGateway:
        def transaction(self, *, write: bool = False):
            raise AssertionError("Storage must not be opened for invalid input")

    service = ProjectTypeService(UnavailableGateway())
    with pytest.raises(ValueError, match="name is required"):
        service.create_type("  ")
    with pytest.raises(ValueError, match="Select at least one"):
        service.set_applicability("p", False, [])


def test_independent_services_share_persisted_state_and_error_contracts(database: str) -> None:
    """New use cases coexist with the old dataframe and SQLite-exception API."""
    service = create_project_type_service(database)
    other_service = create_project_type_service(database)
    type_id = service.create_type("  Rail  ", "  Initial  ")
    row = project_type_frames.types_frame(other_service.get_all_types()).set_index("id").loc[type_id]
    assert (row["name"], row["description"]) == ("Rail", "Initial")
    other_service.update_type(type_id, "Road", "Updated")
    assert service.get_all_types()[1].name == "Road"
    with pytest.raises(ProjectTypeConflictError, match="already exists"):
        service.create_type("road")
    with pytest.raises(ProjectTypeConflictError):
        other_service.create_type("ROAD")
    service.delete_type(type_id)
    service.delete_type(type_id)  # Missing-ID deletion remains idempotent.
    assert project_type_frames.types_frame(other_service.get_all_types()).name.tolist() == ["General"]
    with pytest.raises(ValueError, match="Unknown project type"):
        service.update_type(type_id, "Deleted")
    with pytest.raises(ValueError, match="Unknown project type"):
        service.get_template(type_id)


def test_invalid_default_rolls_back_the_required_override_and_previous_default(database: str) -> None:
    """A failure after the rule write must not leave a partially updated template."""
    schema = create_schema_service(database)
    schema.create_parameter("p", None, "Choice", "ENUM")
    schema.add_option("p", "A", 1)
    service = create_project_type_service(database)
    service.save_rule(1, "p", False, has_default=True, default_value="A")

    with pytest.raises(ValueError, match="invalid selection"):
        service.save_rule(1, "p", True, has_default=True, default_value="Missing")

    template = service.get_template(1)[0]
    assert template["mandatory"] is False
    assert template["default_value"] == "A"
    service.save_rule(1, "p", None, has_default=False)
    assert service.get_template(1)[0]["has_default"] is False


def test_failed_membership_change_restores_the_original_scope(database: str) -> None:
    """A foreign-key failure rolls back both the flag and membership deletion."""
    schema = create_schema_service(database)
    schema.create_parameter("p", None, "Scope", "TEXT")
    service = create_project_type_service(database)
    with pytest.raises(ProjectTypeConflictError):
        service.set_applicability("p", False, [999])
    assert service.get_applicability("p").applies_to_all is True
    service.set_applicability("p", False, [1])
    with pytest.raises(ProjectTypeConflictError):
        service.set_applicability("p", False, [1, 999])
    assert service.get_applicability("p").type_ids == (1,)
    with pytest.raises(ValueError, match="Unknown property"):
        service.get_applicability("missing")
    with pytest.raises(ValueError, match="Unknown property"):
        service.set_applicability("missing", True)
    with pytest.raises(ValueError, match="does not apply"):
        service.save_rule(1, "missing")


def test_schema_and_type_store_share_the_outer_transaction(database: str) -> None:
    """Schema edits must not commit before their applicability update succeeds."""
    schema = create_schema_service(database)
    schema.create_parameter("p", None, "Original", "TEXT")
    with pytest.raises(SchemaConflictError):
        schema.update_parameter(
            "p", None, "Must roll back", "TEXT",
            applies_to_all=False, project_type_ids=[999],
        )
    row = schema_frames.parameters_frame(schema.get_all_parameters()).set_index("param_id").loc["p"]
    assert row["param_name"] == "Original"
    assert row["applies_to_all"] == 1
    with closing(get_db(database)) as connection:
        with connection:
            SqliteProjectTypeStore(connection).set_applicability("p", make_applicability(False, [1]))
            assert connection.in_transaction
            connection.rollback()
    assert create_project_type_service(database).get_applicability("p").applies_to_all


def test_deletion_guards_preserve_types_and_their_project_data(database: str) -> None:
    """General, exclusive properties, and project assignments survive failed deletes."""
    service = create_project_type_service(database)
    with pytest.raises(ValueError, match="cannot be deleted"):
        service.delete_type(1)
    with pytest.raises(ValueError, match="cannot be renamed"):
        service.update_type(1, "Other")
    service.update_type(1, "General", "Updated description")
    type_id = service.create_type("Rail")
    schema = create_schema_service(database)
    schema.create_parameter("p", None, "Rail detail", "TEXT", applies_to_all=False,
                            project_type_ids=[type_id])
    with pytest.raises(ValueError, match="exclusive properties"):
        service.delete_type(type_id)
    service.set_applicability("p", True)
    project_id = create_project_service(database).create_project(name="Line", project_type_id=type_id)
    with pytest.raises(ValueError, match="Reassign"):
        service.delete_type(type_id)
    assert create_project_service(database).get_project_by_id(project_id).project_type_id == type_id


def test_gateway_closes_connections_on_success_and_validation_failure(
    database: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new transaction boundary releases real SQLite connections promptly."""
    connections: list[sqlite3.Connection] = []

    def tracked_connection(path: str | None = None) -> sqlite3.Connection:
        connection = get_db(path)
        connections.append(connection)
        return connection

    monkeypatch.setattr("app.infrastructure.repositories.project_types.get_db", tracked_connection)
    service = create_project_type_service(database)
    service.get_all_types()
    with pytest.raises(ValueError):
        service.delete_type(1)
    assert len(connections) == 2
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_guarded_write_holds_the_sqlite_writer_reservation(database: str) -> None:
    """Another writer cannot invalidate guards between their read and the save."""
    gateway = SqliteProjectTypeGateway(database)
    with closing(sqlite3.connect(database, timeout=0)) as other:
        with gateway.transaction(write=True) as store:
            assert store.find_type(1).is_general
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("UPDATE project_type SET description='racing' WHERE id=1")
        with other:
            other.execute("UPDATE project_type SET description='after commit' WHERE id=1")
    assert create_project_type_service(database).get_all_types()[0].description == "after commit"


def test_storage_failures_are_safe_across_service_and_display_reads(tmp_path: Path) -> None:
    """Services and display reads expose safe errors and preserve their storage cause."""
    missing = str(tmp_path / "missing-directory" / "private.db")
    with pytest.raises(ProjectTypeStorageError) as error:
        create_project_type_service(missing).get_all_types()
    assert missing not in str(error.value)
    assert isinstance(error.value.__cause__, sqlite3.OperationalError)
    with pytest.raises(ProjectTypeStorageError):
        project_type_frames.types_frame(create_project_type_service(missing).get_all_types())
