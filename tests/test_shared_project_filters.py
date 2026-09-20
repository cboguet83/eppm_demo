"""Shared selections survive widget cleanup and reset consistently across pages."""

from app.presentation.components import project_filter_panel as panel


def test_widget_cleanup_keeps_shared_filters_and_restores_independent_copies(monkeypatch):
    state = {'dashboard_filter_status': ['Completed'], 'dashboard_filter_pool': ['7'],
             'dashboard_filter_service': ['4'], 'dashboard_flex_fields': ['name'],
             'dashboard_filter_name': ['Example'], 'dashboard_match': 'All',
             'dashboard_filter_status_all': False, 'dashboard_filter_status_search': 'Com',
             'ms_multi_projects': [1], 'active_resource_pool_filter': {'pool_id': 7}}
    monkeypatch.setattr(panel.st, 'session_state', state)
    panel.reset_page()
    assert 'dashboard_filter_status_all' not in state['shared_project_filters']
    assert 'dashboard_filter_status_search' not in state['shared_project_filters']
    assert 'ms_multi_projects' not in state and 'active_resource_pool_filter' not in state
    for key in list(state):
        if panel._filter_key(key):
            del state[key]
    panel.restore_filters()
    assert state['dashboard_filter_status'] == ['Completed']
    assert state['dashboard_filter_pool'] == ['7']
    assert state['dashboard_filter_service'] == ['4']
    assert state['dashboard_flex_fields'] == ['name']
    assert state['dashboard_filter_name'] == ['Example']
    assert state['dashboard_match'] == 'All'
    state['dashboard_filter_status'].append('Draft')
    assert state['shared_project_filters']['dashboard_filter_status'] == ['Completed']
    panel.clear_filters()
    assert state['dashboard_filter_status'] == ['In Progress']
    assert 'dashboard_filter_pool' not in state['shared_project_filters']
