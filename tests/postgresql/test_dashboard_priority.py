"""Priority filters preserve dashboard status defaults and authorized scope."""

import psycopg
from streamlit.testing.v1 import AppTest

from tests.postgresql.test_dashboard import service
from tests.postgresql.test_dashboard_ui import business, runtime, screen


def test_priority_filters_and_choices_are_scoped_and_revised(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project SET strategic_priority_id=CASE id WHEN 1 THEN 1 WHEN 3 THEN 2 END')
    dashboard = service(authorized)
    catalog = dashboard.catalog()
    assert dashboard.choices(catalog, {}, 'strategic_priority', False) == ['', '1']
    assert [row['id'] for row in dashboard.filtered(catalog, {'strategic_priority': ['1']}, False)] == [1]
    assert [row['id'] for row in dashboard.filtered(catalog, {'strategic_priority': ['']}, False)] == [2]
    assert dashboard.filtered(catalog, {'strategic_priority': ['2']}, False) == []
    before = dashboard.revision()
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project SET strategic_priority_id=4 WHERE id=1')
    assert dashboard.revision() != before


def test_dashboard_priority_control_defaults_to_all_and_reset_keeps_in_progress(business):
    path, _, _, editor, _ = business
    app = AppTest.from_function(screen, args=(path, editor.actor), default_timeout=30).run()
    assert not app.exception
    assert app.session_state['dashboard_filter_strategic_priority'] == []
    assert app.session_state['dashboard_filter_status'] == ['In Progress']
    app.button(key='dashboard_clear').click().run()
    assert not app.exception
    assert app.session_state['dashboard_filter_strategic_priority'] == []
    assert app.session_state['dashboard_filter_status'] == ['In Progress']
