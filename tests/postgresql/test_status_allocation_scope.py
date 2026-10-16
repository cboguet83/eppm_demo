"""Real status-filtered page results and allocation popup scopes."""

from unittest.mock import patch

import psycopg
import pytest

from app.main import create_planning_workspace
from app.presentation.pages.planning import _load_planning_pool_payload
from tests.postgresql.ui import runtime, access, native_screen


@pytest.fixture
def status_data(authorized, runtime):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status=CASE id WHEN 1 THEN 'In Progress' WHEN 2 THEN 'Completed' ELSE 'Draft' END")
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) SELECT id,id,'Work','2025-07-01'::date,'2025-10-31'::date,(SELECT id FROM eppm.project_plan WHERE project_id=project.id AND is_current) FROM eppm.project")
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Pool A',5)")
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date,notes,project_plan_id) VALUES (1,1,2,'2025-07-01','2025-09-30','Selected Q3',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(1,1,3,'2025-10-01','2025-10-31','Selected Q4',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(1,2,10,'2025-08-01','2025-08-31','Completed Q3',(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current))")
    return runtime


def test_planning_status_defaults_reset_and_total_demand(status_data, access):
    app = native_screen('''
from app.main import create_planning_workspace
from app.presentation.pages.planning import render_planning_milestones
render_planning_milestones(create_planning_workspace(runtime, access=access))
''', status_data, access)
    with patch('app.presentation.pages.planning._interactive_gantt', return_value=None):
        app.run()
        assert not app.exception and not app.error
        assert app.session_state['dashboard_filter_status'] == ['In Progress']
        assert app.session_state['planning_status_project_ids'] == (1,)
        app.checkbox(key='dashboard_filter_status_option_In Progress').uncheck()
        app.checkbox(key='dashboard_filter_status_option_Completed').check().run()
        assert not app.exception and not app.error
        assert app.session_state['ms_multi_projects'] == [2]
        app.button(key='dashboard_clear').click().run()
        assert app.session_state['dashboard_filter_status'] == ['In Progress']
        assert app.session_state['planning_status_project_ids'] == (1,)
    workspace = create_planning_workspace(status_data, access=access)
    active, _ = _load_planning_pool_payload(workspace, workspace.revision(), (1,), {}, status_project_ids=(1,))
    all_statuses, _ = _load_planning_pool_payload(workspace, workspace.revision(), (1,), {}, status_project_ids=(1,2,3))
    assert active[0]['daily_usage']['2025-08-01'] == 2
    assert all_statuses[0]['daily_usage']['2025-08-01'] == 12
    assert all_statuses[0]['selected_projects_daily_usage']['2025-08-01'] == 2


def test_portfolio_status_defaults_and_clear_restores_active(status_data, access):
    app = native_screen('''
from app.main import create_project_workspace
from app.presentation.pages.portfolio import render_portfolio_overview
render_portfolio_overview(create_project_workspace(runtime, access=access))
''', status_data, access)
    with patch('app.presentation.pages.portfolio.portfolio_project_table', return_value=None) as table:
        app.run()
        assert not app.exception and not app.error
        assert [row['project_id'] for row in table.call_args.args[0]] == [1]
        app.checkbox(key='dashboard_filter_status_option_In Progress').uncheck()
        app.checkbox(key='dashboard_filter_status_option_Completed').check().run()
        assert [row['project_id'] for row in table.call_args.args[0]] == [2]
        app.button(key='dashboard_clear').click().run()
        assert not app.exception and not app.error
        assert app.session_state['dashboard_filter_status'] == ['In Progress']
        assert [row['project_id'] for row in table.call_args.args[0]] == [1]


@pytest.mark.parametrize('project_ids,expected', [((1,), ['Selected Q3']), ((1,2,3), ['Selected Q3','Completed Q3'])])
def test_popup_retains_clicked_quarter_and_row_project_scope(status_data, access, project_ids, expected):
    app = native_screen(f'''
from app.main import create_planning_workspace
from app.presentation.pages.planning import _pool_allocations_dialog
_pool_allocations_dialog(1,create_planning_workspace(runtime,access=access),
                         start='2025-07-01',end='2025-09-30',project_ids={project_ids!r})
''', status_data, access)
    with patch('app.presentation.components.action_table.action_table', return_value=None) as table:
        app.run()
        assert not app.exception and not app.error
        assert [row['notes'] for row in table.call_args.args[0]] == expected
