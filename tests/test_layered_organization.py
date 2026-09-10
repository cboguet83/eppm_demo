"""Organization rules, real SQLite transactions, and display projections."""

from app.operator_services import deployment_access
from app.application.exceptions import OrganizationConflictError, OrganizationStorageError

from app.presentation.components import organization_frames

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from app.domain.organization.models import (
    Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team,
)
from app.domain.organization.rules import (
    next_employee_code, normalize_employee, normalize_exception, normalize_function,
    normalize_function_type, normalize_team, validate_employee_calendar_exception,
    validate_function, validate_occupation_percentage,
)
from app.infrastructure.repositories.organization import SqliteOrganizationGateway
from app.operator_services import create_organization_service
from app.infrastructure.database.schema_init import init_db


@pytest.fixture
def database(tmp_path: Path) -> str:
    """Create the real existing schema in a disposable database."""
    path = str(tmp_path / "organization.db")
    init_db(path)
    return path


def employee(code: str = "EMP-001") -> Employee:
    """Build a valid profile whose email is distinct for each code."""
    return Employee(" Ada ", " Lovelace ", f" {code}@Example.com ", code,
                    mobile=" 123 ", sigle=" al ", occupation_percentage=80.0)


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
    assert (normalized.mobile, normalized.sigle, normalized.employee_code) == ("123", "AL", "EMP-001")
    assert normalize_exception(exception(1)).reason == "Leave"
    assert employee().firstname == " Ada "
    assert next_employee_code(["manual", "EMP-003-OLD", "emp-004", "EMP-²"]) == "EMP-005"
    assert next_employee_code(["EMP-٠٠٩"]) == "EMP-010"
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


