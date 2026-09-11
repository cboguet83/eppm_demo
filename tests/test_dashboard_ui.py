"""Dashboard presentation, five-row paging, filters, and shared WBS budget view."""

from contextlib import closing
from datetime import date

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


def test_dashboard_five_row_pagination_and_filters_cover_all_results(business):
    path,_,_,_,manager=business
    with closing(get_db(path)) as conn,conn:
        conn.executemany('INSERT INTO project(id,name) VALUES(?,?)',[(i,f'Project {i}') for i in range(3,13)])
    app=AppTest.from_function(screen,args=(path,manager.actor),default_timeout=15).run()
    assert not app.exception
    assert app.header[0].value=='Dashboard'
    assert len(app.dataframe[0].value)==5
    app.button(key='dashboard_next').click().run()
    assert not app.exception and len(app.dataframe[0].value)==5
    app.multiselect(key='dashboard_flex_fields').set_value(['name']).run()
    app.multiselect(key='dashboard_filter_name').set_value(['Visible']).run()
    assert not app.exception and app.dataframe[0].value['Project'].tolist()==['Visible']
    app.button(key='dashboard_clear').click().run()
    assert not app.exception and len(app.dataframe[0].value)==5


def test_dashboard_no_scope_has_no_project_values(business):
    path,access,admin,editor,_=business
    for assignment in access.assignments(admin,editor.actor.user_id):access.revoke(admin,assignment['id'])
    app=AppTest.from_function(screen,args=(path,editor.actor)).run()
    assert not app.exception and app.info
    assert not app.dataframe[0].value.size


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
    assert len(table) == 3 and len(table.columns) == 22
    assert table['2026'].dropna().tolist() == ['50.01', '50.01']
    assert table['2027'].dropna().tolist() == ['0.00', '0.00']
    assert table.loc[1, ['2026', '2027']].isna().all()
    assert table['2028'].isna().all()
    dashboard = AppTest.from_function(screen, args=(path, manager.actor)).run()
    assert not dashboard.exception and dashboard.warning
    assert len(dashboard.get('vega_lite_chart')) == 2


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
