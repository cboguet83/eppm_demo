"""Application and native PostgreSQL project-template contracts."""

from app.application.exceptions import ProjectTypeConflictError, ProjectTypeStorageError, SchemaConflictError

from app.presentation.components import project_type_frames
from app.presentation.components import schema_frames

import psycopg

import pytest

from app.application.services.business_access import BusinessAccess
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access

from app.application.services.project_types import ProjectTypeService
from app.infrastructure.postgresql.project_types import PostgresProjectTypeGateway
from app.infrastructure.postgresql.project_types import PostgresProjectTypeStore
from app.domain.projects.project_types import make_applicability
from app.main import create_project_type_service
from app.main import create_project_service
from app.main import create_schema_service


@pytest.fixture
def database(runtime: RuntimeResources) -> RuntimeResources:
    """Use native resources over a separately migrated test database."""
    return runtime


def test_application_validates_inputs_before_opening_storage() -> None:
    """Invalid user input needs no infrastructure and cannot start a write."""
    class UnavailableGateway:
        def run(self, operation, **options):
            raise AssertionError("Storage must not be opened for invalid input")

    service = ProjectTypeService(UnavailableGateway())
    with pytest.raises(ValueError, match="name is required"):
        service.create_type("  ")
    with pytest.raises(ValueError, match="Select at least one"):
        service.set_applicability("p", False, [])


def test_independent_services_share_persisted_state_and_error_contracts(database: RuntimeResources, access: BusinessAccess) -> None:
    """Independent native services preserve frames and safe application errors."""
    service = create_project_type_service(database, access=access)
    other_service = create_project_type_service(database, access=access)
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


def test_invalid_default_rolls_back_the_required_override_and_previous_default(database: RuntimeResources, access: BusinessAccess) -> None:
    """A failure after the rule write must not leave a partially updated template."""
    schema = create_schema_service(database, access=access)
    schema.create_parameter("p", None, "Choice", "ENUM")
    schema.add_option("p", "A", 1)
    service = create_project_type_service(database, access=access)
    service.save_rule(1, "p", False, has_default=True, default_value="A")

    with pytest.raises(ValueError, match="invalid selection"):
        service.save_rule(1, "p", True, has_default=True, default_value="Missing")

    template = service.get_template(1)[0]
    assert template["mandatory"] is False
    assert template["default_value"] == "A"
    service.save_rule(1, "p", None, has_default=False)
    assert service.get_template(1)[0]["has_default"] is False


def test_failed_membership_change_restores_the_original_scope(database: RuntimeResources, access: BusinessAccess) -> None:
    """A foreign-key failure rolls back both the flag and membership deletion."""
    schema = create_schema_service(database, access=access)
    schema.create_parameter("p", None, "Scope", "TEXT")
    service = create_project_type_service(database, access=access)
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


def test_schema_and_type_store_share_the_outer_transaction(database: RuntimeResources, access: BusinessAccess) -> None:
    """Schema edits must not commit before their applicability update succeeds."""
    schema = create_schema_service(database, access=access)
    schema.create_parameter("p", None, "Original", "TEXT")
    with pytest.raises(SchemaConflictError):
        schema.update_parameter(
            "p", None, "Must roll back", "TEXT",
            applies_to_all=False, project_type_ids=[999],
        )
    row = schema_frames.parameters_frame(schema.get_all_parameters()).set_index("param_id").loc["p"]
    assert row["param_name"] == "Original"
    assert row["applies_to_all"] == 1
    gateway = PostgresProjectTypeGateway(database.database, database.key, access=access)

    def abort_outer_transaction(store: PostgresProjectTypeStore) -> None:
        store.set_applicability("p", make_applicability(False, [1]))
        assert store.connection.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
        assert not store.get_applicability("p").applies_to_all
        raise ValueError("cancel outer transaction")

    with pytest.raises(ValueError, match="cancel outer"):
        gateway.run(abort_outer_transaction, write=True)
    assert create_project_type_service(database, access=access).get_applicability("p").applies_to_all


def test_deletion_guards_preserve_types_and_their_project_data(database: RuntimeResources, access: BusinessAccess) -> None:
    """General, exclusive properties, and project assignments survive failed deletes."""
    service = create_project_type_service(database, access=access)
    with pytest.raises(ValueError, match="cannot be deleted"):
        service.delete_type(1)
    with pytest.raises(ValueError, match="cannot be renamed"):
        service.update_type(1, "Other")
    service.update_type(1, "General", "Updated description")
    type_id = service.create_type("Rail")
    schema = create_schema_service(database, access=access)
    schema.create_parameter("p", None, "Rail detail", "TEXT", applies_to_all=False,
                            project_type_ids=[type_id])
    with pytest.raises(ValueError, match="exclusive properties"):
        service.delete_type(type_id)
    service.set_applicability("p", True)
    project_id = create_project_service(database, access=access).create_project(name="Line", project_type_id=type_id)
    with pytest.raises(ValueError, match="Reassign"):
        service.delete_type(type_id)
    assert create_project_service(database, access=access).get_project_by_id(project_id).project_type_id == type_id


def test_gateway_reuses_leases_after_success_and_validation_failure(
    database: RuntimeResources, access: BusinessAccess,
) -> None:
    """A failed guard returns its lease without losing the persistent template."""
    service = create_project_type_service(database, access=access)
    before = service.get_all_types()
    with pytest.raises(ValueError):
        service.delete_type(1)
    assert service.get_all_types() == before
    service.update_type(1, "General", "After failed guard")
    assert service.get_all_types()[0].description == "After failed guard"


def test_guarded_write_replays_after_a_concurrent_template_edit(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    """A serialization conflict reruns the whole guard and update against fresh data."""
    service = create_project_type_service(database, access=access)
    service.update_type(1, "General", "initial")
    gateway = PostgresProjectTypeGateway(database.database, database.key, access=access)
    seen = []

    def guarded_edit(store: PostgresProjectTypeStore) -> None:
        current = store.find_type(1)
        assert current.is_general
        seen.append(current.description)
        if len(seen) == 1:
            with psycopg.connect(authorized.setup.operator_url) as other:
                other.execute("SET LOCAL statement_timeout='1s'")
                other.execute("UPDATE eppm.project_type SET description='racing' WHERE id=1")
        store.update_type(1, current.name, current.description + " committed")

    gateway.run(guarded_edit, write=True)
    assert seen == ["initial", "racing"]
    assert service.get_all_types()[0].description == "racing committed"


def test_storage_failures_are_safe_across_service_and_display_reads(
    database: RuntimeResources, access: BusinessAccess, caplog: pytest.LogCaptureFixture,
) -> None:
    """A real storage outage cannot expose connection details through display errors."""
    service = create_project_type_service(database, access=access)
    database.database.close()
    with pytest.raises(ProjectTypeStorageError) as error:
        service.get_all_types()
    assert 'postgresql://' not in str(error.value) + caplog.text
    assert error.value.__cause__ is None
    with pytest.raises(ProjectTypeStorageError):
        project_type_frames.types_frame(service.get_all_types())
