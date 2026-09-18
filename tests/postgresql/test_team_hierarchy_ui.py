"""Team hierarchy page metrics and selected resource breakdowns."""

from datetime import date, timedelta
from unittest.mock import patch

from app.domain.organization.models import Team, OrgFunction, Employee, EmployeeCalendarException
from app.domain.resources.models import ResourcePool, PoolMapping
from app.main import create_organization_service, create_resource_pool_service
from tests.postgresql.test_organization_ui import database, access
from tests.postgresql.ui import native_screen


SCREEN = '''
from app.main import create_organization_service
from app.presentation.pages.teams import render_teams
render_teams(create_organization_service(runtime, access=access))
'''


def test_team_page_counts_employee_capacity_and_shows_selected_breakdowns(database, access):
    org = create_organization_service(database, access=access)
    pools = create_resource_pool_service(database, access=access)
    function = org.create_function(OrgFunction('Engineer', 1))
    team = org.create_team(Team('Delivery'), function_ids=[function])
    employee = org.create_employee(Employee('Ada', 'One', 'a@ui.test', function_id=function))
    org.create_employee_calendar_exception(EmployeeCalendarException(employee, date.today()-timedelta(days=1),
                                                                     date.today()+timedelta(days=1), 50))
    pool = pools.create_pool(ResourcePool('Engineering'))
    pools.create_mapping(PoolMapping(pool, 'team', team, 75))
    hidden = org.create_team(Team('Hidden'))
    org.delete_team(hidden)
    with patch('app.presentation.pages.teams.team_tree', return_value=None) as tree:
        app = native_screen(SCREEN, database, access).run()
    assert not app.exception and not app.error
    assert {item.label: item.value for item in app.metric} == {
        'Total Teams': '1', 'Teams with mapped employees': '1', 'Teams with future capacity exceptions': '1'}
    assert tree.call_args.args[0].capacities[team].current_fte == .5
    assert [frame.value.columns.tolist() for frame in app.dataframe] == [
        ['Function', 'Employee', 'Current FTE'],
        ['Function', 'Employee', 'Source', 'Date start', 'Date stop', 'Employee FTE during exception', 'Reason'],
        ['Pool', 'Allocation (%)']]
    assert app.dataframe[0].value.iloc[0]['Current FTE'] == .5
    assert app.dataframe[2].value.iloc[0]['Allocation (%)'] == 75
    with patch('app.presentation.pages.teams.team_tree', return_value=None) as tree:
        app.checkbox(key='team_show_deleted').set_value(True).run()
    assert len(tree.call_args.args[0].teams) == 2 and app.metric[0].value == '1'
