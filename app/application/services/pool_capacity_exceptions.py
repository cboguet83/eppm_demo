"""Effective pool exception sources, using the capacity engine's deduplicated staff."""

from dataclasses import dataclass

from app.application.ports.organization import CalendarExceptionRow
from app.domain.resources.models import PoolCapacityDetail, PoolCapacityException


@dataclass(frozen=True)
class PoolExceptionBreakdown:
    """One applicable exception; positive FTE reduction means lost capacity."""

    pool_id: int
    pool_name: str
    source: str
    resource_name: str
    mapping_source: str
    start_date: str
    end_date: str
    reduction_fte: float
    occupation_percentage: float | None
    reason: str


def capacity_exception_breakdown(
    details: list[PoolCapacityDetail], pool_exceptions: list[PoolCapacityException],
    employee_exceptions: list[CalendarExceptionRow],
) -> list[PoolExceptionBreakdown]:
    """Select pool reductions or mapped employee overrides, never both.

    Staffing contributions already resolve explicit team/function membership,
    exclude deleted resources and apply direct-mapping precedence. Each employee
    exception therefore appears once per pool, even with several mapping paths.
    """
    by_employee: dict[int, list[CalendarExceptionRow]] = {}
    for item in employee_exceptions:
        by_employee.setdefault(item.employee_id, []).append(item)
    by_pool: dict[int, list[PoolCapacityException]] = {}
    for item in pool_exceptions:
        by_pool.setdefault(item.pool_id, []).append(item)
    rows = []
    for detail in details:
        if not detail.has_assigned_resources:
            rows.extend(PoolExceptionBreakdown(detail.pool_id, detail.pool_name, 'Pool', detail.pool_name,
                        '', item.start_date, item.end_date, item.reduction_fte, None, item.reason)
                        for item in by_pool.get(detail.pool_id, []))
            continue
        for person in detail.contributing_resources:
            for item in by_employee.get(person.employee_id, []):
                reduction = (person.nominal_fte - item.occupation_percentage / 100) * person.effective_allocation_pct / 100
                rows.append(PoolExceptionBreakdown(detail.pool_id, detail.pool_name, 'Employee',
                            person.employee_name or person.resource_name, person.source_name,
                            item.start_date, item.end_date, round(reduction, 3), item.occupation_percentage, item.reason))
    return sorted(rows, key=lambda row: (row.pool_name.casefold(), row.start_date, row.resource_name))
