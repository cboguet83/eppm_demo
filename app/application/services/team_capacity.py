"""Explicit team membership and employee-only capacity projections."""

from dataclasses import dataclass, field
from datetime import date

from app.application.ports.organization import CalendarExceptionRow
from app.domain.organization.models import Employee, OrgFunction, Team


@dataclass(frozen=True)
class TeamMember:
    """One mapped function occupant, or a vacant function with zero capacity."""

    function_id: int
    function_name: str
    employee_id: int | None
    employee_name: str
    current_fte: float


@dataclass
class TeamCapacity:
    """Deduplicated direct membership, effective capacity and applicable exceptions."""

    members: list[TeamMember] = field(default_factory=list)
    exceptions: list[CalendarExceptionRow] = field(default_factory=list)
    current_fte: float = 0
    has_employees: bool = False
    has_future_exceptions: bool = False


@dataclass
class TeamOverview:
    """Consistent catalog and calculated team details for shared administration."""

    teams: list[Team]
    functions: list[OrgFunction]
    capacities: dict[int, TeamCapacity]
    pool_mappings: list[dict]


def team_capacities(teams: list[Team], functions: list[OrgFunction], employees: list[Employee],
                    memberships: dict[int, list[int]], exceptions: list[CalendarExceptionRow],
                    today: date) -> dict[int, TeamCapacity]:
    """Count each live employee once, without implicit managers or child teams."""
    functions_by_id = {item.function_id: item for item in functions if not item.deleted_flag}
    occupants: dict[int, dict[int, Employee]] = {}
    calendars: dict[int, list[CalendarExceptionRow]] = {}
    for employee in employees:
        if not employee.deleted_flag and employee.function_id in functions_by_id:
            occupants.setdefault(employee.function_id, {})[employee.employee_id] = employee
    for exception in exceptions:
        calendars.setdefault(exception.employee_id, []).append(exception)
    result = {}
    day = today.isoformat()
    for team in teams:
        detail = TeamCapacity()
        result[team.team_id] = detail
        if team.deleted_flag:
            continue
        for identity in sorted(set(memberships.get(team.team_id, [])) & functions_by_id.keys()):
            function = functions_by_id[identity]
            people = occupants.get(identity, {})
            if not people:
                detail.members.append(TeamMember(identity, function.name, None, '', 0))
            for employee in people.values():
                periods = calendars.get(employee.employee_id, [])
                occupation = next((period.occupation_percentage for period in periods
                    if period.start_date <= day <= period.end_date), employee.occupation_percentage)
                detail.members.append(TeamMember(identity, function.name, employee.employee_id,
                    f'{employee.firstname.strip()} {employee.lastname.strip()}', round(occupation / 100, 3)))
                detail.exceptions.extend(periods)
        detail.current_fte = round(sum(member.current_fte for member in detail.members), 3)
        detail.has_employees = any(member.employee_id is not None for member in detail.members)
        detail.has_future_exceptions = any(period.end_date >= day for period in detail.exceptions)
    return result
