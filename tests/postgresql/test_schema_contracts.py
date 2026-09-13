"""Schema domain contracts, real PostgreSQL integrity, and display projections."""

from app.application.exceptions import SchemaStorageError

from app.main import create_schema_service

from app.presentation.components import schema_frames

import psycopg
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.application.services.business_access import BusinessAccess
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access

from app.application.exceptions import SchemaConflictError
from app.application.services.schema import SchemaService
from app.domain.projects.schema import next_group_order, next_parameter_id
from app.infrastructure.postgresql.schema import PostgresSchemaGateway, PostgresSchemaStore
from app.main import create_project_service, create_project_type_service


@pytest.fixture
def database(runtime: RuntimeResources) -> RuntimeResources:
    """Use native resources over a separately migrated test database."""
    return runtime


def test_identifier_and_order_rules_use_canonical_codes_and_fill_gaps() -> None:
    assert next_group_order([1, 3, None, 0, -1]) == 2
    assert next_group_order([]) == 1
    assert next_parameter_id([]) == "PRM_001"
    assert next_parameter_id(["PRM_002", "4", "PRM_009_extra", "PRM_", "PRM_bad", "custom"]) == "PRM_003"
    assert next_parameter_id(["PRM_009", "PRM_003"]) == "PRM_010"


def test_invalid_schema_inputs_are_rejected_before_opening_storage() -> None:
    class UnavailableGateway:
        def run(self, operation, *, write=False, **kwargs):
            raise AssertionError("Invalid input must not open storage")

    service = SchemaService(UnavailableGateway())
    actions = [
        lambda: service.create_group(" ", 1),
        lambda: service.update_group(1, "Valid", 0),
        lambda: service.create_group("Valid", True),
        lambda: service.create_parameter(" ", None, "Name", "TEXT"),
        lambda: service.create_parameter(None, None, "Name", "UNSUPPORTED"),
        lambda: service.create_parameter(None, None, "Name", "TEXT", applies_to_all=False),
        lambda: service.create_parameter(None, None, "Name", "ENUM", initial_options=[" "]),
        lambda: service.add_option("p", " ", 1),
        lambda: service.add_option("p", "Valid", -1),
    ]
    for action in actions:
        with pytest.raises(ValueError):
            action()


