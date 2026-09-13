"""Details prepare reads before rendering and never reuse them across requests."""

from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.application.services.projects import ProjectService
from app.application.services.portfolio import PortfolioService
from tests.postgresql.test_portfolio_project_modal import business, dashboard_business, runtime
from tests.test_fragment_reruns import FragmentRun
from tests.test_fragment_reruns import project_details_fragment_app


def test_project_details_read_once_per_render_and_refresh_reads_on_tab_interaction(business):
    from app.presentation.pages import portfolio

    path, _, _, editor, _ = business
    reads = []
    original = ProjectService.get_project_by_id
    catalog_reads = []
    original_catalog = PortfolioService.get_catalog

    def read(owner, project_id):
        reads.append(project_id)
        return original(owner, project_id)

    def catalog(owner, **kwargs):
        catalog_reads.append(1)
        return original_catalog(owner, **kwargs)

    app = AppTest.from_function(project_details_fragment_app, args=(path, editor.actor))
    run = FragmentRun('project_details_tabs_1')
    with patch.object(ProjectService, 'get_project_by_id', read), patch.object(PortfolioService, 'get_catalog', catalog):
        run.run(app)
    assert reads == [1, 1]
    assert catalog_reads == [1]
    assert portfolio._detail_content.get() is None
    run.assert_isolated()
    assert app.button(key='btn_edit_details_1')


def test_changed_template_invalidates_reference_cache_on_the_next_tab_request(business):
    from app.main import create_project_type_service

    path, _, _, _, manager = business
    types = create_project_type_service(path, access=manager)
    app = AppTest.from_function(project_details_fragment_app, args=(path, manager.actor))
    reads = []
    original = PortfolioService.get_catalog

    def catalog(owner, **kwargs):
        reads.append(1)
        return original(owner, **kwargs)

    run = FragmentRun('project_details_tabs_1', lambda: types.save_rule(1, 'DEPT', mandatory_override=True))
    with patch.object(PortfolioService, 'get_catalog', catalog):
        run.run(app)
    assert reads == [1, 1]
    assert any('Department *:' in element.value for element in app.get('html'))
    run.assert_isolated()
    assert app.button(key='btn_edit_details_1')


def test_project_schema_read_finishes_before_title_and_summary_are_emitted(business):
    import streamlit as st

    path, _, _, editor, _ = business
    events = []
    read, title = PortfolioService.get_catalog, st.subheader

    def catalog(owner, **kwargs):
        result = read(owner, **kwargs)
        events.append('catalog')
        return result

    def heading(*args, **kwargs):
        events.append('heading')
        return title(*args, **kwargs)

    with patch.object(PortfolioService, 'get_catalog', catalog), patch.object(st, 'subheader', heading):
        app = AppTest.from_function(project_details_fragment_app, args=(path, editor.actor)).run()
    assert not app.exception
    assert events == ['catalog', 'heading']
    summary = [element for element in app.get('html') if '<dl ' in element.value]
    assert len(summary) == 1
    assert '<dt>Status</dt>' in summary[0].value


def test_failed_preparation_does_not_emit_a_partial_summary_or_retain_content(business):
    from app.presentation.pages import portfolio
    from app.application.exceptions import ProjectStorageError

    path, _, _, editor, _ = business
    with patch.object(PortfolioService, 'get_catalog', side_effect=ProjectStorageError('Reference read failed')):
        app = AppTest.from_function(project_details_fragment_app, args=(path, editor.actor)).run()
    assert not app.exception
    assert app.error[0].value == 'Reference read failed'
    assert not app.subheader and not app.button and not app.tabs
    assert portfolio._detail_content.get() is None
