"""Publish Python staffing totals atomically without widening employee access."""

from dataclasses import asdict, replace
from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from app.domain.organization.models import EmployeeCalendarException
from app.domain.resources.capacity import calculate_staffing


def refresh_staffing(connection: psycopg.Connection) -> None:
    """Refresh live staffing using an authorized shared writer or migration owner."""
    from app.infrastructure.postgresql.organization import PostgresOrganizationStore
    from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore

    catalog = PostgresResourcePoolStore(connection).mapping_catalog()
    exceptions = [EmployeeCalendarException(row.employee_id, date.fromisoformat(row.start_date),
        date.fromisoformat(row.end_date), row.occupation_percentage)
        for row in PostgresOrganizationStore(connection).get_employee_calendar_exceptions()]
    records = []
    for identity, inputs in catalog.capacity_inputs().items():
        staffing = calculate_staffing(replace(inputs, exceptions=exceptions))
        records.append((identity, staffing.assigned_capacity_fte, staffing.has_assigned_resources,
                        Jsonb(staffing.daily_assigned_capacity), Jsonb([asdict(item) for item in staffing.contributing_resources])))
    with connection.cursor() as cursor:
        cursor.executemany('''INSERT INTO eppm.pool_staffing_projection VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT(pool_id) DO UPDATE SET assigned_capacity_fte=excluded.assigned_capacity_fte,
            has_assigned_resources=excluded.has_assigned_resources,daily_assigned_capacity=excluded.daily_assigned_capacity,
            contributing_resources=excluded.contributing_resources
            WHERE (pool_staffing_projection.assigned_capacity_fte,pool_staffing_projection.has_assigned_resources,
                pool_staffing_projection.daily_assigned_capacity,pool_staffing_projection.contributing_resources)
                IS DISTINCT FROM (excluded.assigned_capacity_fte,excluded.has_assigned_resources,
                    excluded.daily_assigned_capacity,excluded.contributing_resources)''', records)