def test_initial_choice_failure_rolls_back_property_scope_and_prior_choices(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    service = create_schema_service(database, access=access)
    special = create_project_type_service(database, access=access).create_type("Rail")
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("""CREATE FUNCTION eppm.reject_choice() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private failure detail' USING ERRCODE='23514'; END $$""")
        conn.execute("""CREATE TRIGGER reject_choice BEFORE INSERT ON eppm.schema_param_options
            FOR EACH ROW WHEN (NEW.option_value='Reject') EXECUTE FUNCTION eppm.reject_choice()""")
    with pytest.raises(SchemaConflictError) as error:
        service.create_parameter(None, None, "Route", "ENUM", applies_to_all=False,
                                 project_type_ids=[special], initial_options=["First", "Reject"])
    assert "private failure" not in str(error.value)
    assert error.value.__cause__ is None
    assert service.get_snapshot().parameters == []
    assert service.get_snapshot().options == []
    with psycopg.connect(authorized.setup.operator_url) as conn:
        assert conn.execute("SELECT COUNT(*) FROM eppm.project_type_property").fetchone()[0] == 0
        conn.execute("DROP TRIGGER reject_choice ON eppm.schema_param_options")
    assert service.generate_param_id() == "PRM_001"
    assert service.create_parameter(None, None, "Route", "ENUM", initial_options=["First"]) == "PRM_001"


def test_failed_scope_change_restores_all_property_details(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_schema_service(database, access=access)
    group = service.create_group("Original", 1)
    service.create_parameter("p", group, "Original", "TEXT", alias="Alias")
    before = service.get_snapshot()
    with pytest.raises(SchemaConflictError):
        service.update_parameter("p", None, "Changed", "TEXT", True, "Changed alias", False, [1, 999])
    assert service.get_snapshot() == before
    assert create_project_type_service(database, access=access).get_applicability("p").applies_to_all is True
    service.update_parameter("p", None, "Updated", "TEXT", applies_to_all=False, project_type_ids=[1])
    service.update_parameter("p", group, "Only details changed", "TEXT")
    assert create_project_type_service(database, access=access).get_applicability("p").type_ids == (1,)


@pytest.mark.parametrize("defaults", [False, True], ids=["project", "template-default"])
@pytest.mark.parametrize("kind", ["ENUM", "MULTI_ENUM"])
def test_reference_guards_cover_scalar_and_list_project_values_and_defaults(
    database: RuntimeResources, access: BusinessAccess, defaults: bool, kind: str,
) -> None:
    service = create_schema_service(database, access=access)
    types = create_project_type_service(database, access=access)
    projects = create_project_service(database, access=access)
    service.create_parameter("p", None, "Choice", kind, initial_options=["A"])
    option = service.get_all_options()[0]
    value = ["A"] if kind == "MULTI_ENUM" else "A"
    if defaults:
        types.save_rule(1, "p", has_default=True, default_value=value)
    else:
        project_id = projects.create_project(name="References", dynamic_attributes={"p": value})
    for action in (
        lambda: service.delete_option(option.id),
        lambda: service.delete_parameter(" p "),
        lambda: service.update_parameter(" p ", None, "Changed", "NUMBER"),
    ):
        with pytest.raises(ValueError):
            action()
    assert service.get_all_parameters()[0].param_type == kind
    if defaults:
        types.save_rule(1, "p", has_default=False)
    else:
        projects.delete_project(project_id)
    assert service.delete_option(option.id)
    assert service.update_parameter(" p ", None, "Changed", "NUMBER")
    assert service.delete_parameter(" p ")


def test_explicit_null_still_protects_property_type_and_deletion(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_schema_service(database, access=access)
    service.create_parameter("p", None, "Nullable", "TEXT")
    create_project_type_service(database, access=access).save_rule(1, "p", has_default=True, default_value=None)
    with pytest.raises(ValueError, match="Clear stored values"):
        service.update_parameter(" p ", None, "Nullable", "NUMBER")
    with pytest.raises(ValueError, match="stored values or defaults"):
        service.delete_parameter("p")


def test_group_deletion_rolls_back_ungrouping_and_preserves_project_values(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    service = create_schema_service(database, access=access)
    group = service.create_group("Group", 1)
    service.create_parameter("p", group, "Property", "TEXT")
    projects = create_project_service(database, access=access)
    pid = projects.create_project(name="Project", dynamic_attributes={"p": "Retained"})
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("""CREATE FUNCTION eppm.reject_group_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'blocked' USING ERRCODE='23514'; END $$""")
        conn.execute("""CREATE TRIGGER reject_group_delete BEFORE DELETE ON eppm.schema_groups
            FOR EACH ROW EXECUTE FUNCTION eppm.reject_group_delete()""")
    with pytest.raises(SchemaConflictError):
        service.delete_group(group)
    assert service.get_all_parameters()[0].group_id == group
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("DROP TRIGGER reject_group_delete ON eppm.schema_groups")
    assert service.delete_group(group)
    assert service.get_all_parameters()[0].group_id is None
    assert projects.get_project_by_id(pid).dynamic_attributes == {"p": "Retained"}


def test_property_deletion_rolls_back_option_removal_if_parent_delete_fails(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    service = create_schema_service(database, access=access)
    service.create_parameter("p", None, "Choice", "ENUM", initial_options=["A", "B"])
    before = service.get_snapshot()
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("""CREATE FUNCTION eppm.reject_property_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'blocked' USING ERRCODE='23514'; END $$""")
        conn.execute("""CREATE TRIGGER reject_property_delete BEFORE DELETE ON eppm.schema_parameters
            FOR EACH ROW EXECUTE FUNCTION eppm.reject_property_delete()""")
    with pytest.raises(SchemaConflictError):
        service.delete_parameter("p")
    assert service.get_snapshot() == before


def test_concurrent_creates_allocate_fresh_ids_and_free_group_orders(database: RuntimeResources, access: BusinessAccess) -> None:
    first, second = create_schema_service(database, access=access), create_schema_service(database, access=access)
    assert first.generate_param_id() == second.generate_param_id() == "PRM_001"
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(service.create_parameter, None, None, name, "TEXT")
                   for service, name in ((first, "First"), (second, "Second"))]
        assert {future.result() for future in futures} == {"PRM_001", "PRM_002"}
        futures = [executor.submit(service.create_group, name, 1, auto_assign_order=True)
                   for service, name in ((first, "First"), (second, "Second"))]
        assert len({future.result() for future in futures}) == 2
    assert [group.display_order for group in first.get_all_groups()] == [1, 2]
    second_group = first.get_all_groups()[1]
    with pytest.raises(SchemaConflictError, match="order"):
        first.update_group(second_group.id, second_group.group_name, 1)


def test_schema_missing_records_and_display_projection(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_schema_service(database, access=access)
    other_service = create_schema_service(database, access=access)
    assert other_service.create_parameter(" p ", None, " Name ", "TEXT", True, " Alias ") == "p"
    frame = schema_frames.parameters_frame(other_service.get_all_parameters())
    assert (frame.iloc[0].param_id, frame.iloc[0].alias, frame.iloc[0].mandatory) == ("p", "Alias", 1)
    assert service.get_all_parameters()[0].mandatory is True
    assert not service.update_parameter("missing", None, "Missing", "TEXT")
    with pytest.raises(ValueError, match="Unknown property"):
        service.update_parameter("missing", None, "Missing", "TEXT", applies_to_all=True)
    assert not service.delete_group(999)
    assert not service.update_group(999, "Missing", 1)
    assert not service.delete_parameter("missing")
    assert not service.delete_option(999)
    with pytest.raises(SchemaConflictError):
        other_service.create_parameter("p", None, "Duplicate", "TEXT")
    group = other_service.create_group("Group", 1)
    with pytest.raises(SchemaConflictError):
        other_service.create_group("Group", 2)
    assert other_service.update_group(group, "Updated", 3)
    assert create_schema_service(database, access=access).get_next_available_group_order() == 1


def test_gateway_preserves_reference_guards_and_reuses_leases_after_failure(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    """Guarded changes roll back without locking unrelated project writers."""
    service = create_schema_service(database, access=access)
    service.get_snapshot()
    service.create_parameter("p", None, "Choice", "ENUM", initial_options=["A"])
    with pytest.raises(SchemaConflictError):
        service.create_parameter("p", None, "Duplicate", "TEXT")
    create_project_type_service(database, access=access).save_rule(1, "p", has_default=True, default_value="A")
    with pytest.raises(ValueError):
        service.delete_parameter("p")
    before = service.get_snapshot()
    gateway = PostgresSchemaGateway(database.database, database.key, access=access)

    def reject_after_guard(store: PostgresSchemaStore) -> None:
        assert store.has_property_values("p")
        store.update_parameter(replace(store.parameters()[0], param_name="Rolled back"))
        with psycopg.connect(authorized.setup.operator_url) as other:
            other.execute("SET LOCAL statement_timeout='1s'")
            other.execute("UPDATE eppm.project SET name='Independent' WHERE id=2")
        raise ValueError("cancel")

    with pytest.raises(ValueError, match="cancel"):
        gateway.run(reject_after_guard, write=True)
    assert service.get_snapshot() == before
    assert authorized.query('SELECT name FROM eppm.project WHERE id=2', user_id=4) == [('Independent',)]


def test_schema_storage_failures_are_translated_to_safe_errors(
    database: RuntimeResources, access: BusinessAccess, caplog: pytest.LogCaptureFixture,
) -> None:
    """An actual closed pool produces safe service and frame errors."""
    service = create_schema_service(database, access=access)
    database.database.close()
    with pytest.raises(SchemaStorageError) as error:
        service.get_snapshot()
    assert 'postgresql://' not in str(error.value) + caplog.text
    assert error.value.__cause__ is None
    with pytest.raises(SchemaStorageError):
        schema_frames.groups_frame(service.get_all_groups())
