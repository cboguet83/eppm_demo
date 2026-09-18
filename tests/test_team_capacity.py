"""Team capacity uses explicit live membership and inclusive employee calendars."""

from datetime import date

from app.application.ports.organization import CalendarExceptionRow
from app.application.services.team_capacity import team_capacities
from app.domain.organization.models import Employee, OrgFunction, Team


def test_team_capacity_deduplicates_and_never_infers_membership_or_vacant_fte():
    teams = [Team('Parent', 1, manager_function_id=1), Team('Child', 2, parent_team_id=1), Team('Deleted', 3, deleted_flag=True)]
    functions = [OrgFunction('Occupied', 1, function_id=1), OrgFunction('Vacant', 1, function_id=2),
                 OrgFunction('Deleted', 1, function_id=3, deleted_flag=True)]
    employees = [Employee('Ada', 'One', 'a@t.test', employee_id=1, function_id=1, occupation_percentage=80),
                 Employee('Gone', 'Two', 'b@t.test', employee_id=2, function_id=1, deleted_flag=True),
                 Employee('Gone function', 'Three', 'c@t.test', employee_id=3, function_id=3)]
    exceptions = [CalendarExceptionRow(1, 1, 'Ada', 'One', '2026-01-01', '2026-01-03', 20, 'Current'),
                  CalendarExceptionRow(2, 1, 'Ada', 'One', '2025-01-01', '2025-01-02', 0, 'Past')]
    result = team_capacities(teams, functions, employees, {2: [1, 1, 2, 3], 3: [1]}, exceptions, date(2026, 1, 3))
    assert result[1].current_fte == 0 and not result[1].has_employees
    assert result[2].current_fte == .2 and result[2].has_employees and result[2].has_future_exceptions
    assert len(result[2].members) == 2 and len(result[2].exceptions) == 2
    assert result[2].members[1].employee_id is None and result[2].members[1].current_fte == 0
    assert not result[3].members and not result[3].has_future_exceptions
    next_day = team_capacities(teams, functions, employees, {2: [1]}, exceptions, date(2026, 1, 4))
    assert next_day[2].current_fte == .8 and not next_day[2].has_future_exceptions
