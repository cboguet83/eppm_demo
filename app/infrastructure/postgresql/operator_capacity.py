"""Native capacity source records for explicit operator previews only."""

from datetime import date

import psycopg

from app.domain.organization.models import EmployeeCalendarException
from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.mapping_allocation import MappingCatalog
from app.infrastructure.postgresql.organization import PostgresOrganizationStore
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore


def read_operator_capacity_inputs(
    connection: psycopg.Connection, pool_ids: list[int],
) -> dict[int, CapacityInputs]:
    """Read shared source records once on the separate operator connection.

    Operator previews need mutable mapping inputs to simulate staffing changes.
    Runtime readers continue to use the guarded, aggregate-only staffing path;
    no SQL privileges or actor requirements are changed by this helper.
    """
    organization = PostgresOrganizationStore(connection)
    store = PostgresResourcePoolStore(connection)
    functions = organization.get_all_functions()
    teams, employees = organization.get_all_teams(), organization.get_all_employees()
    exceptions = [
        EmployeeCalendarException(
            row.employee_id, date.fromisoformat(row.start_date),
            date.fromisoformat(row.end_date), row.occupation_percentage,
            reason=row.reason, exception_id=row.exception_id,
        )
        for row in organization.get_employee_calendar_exceptions()
    ]
    memberships: dict[int, list[int]] = {}
    for team, function in connection.execute('SELECT team_id,function_id FROM eppm.team_function'):
        memberships.setdefault(team, []).append(function)
    bounds = {
        identity: (start.isoformat(), end.isoformat())
        for identity, start, end in connection.execute(
            'SELECT project_id,min(start_date),max(end_date) '
            'FROM eppm.current_project_task GROUP BY project_id',
        )
    }
    pools = {pool.id: pool for pool in store.get_all_pools()}
    catalog = MappingCatalog(list(pools.values()), CapacityInputs(0, employees=employees,
                            mappings=store.get_all_mappings()))
    global_inputs = catalog.capacity_inputs()
    result = {
        identity: CapacityInputs(
            identity, pool=pools.get(identity), functions=functions, teams=teams,
            employees=employees, exceptions=exceptions,
            team_functions=memberships, project_bounds=bounds,
            direct_employee_totals=global_inputs[identity].direct_employee_totals if identity in global_inputs else {},
        )
        for identity in pool_ids
    }
    for exception in store.capacity_exceptions(pool_ids):
        result[exception.pool_id].capacity_exceptions.append(exception)
    for mapping in store.get_all_mappings():
        if mapping.pool_id in result:
            result[mapping.pool_id].mappings.append(mapping)
    for assignment in store.get_assignments(pool_ids=pool_ids):
        result[assignment['pool_id']].assignments.append(assignment)
    return result
