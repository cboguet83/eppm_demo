"""Finance action callbacks retain drafts on failures and recheck authorization."""

from datetime import date
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.application.exceptions import FinanceStorageError
from app.domain.finance import BudgetRow, export_csv
from tests.test_business_transaction_security import business as business


def screen(path, actor, language='en'):
    """Use production rendering and callbacks with only the browser component replaced."""
    from datetime import date
    from unittest.mock import patch
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_finance_service
    from app.presentation.pages.finance import _action, render_finance
    from app.presentation.i18n import set_current_locale

    set_current_locale(language)
    service=create_finance_service(path,access=BusinessAccess(actor,AuthorizationPolicy(lambda:1000,SessionLimits())))
    service.today=lambda:date(2026,6,1)
    action=st.session_state.pop('next_action',None)
    if action is not None:
        previous=st.session_state['display']
        st.session_state['finance_grid']={'action':action}
        _action(service,previous['token'],previous['selected']['id'] if previous['selected'] else None)
    def capture(data,on_action):
        st.session_state['display']=data
    with patch('app.presentation.pages.finance.finance_grid',capture):
        render_finance(service)


def act(app, kind, **values):
    display=app.session_state['display']
    app.session_state['next_action']={'kind':kind,'token':display['token'],
                                     'nonce':str(app.session_state['finance_ui'].get('handled',''))+'x',**values}
    app.run()
    assert not app.exception
    return app.session_state['display']


@pytest.mark.parametrize('language,title', [('en','Finance'),('fr','Finance')])
def test_finance_callbacks_save_import_and_preserve_draft_tokens_on_errors(business,language,title):
    path,_,_,_,manager=business
    app=AppTest.from_function(screen,args=(path,manager.actor,language)).run()
    assert not app.exception and app.header[0].value==title
    display=app.session_state['display']
    assert display['rows']==[] and display['can_edit']
    first=act(app,'save',rows=[{'code':'A','amounts':{'2026':'1.01'}}],status='Draft',name='Base',year=2026)
    assert first['selected']['number']==1 and first['selected']['status']=='Draft'
    failed=act(app,'save',rows=[{'code':'A','amounts':{'2026':'-1'}}],status='Draft',name='Baseline',year=2026)
    assert failed['error'] and failed['token']==first['token']
    proposed=act(app,'save',rows=[{'code':'A','amounts':{'2026':'1.01'}}],status='Proposed',name='Base',year=2026)
    assert proposed['selected']['number']==2 and proposed['selected']['status']=='Proposed'
    imported=act(app,'import',content=export_csv((BudgetRow('B',{2026:22}),),{},2026),year=2026)
    assert imported['preview']['rows']==[{'code':'B','amounts':{'2026':'0.22'}}]
    assert imported['token']==proposed['token'] and len(imported['versions'])==2
    bad=act(app,'import',content='bad',year=2026)
    assert bad['error'] and bad['preview'] is None
    selected=act(app,'select',snapshot_id=first['selected']['id'])
    assert selected['selected']['id']==first['selected']['id']
    assert act(app,'reload')['selected']['id']==proposed['selected']['id']
    canceled=act(app,'cancel_version')
    assert canceled['selected']['status']=='Canceled' and len(canceled['versions'])==2
    assert act(app,'cancel_version')['error']
    assert act(app,'unknown')['error']


def test_finance_callbacks_reject_revoked_writes_and_handle_storage_failure(business):
    path,access,admin,editor,_=business
    grant=access.grant(admin,editor.actor.user_id,'finance_editor',{'kind':'all'})
    app=AppTest.from_function(screen,args=(path,editor.actor)).run()
    access.revoke(admin,grant)
    denied=act(app,'save',rows=[],status='Draft',name='Denied',year=2026)
    assert denied['error'] and not denied['can_edit'] and denied['selected'] is None
    with patch('app.application.services.finance.FinanceService.save',side_effect=FinanceStorageError()):
        failed=act(app,'save',rows=[],status='Draft',name='Failed',year=2026)
    assert 'storage' in failed['error']
    with patch('app.application.services.finance.FinanceService.view',side_effect=FinanceStorageError()):
        app.run()
    assert not app.exception and app.error


@pytest.mark.parametrize('payload', [None,{},[],{'token':'stale','nonce':'id'}, {'token':'0:0:2026','nonce':[]}])
def test_malformed_or_stale_finance_component_events_do_not_save(business,payload):
    path,_,_,_,manager=business
    app=AppTest.from_function(screen,args=(path,manager.actor)).run()
    app.session_state['next_action']=payload
    app.run()
    assert not app.exception
    assert app.session_state['display']['versions']==[]


def test_finance_page_handles_missing_snapshot_and_disabled_account(business):
    path,service,admin,editor,_=business
    app=AppTest.from_function(screen,args=(path,editor.actor)).run()
    app.session_state['finance_ui']={'selected':999,'generation':0}
    app.run()
    assert not app.exception and 'snapshot' in app.error[0].value
    service.set_status(admin,editor.actor.user_id,'disabled')
    app.run()
    assert not app.exception and 'not permitted' in app.error[0].value
