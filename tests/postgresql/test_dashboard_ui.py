"""Dashboard presentation, five-row paging, filters, and shared WBS budget view."""

import psycopg
from datetime import date
import json

import pytest

from streamlit.testing.v1 import AppTest

from app.main import create_finance_service
from app.application.services.access import AccessService
from app.infrastructure.postgresql.access import PostgresAccessGateway
from tests.postgresql.ui import runtime


@pytest.fixture
def business(authorized, runtime):
    """Use two native projects with one scoped editor and separate administrators."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DELETE FROM eppm.project WHERE id=3")
        connection.execute("UPDATE eppm.project SET name=CASE id WHEN 1 THEN 'Visible' ELSE 'Hidden' END")
        connection.execute("DELETE FROM eppm.app_role_assignment WHERE user_id=1 AND role='project_viewer'")
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date) "
                           "VALUES(10,1,'Visible task','2026-01-01','2026-01-05'),"
                           "(20,2,'Hidden task','2026-01-01','2026-01-05')")
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Reference pool',3)")
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) "
                           "VALUES(1,1,10,1),(1,2,20,2)")
    editor, manager = authorized.binding(1).access, authorized.binding(4).access
    service = AccessService(PostgresAccessGateway(runtime.database, runtime.key, editor.policy),
                            editor.policy, 'https://issuer.example.test', lambda: 'unused')
    return runtime, service, authorized.binding(5).access.actor, editor, manager


def screen(path, actor):
    from datetime import date
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_dashboard_service
    from app.presentation.pages.dashboard import render_dashboard
    from app.presentation.i18n import set_current_locale
    set_current_locale('en')
    service=create_dashboard_service(path,access=BusinessAccess(actor,AuthorizationPolicy(lambda:1000,SessionLimits())))
    service.today=lambda:date(2026,6,1)
    render_dashboard(service)


def table_data(app):
    return json.loads(next(item.proto.json for item in app.get('bidi_component')
                           if item.proto.id.endswith('-dashboard_project_table')))


def test_dashboard_lazy_table_and_filters_cover_all_results(business, authorized):
    path,_,_,_,manager=business
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.cursor().executemany('INSERT INTO eppm.project(id,name) VALUES(%s,%s)',[(i,f'Project {i}') for i in range(3,13)])
    app=AppTest.from_function(screen,args=(path,manager.actor),default_timeout=15).run()
    assert not app.exception
    assert not app.header
    assert table_data(app)['total']==12
    assert [row['id'] for row in table_data(app)['rows']]==list(range(1,13))
    assert app.expander[0].label=='12 matching projects'
    assert app.expander[0].proto.expanded is False
    assert not any(button.key in {'dashboard_next','dashboard_previous'} for button in app.button)
    app.multiselect(key='dashboard_flex_fields').set_value(['name']).run()
    app.multiselect(key='dashboard_filter_name').set_value(['Visible']).run()
    assert not app.exception and table_data(app)['rows'][0]['values'][0]=='Visible'
    assert table_data(app)['total']==1
    app.button(key='dashboard_clear').click().run()
    assert not app.exception and table_data(app)['total']==12


def test_dashboard_no_scope_has_no_project_values(business):
    path,access,admin,editor,_=business
    for assignment in access.assignments(admin,editor.actor.user_id):access.revoke(admin,assignment['id'])
    app=AppTest.from_function(screen,args=(path,editor.actor)).run()
    assert not app.exception and app.info
    assert table_data(app)['rows']==[]


def selection_screen(path, actor, event, selected):
    """Run the selection boundary with a recorded keyed-rerun request."""
    import streamlit as st
    from unittest.mock import patch
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_dashboard_service
    from app.presentation.pages.dashboard import _select_project

    service = create_dashboard_service(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda:1000, SessionLimits())))
    st.session_state['dashboard_project_table'] = {'project': event}
    st.session_state['dashboard_selected_project'] = selected
    with patch('app.presentation.pages.dashboard.st.rerun') as rerun:
        _select_project(service, 'current')
    st.json({'selected': st.session_state['dashboard_selected_project'],
             'reruns': [call.args[0] for call in rerun.call_args_list]})


@pytest.mark.parametrize('event,selected,expected,reruns', [
    ({'id':1,'token':'current'}, None, 1, ['dashboard']),
    ({'id':1,'token':'current'}, 1, None, ['dashboard']),
    ({'id':2,'token':'current'}, None, None, []),
    ({'id':1,'token':'stale'}, None, None, []),
    ({'id':True,'token':'current'}, None, None, []),
])
def test_project_selection_rechecks_scope_and_rejects_stale_events(business, event, selected, expected, reruns):
    path, _, _, editor, _ = business
    app = AppTest.from_function(selection_screen, args=(path,editor.actor,event,selected)).run()
    assert not app.exception
    assert json.loads(app.json[0].value) == {'selected':expected,'reruns':reruns}


def budget_screen(path, actor, project_id):
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_dashboard_service
    from app.presentation.pages.dashboard import render_project_budget
    from app.presentation.i18n import set_current_locale
    from datetime import date
    set_current_locale('en')
    service = create_dashboard_service(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))
    service.today = lambda: date(2026, 6, 1)
    render_project_budget(project_id, service)


def test_project_budget_and_dashboard_use_identical_rounded_shares_and_missing_values(business, authorized):
    path, _, _, _, manager = business
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("INSERT INTO eppm.wbs(id,code,description) VALUES(1,'A','Matched'),(2,'B','Unmatched')")
        conn.execute('INSERT INTO eppm.project_wbs VALUES(1,1,50),(1,2,100)')
    finance = create_finance_service(path, access=manager)
    finance.today = lambda: date(2026, 6, 1)
    finance.save([{'code': 'A', 'amounts': {'2026': '100.01', '2027': '0'}}],
                 base_id=None, name='Approved plan', status='Approved', year=2026)
    app = AppTest.from_function(budget_screen, args=(path, manager.actor, 1)).run()
    assert not app.exception and app.warning
    table = app.dataframe[0].value
    assert len(table) == 3 and len(table.columns) == 21
    assert table['2026'].dropna().tolist() == ['50.01', '50.01']
    assert table['2027'].dropna().tolist() == ['0.00', '0.00']
    assert table.loc[1, ['2026', '2027']].isna().all()
    assert table['2028'].isna().all()
    dashboard = AppTest.from_function(screen, args=(path, manager.actor)).run()
    assert not dashboard.exception and dashboard.warning
    assert len(dashboard.get('vega_lite_chart')) == 1
    assert any(item.proto.id.endswith('-dashboard_resource_chart') for item in dashboard.get('bidi_component'))


def test_project_budget_empty_states_and_authorization(business):
    path, _, _, editor, manager = business
    app = AppTest.from_function(budget_screen, args=(path, editor.actor, 1)).run()
    assert not app.exception and app.info and not app.dataframe
    finance = create_finance_service(path, access=manager)
    finance.today = lambda: date(2026, 6, 1)
    finance.save([{'code': 'A', 'amounts': {'2026': '100'}}],
                 base_id=None, name='Approved plan', status='Approved', year=2026)
    app.run()
    assert not app.exception and app.info and not app.dataframe
    denied = AppTest.from_function(budget_screen, args=(path, editor.actor, 2)).run()
    assert not denied.exception and denied.error and not denied.dataframe


def test_project_budget_displays_latest_approved_proposed_and_draft_with_requested_columns(business, authorized):
    path, _, _, _, manager = business
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("INSERT INTO eppm.wbs(id,code,description) VALUES(1,'A','Example')")
        conn.execute('INSERT INTO eppm.project_wbs VALUES(1,1,50)')
    finance = create_finance_service(path, access=manager)
    finance.today = lambda: date(2026, 6, 1)
    for status, amount in [('Approved','100'),('Proposed','200'),('Draft','300'),('Proposed','400')]:
        latest = finance.save([{'code':'A','amounts':{'2026':amount}}], base_id=None, name=status, status=status, year=2026)
    app = AppTest.from_function(budget_screen, args=(path, manager.actor, 1)).run()
    assert not app.exception
    assert [heading.value for heading in app.subheader] == ['Approved','Proposed','Draft']
    assert [table.value.iloc[0]['2026'] for table in app.dataframe] == ['50.00','200.00','150.00']
    assert ['Allocation (%)' in table.value for table in app.dataframe] == [False,False,True]
    finance.cancel(latest)
    app.run()
    assert app.dataframe[1].value.iloc[0]['2026'] == '100.00'
