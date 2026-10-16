"""Storage-independent dashboard reset regression checks."""

from app.presentation.pages import dashboard
import pytest
from streamlit.testing.v1 import AppTest


def pool_screen(count):
    """Render warning labels without database dependencies."""
    from app.presentation.pages.dashboard import _pool_warning
    _pool_warning([{'id': index, 'name': f'Pool {index}'} for index in range(count)])


@pytest.mark.parametrize('count,label', [(0, 'Overassigned Pool'), (1, 'Overassigned Pool'),
                                        (2, 'Overassigned Pools')])
def test_pool_warning_uses_singular_for_zero_and_one(count, label):
    app = AppTest.from_function(pool_screen, args=(count,)).run()
    assert not app.exception
    assert any(f'<p>{count} {label}</p>' in item.proto.body for item in app.get('html'))


def test_clear_restores_default_status_and_removes_other_filters(monkeypatch):
    state = {'dashboard_filter_status': ['Completed'], 'dashboard_filter_pool': ['7'],
             'dashboard_filter_chart_pool': 7,
             'dashboard_flex_fields': ['name'], 'dashboard_match': 'All',
             'dashboard_selected_project': 4, 'dashboard_offset': 10}
    monkeypatch.setattr(dashboard.st, 'session_state', state)
    dashboard._clear()
    assert state.pop('shared_project_filters') == {
        'dashboard_filter_status': ['In Progress'], 'dashboard_flex_fields': [], 'dashboard_match': 'Any'}
    assert state.pop('portfolio_filter_reset') == 1
    assert state.pop('planning_filter_reset') == 1
    assert state == {'dashboard_filter_status': ['In Progress'],
                     'dashboard_flex_fields': [], 'dashboard_match': 'Any',
                     'dashboard_offset': 0}
