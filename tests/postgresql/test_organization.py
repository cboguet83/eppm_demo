"""Organization services, privacy and concurrent writes on native PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import date
from threading import Barrier

import psycopg
import pytest

from app.application.exceptions import OrganizationConflictError, OrganizationStorageError
from app.application.services.business_access import BusinessAccess
from app.application.services.organization import OrganizationService
from app.domain.access.models import AccessDenied, DeploymentActor, Permission
from app.domain.hierarchy import HierarchyType
from app.domain.organization.models import Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team
from app.infrastructure.postgresql.organization import PostgresOrganizationGateway


@pytest.fixture
def organization(authorized):
    return OrganizationService(PostgresOrganizationGateway(authorized.database, authorized.key, access=authorized.binding(4).access))


def employee(code="EMP-001"):
    return Employee(" Ada ", " Lovelace ", f"{code.lower()}@example.test", code, occupation_percentage=80)


def exception(employee_id, start=1, end=10):
    return EmployeeCalendarException(employee_id, date(2026, 9, start), date(2026, 9, end), 0, " Leave ")


def test_crud_preserves_native_boolean_values_and_existing_organization_dtos(organization):
    service = organization
    assert service.get_all_function_types() == service.get_all_functions() == []
    assert service.get_all_teams() == service.get_all_employees() == []
    assert service.generate_next_employee_code() == "EMP-001"
    for getter in (service.get_function_type_by_id, service.get_function_by_id, service.get_team_by_id,
                   service.get_employee_by_id, service.get_employee_calendar_exception_by_id):
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
    assert service.get_employee_by_id(employee_id).email == "emp-001@example.test"
    assert service.generate_next_employee_code() == "EMP-002"
    assert service.check_email_exists("EMP-001@EXAMPLE.TEST") and not service.check_email_exists("EMP-001@EXAMPLE.TEST", employee_id)
    assert service.check_code_exists("emp-001") and not service.check_code_exists("emp-001", employee_id)
    assert service.update_function_type(FunctionType("Architecture", type_id))
    assert service.update_function(OrgFunction("Lead", 3, function_id, type_id, has_reports=True))
    assert service.update_team(Team("Renamed", team_id))
    assert service.update_employee(replace(employee(), employee_id=employee_id, occupation_percentage=60, function_id=function_id))
    assert service.get_all_functions()[0].has_reports is True
    assert service.get_all_function_types()[0].function_type == "Architecture"
    assert service.get_all_teams()[0].team_name == "Renamed"
    assert service.get_all_employees()[0].occupation_percentage == 60
    assert service.get_effective_occupation_percentage(employee_id, date(2026, 8, 31)) == 60
    with pytest.raises(OrganizationConflictError):
        service.delete_function_type(type_id)
    with pytest.raises(OrganizationConflictError):
        service.delete_function(function_id)
    with pytest.raises(OrganizationConflictError):
        service.create_employee(employee())
    assert service.delete_employee(employee_id)
    assert service.delete_team(team_id)
    assert service.delete_function(function_id)
    assert service.delete_function_type(type_id)
    for remover in (service.delete_function_type, service.delete_function, service.delete_team,
                    service.delete_employee, service.delete_employee_calendar_exception):
        assert not remover(-1)


@pytest.mark.parametrize("missing", [None, -1])
def test_updates_keep_missing_record_results_without_creating_memberships(organization, missing):
    assert not organization.update_function_type(FunctionType("Absent", missing))
    assert not organization.update_function(OrgFunction("Absent", 1, missing))
    assert not organization.update_team(Team("Absent", missing), function_ids=[999])
    assert not organization.update_employee(replace(employee(), employee_id=missing))
    assert not organization.update_employee_calendar_exception(replace(exception(1), exception_id=missing))


def test_team_membership_and_details_commit_or_rollback_together(organization):
    member = organization.create_function(OrgFunction("Member", 1))
    with pytest.raises(OrganizationConflictError):
        organization.create_team(Team("Partial"), function_ids=[member, 999])
    assert organization.get_all_teams() == []
    team_id = organization.create_team(Team("Original"), function_ids=[member])
    with pytest.raises(OrganizationConflictError):
        organization.update_team(Team("Partial rename", team_id), function_ids=[999])
    assert organization.get_team_by_id(team_id).team_name == "Original"
    with pytest.raises(OrganizationConflictError):
        organization.set_team_functions(team_id, [member, 999])
    assert organization.get_team_functions(team_id) == [member]
    assert not organization.add_team_function(team_id, member)
    assert organization.remove_team_function(team_id, member)
    assert not organization.remove_team_function(team_id, member)
    assert organization.add_team_function(team_id, member)
    with pytest.raises(OrganizationConflictError):
        organization.add_team_function(team_id, 999)
    assert organization.update_team(Team("Cleared", team_id), function_ids=[])
    assert organization.get_team_functions(team_id) == []


def test_employee_and_calendar_mutations_preserve_inclusive_dates_and_atomicity(organization):
    with pytest.raises(ValueError):
        organization.create_employee(employee(), initial_exception=exception(999, 10, 1))
    assert organization.get_all_employees() == []
    employee_id = organization.create_employee(employee(), initial_exception=exception(999))
    rows = organization.get_employee_calendar_exceptions(employee_id)
    assert len(rows) == 1 and rows[0].start_date == "2026-09-01" and rows[0].reason == "Leave"
    first = organization.get_employee_calendar_exception_by_id(rows[0].exception_id)
    assert first.start_date == date(2026, 9, 1)
    assert organization.get_effective_occupation_percentage(employee_id, date(2026, 9, 1)) == 0
    assert organization.get_effective_occupation_percentage(employee_id, date(2026, 9, 10)) == 0
    assert organization.get_effective_occupation_percentage(employee_id, date(2026, 9, 11)) == 80
    assert organization.has_overlapping_calendar_exception(employee_id, first.start_date, first.end_date)
    assert not organization.has_overlapping_calendar_exception(employee_id, first.start_date, first.end_date, first.exception_id)
    second = organization.create_employee_calendar_exception(exception(employee_id, 11, 20))
    with pytest.raises(ValueError, match="overlaps"):
        organization.update_employee_calendar_exception(replace(first, end_date=date(2026, 9, 11)))
    assert organization.update_employee_calendar_exception(replace(first, reason="Updated"))
    assert [row.exception_id for row in organization.get_employee_calendar_exceptions()] == [second, first.exception_id]
    assert organization.delete_employee_calendar_exception(second)
    assert organization.delete_employee(employee_id)
    assert organization.get_employee_calendar_exceptions() == []


def test_calendar_insert_failure_rolls_back_the_employee(organization, authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("CREATE FUNCTION eppm.reject_calendar() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private rejection' USING ERRCODE='23514'; END $$")
        connection.execute("CREATE TRIGGER reject_calendar BEFORE INSERT ON eppm.employee_calendar_exception FOR EACH ROW EXECUTE FUNCTION eppm.reject_calendar()")
    with pytest.raises(OrganizationConflictError) as error:
        organization.create_employee(employee(), initial_exception=exception(999))
    assert "private" not in str(error.value)
    assert organization.get_all_employees() == []


def test_hierarchy_labels_and_optional_team_assignments_are_atomic(organization):
    type_id = organization.save_hierarchy_type(HierarchyType("custom", {"en": "Custom", "fr": "Personnalisé"}))
    value = organization.get_all_hierarchy_types()[0]
    assert value.label("fr") == "Personnalisé"
    assert organization.save_hierarchy_type(replace(value, translations={"en": "Changed"})) == type_id
    assert organization.get_all_hierarchy_types()[0].translations == {"en": "Changed"}
    with pytest.raises(ValueError, match="cannot be changed"):
        organization.save_hierarchy_type(replace(value, code="renamed"))
    with pytest.raises(ValueError, match="no longer exists"):
        organization.save_hierarchy_type(replace(value, id=999))
    with pytest.raises(OrganizationConflictError):
        organization.save_hierarchy_type(HierarchyType("custom", {"en": "Duplicate"}))
    team_id = organization.create_team(Team("Unclassified"))
    team = organization.get_team_by_id(team_id)
    assert team.hierarchy_type_id is None
    assert organization.update_team(replace(team, hierarchy_type_id=type_id))
    with pytest.raises(OrganizationConflictError):
        organization.delete_hierarchy_type(type_id)
    with pytest.raises(OrganizationConflictError):
        organization.update_team(replace(team, hierarchy_type_id=999))
    assert organization.get_team_by_id(team_id).hierarchy_type_id == type_id
    assert organization.update_team(team)
    assert organization.delete_hierarchy_type(type_id)
    assert not organization.delete_hierarchy_type(type_id)


def test_scoped_reader_sees_only_name_projection_and_no_private_employee_fields(organization, authorized, caplog):
    function_id = organization.create_function(OrgFunction("Lead", 1))
    organization.create_employee(replace(employee(), function_id=function_id, mobile="private phone", landline="private landline"))
    reader = OrganizationService(PostgresOrganizationGateway(authorized.database, authorized.key, access=authorized.binding(1).access))
    assert asdict(reader.employee_references()[0]) == {"function_id": function_id, "firstname": "Ada", "lastname": "Lovelace"}
    assert reader.function_references()[0].name == "Lead"
    assert authorized.query('SELECT * FROM eppm.employee') == []
    assert authorized.query('SELECT * FROM eppm.employee_name_directory', user_id=3) == []
    with pytest.raises(psycopg.errors.UndefinedColumn):
        authorized.query('SELECT email FROM eppm.employee_name_directory')
    for operation in (reader.get_all_employees, lambda: reader.get_employee_by_id(1), reader.get_employee_calendar_exceptions,
                      lambda: reader.check_email_exists("emp-001@example.test"), lambda: reader.create_team(Team("Forbidden"))):
        with pytest.raises(AccessDenied):
            operation()
    assert len([row for row in caplog.records if 'business.authorization_denied' in row.message]) == 5
    assert "private phone" not in caplog.text


def test_runtime_gateway_rejects_operator_context_and_native_write_bypass(organization, authorized):
    operator = BusinessAccess(DeploymentActor("test", "request"), authorized.binding().access.policy)
    gateway = PostgresOrganizationGateway(authorized.database, authorized.key, access=operator)
    with pytest.raises(AccessDenied):
        OrganizationService(gateway).get_all_teams()
    gateway = PostgresOrganizationGateway(authorized.database, authorized.key, access=authorized.binding(1).access)
    with pytest.raises(AccessDenied):
        gateway.run(lambda store: store.create_team(Team("No service guard")), write=True)
    assert organization.get_all_teams() == []


def simultaneous_gateways(authorized):
    """Force both real transaction snapshots before their first service attempt."""
    barrier = Barrier(2)
    attempts = [0, 0]

    class GatedGateway(PostgresOrganizationGateway):
        def __init__(self, index):
            super().__init__(authorized.database, authorized.key, access=authorized.binding(4).access)
            self.index = index

        def run(self, operation, **options):
            def callback(store):
                attempts[self.index] += 1
                if attempts[self.index] == 1:
                    barrier.wait(timeout=10)
                return operation(store)
            return super().run(callback, **options)

    return [OrganizationService(GatedGateway(index)) for index in range(2)], attempts


def test_concurrent_team_replacements_replay_complete_details_and_membership(organization, authorized):
    members = [organization.create_function(OrgFunction(name, 1)) for name in ("First", "Second")]
    team_id = organization.create_team(Team("Initial"))
    services, attempts = simultaneous_gateways(authorized)
    def update(index):
        return services[index].update_team(Team(str(index), team_id), function_ids=[members[index]])
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(update, range(2))) == [True, True]
    final = organization.get_team_by_id(team_id)
    assert organization.get_team_functions(team_id) == [members[int(final.team_name)]]
    assert sum(attempts) >= 3


def test_concurrent_calendar_inserts_revalidate_overlap_after_retry(organization, authorized):
    employee_id = organization.create_employee(employee())
    services, attempts = simultaneous_gateways(authorized)
    def insert(index):
        try:
            services[index].create_employee_calendar_exception(exception(employee_id, 1 + index, 10 + index))
            return "saved"
        except ValueError as error:
            assert "overlaps" in str(error)
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(insert, range(2))) == ["conflict", "saved"]
    assert len(organization.get_employee_calendar_exceptions()) == 1
    assert sum(attempts) >= 3


def test_native_date_output_is_independent_of_session_datestyle(organization, authorized):
    employee_id = organization.create_employee(employee(), initial_exception=exception(999))
    def query(store):
        store.connection.execute("SET LOCAL datestyle = 'SQL, DMY'")
        return store.get_employee_calendar_exceptions(employee_id)
    gateway = PostgresOrganizationGateway(authorized.database, authorized.key, access=authorized.binding(4).access)
    assert gateway.run(query, permission=Permission.SHARED)[0].start_date == "2026-09-01"


def test_native_storage_outage_has_safe_existing_application_error(organization, authorized, caplog):
    authorized.database.close()
    with pytest.raises(OrganizationStorageError) as error:
        organization.get_all_teams()
    assert "postgresql://" not in str(error.value) + caplog.text
