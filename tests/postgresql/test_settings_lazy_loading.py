"""Real PostgreSQL-backed Settings reruns keep hidden sections lazy."""

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.application.services.business_access import BusinessAccess
from app.domain.resources.models import PoolAssignment, ResourcePool
from app.main import create_resource_pool_service
from app.runtime import RuntimeResources
from tests.postgresql.ui import runtime as runtime, access as access


def settings_app(resources: RuntimeResources, access: BusinessAccess) -> None:
    """Render the real Settings workspace with the fixture's native actor."""
    from app.main import create_settings_workspace
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.settings import render_settings_view

    set_current_locale('en')
    render_settings_view(create_settings_workspace(resources, access=access))


@pytest.fixture
def pool_ids(runtime, access):
    service = create_resource_pool_service(runtime, access=access)
    assigned = service.create_pool(ResourcePool(name='Assigned pool', capacity_fte=3.0))
    service.create_assignment(PoolAssignment(assigned, 1, 1.0))
    empty = service.create_pool(ResourcePool(name='Pool without demand', capacity_fte=3.0))
    return assigned, empty


def test_resource_pool_details_keep_controls_without_daily_chart(runtime, access, pool_ids):
    """Pools with and without demand retain details but never render a chart."""
    assigned_pool_id, empty_pool_id = pool_ids
    app = AppTest.from_function(settings_app, args=(runtime, access))
    app.session_state['settings_active_tab'] = 'resource_pools'
    with patch('app.presentation.pages.settings.st.plotly_chart',
               side_effect=AssertionError('Removed daily chart rendered')):
        for pool_id in (assigned_pool_id, empty_pool_id):
            app.session_state['target_resource_pool_id'] = pool_id
            app.run()
            assert not app.exception
            assert app.session_state['sb_selected_resource_pool'] == pool_id
            assert len(app.metric) == 5
            assert app.success or app.error, 'Capacity status remains visible'
            button_keys = {button.key for button in app.button}
            assert f'btn_edit_pool_{pool_id}' in button_keys
            assert f'btn_add_map_{pool_id}' in button_keys
            markup = '\n'.join(item.value for item in app.markdown)
            assert 'Daily Capacity vs. Assigned Demand Timeline' not in markup
            assert 'Active Allocations on Projects & Tasks' in markup
            assert 'Deduplicated Assigned Capacity Breakdown' in markup
            if pool_id == assigned_pool_id:
                assert app.get('bidi_component'), 'Allocations expose row action buttons'
                assert f'btn_unassign_{pool_id}' not in button_keys


def test_pool_data_is_loaded_only_in_pool_tab_and_selection_survives_rerun(runtime, access, pool_ids):
    app = AppTest.from_function(settings_app, args=(runtime, access))
    with patch('app.application.services.pool_capacity.PoolCapacityService.get_summaries',
               side_effect=AssertionError('Hidden pools loaded')):
        app.run()
        assert not app.exception
    app.session_state['settings_active_tab'] = 'resource_pools'
    with patch('app.application.services.tags.TagService.get_task_tags_page',
               side_effect=AssertionError('Hidden task tab loaded')):
        app.run()
        assert not app.exception
        assert 'Resource Pools' in app.session_state['settings_tab_selection']
        app.run()
        assert not app.exception
        assert 'Resource Pools' in app.session_state['settings_tab_selection']
