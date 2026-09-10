"""Batched capacity inputs read through one SQLite snapshot."""

from app.application.services.business_access import BusinessAccess
from datetime import date
from dataclasses import replace
import json

from app.domain.organization.models import EmployeeCalendarException
from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.models import PoolCapacityDetail
from app.domain.access.models import Permission
from app.infrastructure.repositories.access import SqliteAccessStore
from app.infrastructure.repositories.organization import SqliteOrganizationStore
from app.infrastructure.repositories.resource_pools import SqliteResourcePoolGateway


class SqliteCapacityReader:
    """Read shared catalogs once regardless of the number of requested pools."""

    def __init__(self, db_path: str | None = None, *, access: BusinessAccess) -> None:
        """Retain the database gateway without opening a connection."""
        self._gateway = SqliteResourcePoolGateway(db_path, access=access)
        self._access = access

    def visible_details(self, details: list[PoolCapacityDetail]) -> list[PoolCapacityDetail]:
        """Recheck current access and hide employee staffing from project-only readers."""
        with self._gateway.transaction() as store:
            if self._access.global_permission(SqliteAccessStore(store.connection), Permission.SHARED):
                return details
            return [replace(detail, contributing_resources=[]) for detail in details]

    def read(self, pool_ids: list[int]) -> dict[int, CapacityInputs]:
        """Collect pool, organization, and task inputs within one read transaction."""
        with self._gateway.transaction() as store:
            org = SqliteOrganizationStore(store.connection)
            functions = org.get_all_functions()
            teams = org.get_all_teams()
            employees = org.get_all_employees()
            exceptions = []
            for row in org.get_employee_calendar_exceptions():
                exceptions.append(
                    EmployeeCalendarException(
                        employee_id=row.employee_id,
                        start_date=date.fromisoformat(row.start_date),
                        end_date=date.fromisoformat(row.end_date),
                        occupation_percentage=row.occupation_percentage,
                        reason=row.reason,
                        exception_id=row.exception_id,
                    )
                )
            team_functions: dict[int, list[int]] = {}
            for team_id, function_id in store.connection.execute(
                "SELECT team_id, function_id FROM team_function",
            ):
                team_functions.setdefault(team_id, []).append(function_id)
            assignments = store.get_assignments(pool_ids=pool_ids)
            project_ids = sorted({row["project_id"] for row in assignments})
            bounds = {
                project_id: (start, end)
                for project_id, start, end in store.connection.execute(
                    "SELECT project_id, MIN(start_date), MAX(end_date) "
                    "FROM project_task WHERE project_id IN (SELECT value FROM json_each(?)) GROUP BY project_id",
                    (json.dumps(project_ids),),
                )
            }
            pools = {pool.id: pool for pool in store.get_all_pools()}
            inputs = {
                pool_id: CapacityInputs(
                    pool_id=pool_id,
                    pool=pools.get(pool_id),
                    functions=functions,
                    teams=teams,
                    employees=employees,
                    exceptions=exceptions,
                    team_functions=team_functions,
                    project_bounds=bounds,
                )
                for pool_id in pool_ids
            }
            for mapping in store.get_all_mappings():
                if mapping.pool_id in inputs:
                    inputs[mapping.pool_id].mappings.append(mapping)
            for assignment in assignments:
                if assignment["pool_id"] in inputs:
                    inputs[assignment["pool_id"]].assignments.append(assignment)
            return inputs