def test_application_crud_and_display_frames_handle_missing_records(database: str) -> None:
    service = create_organization_service(database)
    other_service = create_organization_service(database)
    assert service.get_all_function_types() == service.get_all_functions() == []
    assert service.get_all_teams() == service.get_all_employees() == []
    assert service.get_employee_calendar_exceptions() == []
    assert service.generate_next_employee_code() == "EMP-001"
    assert list(organization_frames.employees_frame(other_service.get_all_employees()).columns) == [
        "employee_id", "firstname", "lastname", "email", "mobile", "landline", "sigle",
        "employee_code", "function_id", "occupation_percentage",
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
    assert service.generate_next_employee_code() == "EMP-002"
    assert service.check_email_exists("EMP-001@EXAMPLE.COM")
    assert not service.check_email_exists("EMP-001@EXAMPLE.COM", employee_id)
    assert service.check_code_exists("emp-001")
    assert not service.check_code_exists("emp-001", employee_id)
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

    with pytest.raises(OrganizationConflictError) as conflict:
        service.delete_function_type(type_id)
    assert isinstance(conflict.value.__cause__, sqlite3.IntegrityError)
    with pytest.raises(OrganizationConflictError):
        other_service.delete_function(function_id)
    with pytest.raises(OrganizationConflictError):
        other_service.create_employee(employee())
    assert service.delete_employee(employee_id)
    assert service.delete_team(team_id)
    assert service.delete_function(function_id)
    assert service.delete_function_type(type_id)
    for remover in (service.delete_function_type, service.delete_function,
                    service.delete_team, service.delete_employee,
                    service.delete_employee_calendar_exception):
        assert not remover(-1)


@pytest.mark.parametrize("with_id", [False, True])
def test_updates_preserve_missing_record_boolean_contracts(database: str, with_id: bool) -> None:
    service = create_organization_service(database)
    missing = -1 if with_id else None
    assert not service.update_function_type(FunctionType("Absent", missing))
    assert not service.update_function(OrgFunction("Absent", 1, missing))
    assert not service.update_team(Team("Absent", missing), function_ids=[999])
    assert not service.update_employee(replace(employee(), employee_id=missing))
    assert not service.update_employee_calendar_exception(replace(exception(1), exception_id=missing))


def test_team_details_and_membership_rollback_together(database: str) -> None:
    service = create_organization_service(database)
    member = service.create_function(OrgFunction("Member", 1))
    with pytest.raises(OrganizationConflictError):
        service.create_team(Team("Partial"), function_ids=[member, 999])
    assert service.get_all_teams() == []
    team_id = service.create_team(Team("Original"), function_ids=[member])
    with pytest.raises(OrganizationConflictError):
        service.update_team(Team("Partial rename", team_id), function_ids=[999])
    assert service.get_team_by_id(team_id).team_name == "Original"
    assert service.get_team_functions(team_id) == [member]
    pools = create_organization_service(database)
    with pytest.raises(OrganizationConflictError):
        pools.set_team_functions(team_id, [member, 999])
    assert pools.get_team_functions(team_id) == [member]
    assert not pools.add_team_function(team_id, member)
    assert pools.remove_team_function(team_id, member)
    assert not pools.remove_team_function(team_id, member)
    assert pools.add_team_function(team_id, member)
    assert service.update_team(Team("Cleared", team_id), function_ids=[])
    assert service.get_team_functions(team_id) == []


def test_employee_and_initial_exception_rollback_on_validation_and_sql_failure(database: str) -> None:
    service = create_organization_service(database)
    with pytest.raises(ValueError):
        service.create_employee(employee(), initial_exception=exception(999, 10, 1))
    assert service.get_all_employees() == []
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""CREATE TRIGGER reject_exception BEFORE INSERT ON employee_calendar_exception
                              BEGIN SELECT RAISE(ABORT, 'test rejection'); END""")
    with pytest.raises(OrganizationConflictError):
        service.create_employee(employee(), initial_exception=exception(999))
    assert service.get_all_employees() == service.get_employee_calendar_exceptions() == []
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("DROP TRIGGER reject_exception")
    employee_id = service.create_employee(employee(), initial_exception=exception(999))
    rows = service.get_employee_calendar_exceptions(employee_id)
    assert len(rows) == 1 and rows[0].employee_id == employee_id
    assert rows[0].reason == "Leave"
    assert service.get_effective_occupation_percentage(employee_id, date(2026, 9, 1)) == 0
    assert service.get_effective_occupation_percentage(employee_id, date(2026, 9, 10)) == 0
    assert service.get_effective_occupation_percentage(employee_id, date(2026, 9, 11)) == 80
    assert service.delete_employee(employee_id)
    assert service.get_employee_calendar_exceptions() == []


def test_calendar_edits_exclude_current_record_and_preserve_ordering(database: str) -> None:
    other_service = create_organization_service(database)
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


def test_concurrent_calendar_writers_cannot_insert_overlapping_periods(database: str) -> None:
    service = create_organization_service(database)
    employee_id = service.create_employee(employee())
    start = Barrier(2)

    def save() -> str:
        start.wait(timeout=5)
        try:
            create_organization_service(database).create_employee_calendar_exception(exception(employee_id))
            return "saved"
        except ValueError as exc:
            assert "overlaps" in str(exc)
            return "overlap"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: save(), range(2)))
    assert sorted(results) == ["overlap", "saved"]
    assert len(service.get_employee_calendar_exceptions(employee_id)) == 1


@pytest.mark.parametrize("operation", ["read", "write", "rollback"])
def test_gateway_reserves_writers_and_closes_connections(database: str, monkeypatch, operation: str) -> None:
    from app.infrastructure.database.connection import get_db

    captured = get_db(database)
    monkeypatch.setattr("app.infrastructure.repositories.organization.get_db", lambda _: captured)
    gateway = SqliteOrganizationGateway(database, access=deployment_access())
    if operation == "rollback":
        with pytest.raises(ValueError, match="cancel"):
            with gateway.transaction(write=True) as store:
                store.create_team(Team("Rolled back"))
                raise ValueError("cancel")
    else:
        with gateway.transaction(write=operation == "write") as store:
            assert store.get_all_teams() == []
            if operation == "write":
                with closing(sqlite3.connect(database, timeout=0)) as contender:
                    with pytest.raises(sqlite3.OperationalError, match="locked"):
                        contender.execute("BEGIN IMMEDIATE")
                store.create_team(Team("Committed"))
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        captured.execute("SELECT 1")
    with closing(sqlite3.connect(database)) as check:
        assert check.execute("SELECT COUNT(*) FROM team").fetchone()[0] == (operation == "write")


def test_organization_storage_errors_are_safe_across_services_and_frames(tmp_path: Path) -> None:
    path = str(tmp_path / "missing" / "organization.db")
    with pytest.raises(OrganizationStorageError) as error:
        create_organization_service(path).get_all_functions()
    assert path not in str(error.value)
    assert isinstance(error.value.__cause__, sqlite3.OperationalError)
    with pytest.raises(OrganizationStorageError):
        organization_frames.functions_frame(create_organization_service(path).get_all_functions())
