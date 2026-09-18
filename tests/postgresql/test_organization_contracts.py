"""Organization rules, real PostgreSQL transactions, and display projections."""

from app.application.exceptions import OrganizationConflictError, OrganizationStorageError

from app.presentation.components import organization_frames

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
import psycopg
from threading import Barrier

import pytest

from app.application.services.business_access import BusinessAccess
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access

from app.domain.organization.models import (
    Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team,
)
from app.domain.organization.rules import (
    normalize_employee, normalize_exception, normalize_function,
    normalize_function_type, normalize_team, validate_employee_calendar_exception,
    validate_function, validate_occupation_percentage,
)
from app.infrastructure.postgresql.organization import PostgresOrganizationGateway, PostgresOrganizationStore
from app.main import create_organization_service


@pytest.fixture
def database(runtime: RuntimeResources) -> RuntimeResources:
    """Use a separately migrated database and the process-shaped native resources."""
    return runtime


def employee(code: str = "EMP-001") -> Employee:
    """Build a valid profile whose email is distinct for each code."""
    return Employee(" Ada ", " Lovelace ", f" {code}@Example.com ", mobile=" 123 ", sigle=" al ", occupation_percentage=80.0)


def exception(employee_id: int, start: int = 1, end: int = 10) -> EmployeeCalendarException:
    """Build an inclusive September override."""
    return EmployeeCalendarException(employee_id, date(2026, 9, start),
                                     date(2026, 9, end), 0.0, " Leave ")


@pytest.mark.parametrize("value", [-1.0, 101.0, float("nan"), float("inf")])
def test_occupation_percentage_rejects_invalid_and_nonfinite_values(value: float) -> None:
    with pytest.raises(ValueError, match="Occupation"):
        validate_occupation_percentage(value)
    with pytest.raises(ValueError):
        normalize_employee(replace(employee(), occupation_percentage=value))
    with pytest.raises(ValueError):
        normalize_exception(replace(exception(1), occupation_percentage=value))


def test_domain_normalization_and_existing_function_capacity_contract() -> None:
    assert normalize_function_type(FunctionType(" Engineering ")).function_type == "Engineering"
    assert normalize_team(Team(" Platform ")).team_name == "Platform"
    assert normalize_function(OrgFunction(" Architect ", 2, fte_percentage=200)).fte_percentage == 200
    assert normalize_function(OrgFunction(" Architect ", 2, fte_percentage=None)).fte_percentage == 100
    normalized = normalize_employee(employee())
    assert (normalized.firstname, normalized.lastname, normalized.email) == (
        "Ada", "Lovelace", "emp-001@example.com",
    )
    assert (normalized.mobile, normalized.sigle) == ("123", "AL")
    assert normalize_exception(exception(1)).reason == "Leave"
    assert employee().firstname == " Ada "
    for invalid in ("", "  "):
        with pytest.raises(ValueError):
            normalize_function_type(FunctionType(invalid))
        with pytest.raises(ValueError):
            normalize_team(Team(invalid))
    for fte in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            normalize_function(OrgFunction("Architect", 1, fte_percentage=fte))
    for level in (None, 0, 1.5, True):
        with pytest.raises(ValueError, match="Hierarchy"):
            validate_function("Architect", level)
    with pytest.raises(ValueError):
        validate_function("Architect", 1, 200)
    with pytest.raises(ValueError, match="dates"):
        validate_employee_calendar_exception(None, date(2026, 9, 1), 0)
    with pytest.raises(ValueError, match="End date"):
        normalize_exception(exception(1, 10, 1))


