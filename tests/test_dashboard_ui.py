"""Dashboard presentation, five-row paging, filters, and shared WBS budget view."""

from contextlib import closing
from datetime import date
import json

from streamlit.testing.v1 import AppTest

from app.infrastructure.database.connection import get_db
from app.main import create_finance_service
from tests.test_business_transaction_security import business as business


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


def test_dashboard_lazy_table_and_filters_cover_all_results(business):
    path,_,_,_,manager=business
    with closing(get_db(path)) as conn,conn:
        conn.executemany('INSERT INTO project(id,name) VALUES(?,?)',[(i,f'Project {i}') for i in range(3,13)])
    app=AppTest.from_function(screen,args=(path,manager.actor),default_timeout=15).run()
    assert not app.exception
    assert not app.header
    assert table_data(app)['total']==12
    assert [row['id'] for row in table_data(app)['rows']]==list(range(1,13))
    assert app.expander[0].label=='12 matching projects'
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


def test_project_budget_and_dashboard_use_identical_rounded_shares_and_missing_values(business):
    path, _, _, _, manager = business
    with closing(get_db(path)) as conn, conn:
        conn.execute("INSERT INTO wbs(id,code,description) VALUES(1,'A','Matched'),(2,'B','Unmatched')")
        conn.execute('INSERT INTO project_wbs VALUES(1,1,50),(1,2,100)')
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


def test_project_budget_displays_latest_approved_proposed_and_draft_with_requested_columns(business):
    path, _, _, _, manager = business
    with closing(get_db(path)) as conn, conn:
        conn.execute("INSERT INTO wbs(id,code,description) VALUES(1,'A','Example')")
        conn.execute('INSERT INTO project_wbs VALUES(1,1,50)')
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