def test_application_crud_and_display_frames_handle_missing_records(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_organization_service(database, access=access)
    other_service = create_organization_service(database, access=access)
    assert service.get_all_function_types() == service.get_all_functions() == []
    assert service.get_all_teams() == service.get_all_employees() == []
    assert service.get_employee_calendar_exceptions() == []
    assert list(organization_frames.employees_frame(other_service.get_all_employees()).columns) == [
        "employee_id", "firstname", "lastname", "email", "mobile", "landline", "sigle",
        "function_id", "occupation_percentage",
    ]
    for getter in (service.get_function_type_by_id, service.get_function_by_id,
                   service.get_team_by_id, service.get_employee_by_id,
                   service.get_employee_calendar_exception_by_id):
        assert getter(-1) is None
    assert service.get_effective_occupation_percentage(-1, date(2026, 9, 1)) is None

    type_id = service.create_function_type(FunctionType(" Engineering "))
    function_id = service.create_function(OrgFunction(" Architect ", 2, function_type_id=type_id))
    team_id = service.create_team(Team(" Platform "), function_ids=[function_id, function_id])
    employee_id = service.create_employee(replace(employee(), function_id=function_id))
    assert service.get_team_functions(team_id) == [function_id]
    assert service.get_function_type_by_id(type_id).function_type == "Engineering"
    assert service.get_function_by_id(function_id).name == "Architect"
    assert service.get_team_by_id(team_id).team_name == "Platform"
    assert service.get_employee_by_id(employee_id).email == "emp-001@example.com"
    assert service.check_email_exists("EMP-001@EXAMPLE.COM")
    assert not service.check_email_exists("EMP-001@EXAMPLE.COM", employee_id)
    assert service.update_function_type(FunctionType("Architecture", type_id))
    assert service.update_function(OrgFunction("Lead", 3, function_id, type_id, has_reports=True))
    assert service.update_team(Team("Renamed", team_id))
    assert service.get_team_functions(team_id) == [function_id]
    assert service.update_employee(replace(
        employee(), employee_id=employee_id, occupation_percentage=60, function_id=function_id,
    ))
    assert organization_frames.functions_frame(other_service.get_all_functions()).iloc[0]["has_reports"] == 1
    assert not organization_frames.function_types_frame(other_service.get_all_function_types()).empty
    assert not organization_frames.teams_frame(other_service.get_all_teams()).empty
    assert not organization_frames.employees_frame(other_service.get_all_employees()).empty
    assert service.get_effective_occupation_percentage(employee_id, date(2026, 8, 31)) == 60

    with pytest.raises(ValueError, match='in use') as conflict:
        service.delete_function_type(type_id)
    assert conflict.value.__cause__ is None
    assert other_service.delete_function(function_id)
    with pytest.raises(OrganizationConflictError):
        other_service.create_employee(employee())
    assert service.delete_employee(employee_id)
    assert service.delete_team(team_id)
    assert not service.delete_function(function_id)
    with pytest.raises(ValueError, match='in use'):
        service.delete_function_type(type_id)
    for remover in (service.delete_function_type, service.delete_function,
                    service.delete_team, service.delete_employee,
                    service.delete_employee_calendar_exception):
        assert not remover(-1)


@pytest.mark.parametrize("with_id", [False, True])
def test_updates_preserve_missing_record_boolean_contracts(database: RuntimeResources, access: BusinessAccess, with_id: bool) -> None:
    service = create_organization_service(database, access=access)
    missing = -1 if with_id else None
    assert not service.update_function_type(FunctionType("Absent", missing))
    assert not service.update_function(OrgFunction("Absent", 1, missing))
    assert not service.update_team(Team("Absent", missing), function_ids=[999])
    assert not service.update_employee(replace(employee(), employee_id=missing))
    assert not service.update_employee_calendar_exception(replace(exception(1), exception_id=missing))


def test_team_details_and_membership_rollback_together(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_organization_service(database, access=access)
    member = service.create_function(OrgFunction("Member", 1))
    with pytest.raises(ValueError, match='no longer exists'):
        service.create_team(Team("Partial"), function_ids=[member, 999])
    assert service.get_all_teams() == []
    team_id = service.create_team(Team("Original"), function_ids=[member])
    with pytest.raises(ValueError, match='no longer exists'):
        service.update_team(Team("Partial rename", team_id), function_ids=[999])
    assert service.get_team_by_id(team_id).team_name == "Original"
    assert service.get_team_functions(team_id) == [member]
    pools = create_organization_service(database, access=access)
    with pytest.raises(ValueError, match='no longer exists'):
        pools.set_team_functions(team_id, [member, 999])
    assert pools.get_team_functions(team_id) == [member]
    assert not pools.add_team_function(team_id, member)
    assert pools.remove_team_function(team_id, member)
    assert not pools.remove_team_function(team_id, member)
    assert pools.add_team_function(team_id, member)
    assert service.update_team(Team("Cleared", team_id), function_ids=[])
    assert service.get_team_functions(team_id) == []


def test_employee_and_initial_exception_rollback_on_validation_and_sql_failure(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    service = create_organization_service(database, access=access)
    with pytest.raises(ValueError):
        service.create_employee(employee(), initial_exception=exception(999, 10, 1))
    assert service.get_all_employees() == []
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_exception() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test rejection' USING ERRCODE='23514'; END $$""")
        connection.execute("""CREATE TRIGGER reject_exception BEFORE INSERT ON eppm.employee_calendar_exception
            FOR EACH ROW EXECUTE FUNCTION eppm.reject_exception()""")
    with pytest.raises(OrganizationConflictError):
        service.create_employee(employee(), initial_exception=exception(999))
    assert service.get_all_employees() == service.get_employee_calendar_exceptions() == []
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DROP TRIGGER reject_exception ON eppm.employee_calendar_exception")
    employee_id = service.create_employee(employee(), initial_exception=exception(999))
    rows = service.get_employee_calendar_exceptions(employee_id)
    assert len(rows) == 1 and rows[0].employee_id == employee_id
    assert rows[0].reason == "Leave"
    assert service.get_effective_occupation_percentage(employee_id, date(2026, 9, 1)) == 0
    assert service.get_effective_occupation_percentage(employee_id, date(2026, 9, 10)) == 0
    assert service.get_effective_occupation_percentage(employee_id, date(2026, 9, 11)) == 80
    assert service.delete_employee(employee_id)
    assert service.get_employee_calendar_exceptions() == []


def test_calendar_edits_exclude_current_record_and_preserve_ordering(database: RuntimeResources, access: BusinessAccess) -> None:
    other_service = create_organization_service(database, access=access)
    employee_id = other_service.create_employee(employee())
    first = other_service.create_employee_calendar_exception(exception(employee_id))
    second = other_service.create_employee_calendar_exception(exception(employee_id, 11, 20))
    assert other_service.has_overlapping_calendar_exception(employee_id, date(2026, 9, 10), date(2026, 9, 11))
    assert not other_service.has_overlapping_calendar_exception(employee_id, date(2026, 9, 1), date(2026, 9, 10), first)
    assert other_service.update_employee_calendar_exception(replace(exception(employee_id, 1, 9), exception_id=first))
    with pytest.raises(ValueError, match="overlaps"):
        other_service.update_employee_calendar_exception(replace(exception(employee_id, 9, 12), exception_id=first))
    assert other_service.get_employee_calendar_exception_by_id(first).end_date == date(2026, 9, 9)
    assert organization_frames.exceptions_frame(other_service.get_employee_calendar_exceptions()).exception_id.tolist() == [second, first]
    assert other_service.delete_employee_calendar_exception(first)
    assert not other_service.delete_employee_calendar_exception(first)


def test_concurrent_calendar_writers_cannot_insert_overlapping_periods(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_organization_service(database, access=access)
    employee_id = service.create_employee(employee())
    start = Barrier(2)

    def save() -> str:
        start.wait(timeout=5)
        try:
            create_organization_service(database, access=access).create_employee_calendar_exception(exception(employee_id))
            return "saved"
        except ValueError as exc:
            assert "overlaps" in str(exc)
            return "overlap"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: save(), range(2)))
    assert sorted(results) == ["overlap", "saved"]
    assert len(service.get_employee_calendar_exceptions(employee_id)) == 1


@pytest.mark.parametrize("operation", ["read", "write", "rollback"])
def test_gateway_commits_or_rolls_back_and_reuses_the_pool(
    database: RuntimeResources, access: BusinessAccess,
    authorized: AuthorizedFixture, operation: str,
) -> None:
    """Returning a lease preserves atomic writes without a database-wide writer lock."""
    gateway = PostgresOrganizationGateway(database.database, database.key, access=access)

    def execute(store: PostgresOrganizationStore) -> None:
        assert store.get_all_teams() == []
        if operation != "read":
            store.create_team(Team("Committed"))
            with psycopg.connect(authorized.setup.operator_url) as contender:
                contender.execute("SET LOCAL statement_timeout='1s'")
                contender.execute("UPDATE eppm.project SET name='Independent' WHERE id=2")
        if operation == "rollback":
            raise ValueError("cancel")

    if operation == "rollback":
        with pytest.raises(ValueError, match="cancel"):
            gateway.run(execute, write=True)
    else:
        gateway.run(execute, write=operation == "write")

    teams = gateway.run(lambda store: store.get_all_teams())
    assert [team.team_name for team in teams] == (["Committed"] if operation == "write" else [])
    if operation != "read":
        assert authorized.query('SELECT name FROM eppm.project WHERE id=2', user_id=4) == [('Independent',)]
    with pytest.raises(OrganizationStorageError) as failure:
        gateway.run(lambda store: store.connection.execute('SELECT * FROM eppm.missing_table'))
    assert "missing_table" not in str(failure.value)
    assert gateway.run(lambda store: store.get_all_teams()) == teams


def test_organization_storage_errors_are_safe_across_services_and_frames(
    database: RuntimeResources, access: BusinessAccess, caplog: pytest.LogCaptureFixture,
) -> None:
    """A real pool outage produces the existing safe application error."""
    service = create_organization_service(database, access=access)
    database.database.close()
    with pytest.raises(OrganizationStorageError) as error:
        service.get_all_functions()
    assert "postgresql://" not in str(error.value) + caplog.text
    assert error.value.__cause__ is None
    with pytest.raises(OrganizationStorageError):
        organization_frames.functions_frame(service.get_all_functions())
