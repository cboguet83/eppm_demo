"""Pool tree transport validation and bounded presentation traversal."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.domain.resources.hierarchy import PoolHierarchy
from app.domain.resources.models import ResourcePool
from app.presentation.components.resource_pool_tree import resource_pool_tree


@pytest.mark.parametrize('event', [None, [], {}, {'id': True, 'action': 'edit'},
    {'id': '1', 'action': 'edit'}, {'id': 99, 'action': 'create'}, {'id': 1, 'action': 'delete'}])
def test_tree_rejects_malformed_or_stale_client_events(event):
    tree = PoolHierarchy([ResourcePool('Pool', id=1)])
    component = Mock(return_value=SimpleNamespace(action=event))
    with patch('streamlit.components.v2.component', return_value=component):
        assert resource_pool_tree(tree, {}, 1) is None


@pytest.mark.parametrize('action', ['select', 'edit', 'create', 'gantt', 'map'])
def test_tree_accepts_actions_for_existing_pools_and_orders_children(action):
    tree = PoolHierarchy([ResourcePool('Zulu', id=1, hierarchy_type_id=7), ResourcePool('Child', id=2, parent_pool_id=1),
                          ResourcePool('Alpha', id=3)])
    component = Mock(return_value=SimpleNamespace(action={'id': 2, 'action': action}))
    with patch('streamlit.components.v2.component', return_value=component):
        assert resource_pool_tree(tree, {1: 4, 2: 4}, 1, assigned_capacities={1: 2.5, 2: 2.5},
                                  pool_types={1: 'Human'}, hierarchy_types={7: 'Department'}) == {'id': 2, 'action': action}
    rows = component.call_args.kwargs['data']['rows']
    assert [(row['id'], row['depth'], row['container']) for row in rows] == [(3, 0, False), (1, 0, True), (2, 1, False)]
    assert rows[1]['capacity'] == rows[2]['capacity'] == '4.00'
    assert rows[1]['assigned_capacity'] == rows[2]['assigned_capacity'] == '2.50'
    assert rows[1]['pool_type'] == 'Human'
    assert rows[1]['hierarchy_type'] == 'Department'
    assert rows[2]['hierarchy_type'] == '—'


def test_tree_presentation_handles_hierarchies_deeper_than_python_recursion_limit():
    tree = PoolHierarchy([ResourcePool(str(identity), id=identity, parent_pool_id=identity - 1 or None)
                          for identity in range(1, 1501)])
    component = Mock(return_value=SimpleNamespace(action=None))
    with patch('streamlit.components.v2.component', return_value=component):
        resource_pool_tree(tree, {}, 1)
    rows = component.call_args.kwargs['data']['rows']
    assert len(rows) == 1500
    assert rows[-1]['depth'] == 1499


def test_mapping_column_distinguishes_direct_targets_from_container_children():
    tree = PoolHierarchy([ResourcePool('Root', id=1),
                          *(ResourcePool(str(identity), id=identity, parent_pool_id=1) for identity in range(2, 6))])
    component = Mock(return_value=SimpleNamespace(action=None))
    with patch('streamlit.components.v2.component', return_value=component):
        resource_pool_tree(tree, {}, 1, mapping_types={2: {'employee'}, 3: {'team'}, 4: {'employee', 'team'}})
    rows = component.call_args.kwargs['data']['rows']
    assert {row['id']: row['mappings'] for row in rows} == {
        1: '', 2: '✓', 3: '✓', 4: '✓', 5: ''}


def test_client_cannot_open_mapping_action_for_container():
    tree = PoolHierarchy([ResourcePool('Root', id=1), ResourcePool('Leaf', id=2, parent_pool_id=1)])
    component = Mock(return_value=SimpleNamespace(action={'id': 1, 'action': 'map'}))
    with patch('streamlit.components.v2.component', return_value=component):
        assert resource_pool_tree(tree, {}, 1) is None


def test_empty_tree_accepts_root_creation():
    component = Mock(return_value=SimpleNamespace(action={'id': 0, 'action': 'create_root'}))
    with patch('streamlit.components.v2.component', return_value=component):
        assert resource_pool_tree(PoolHierarchy([]), {}, 0) == {'id': 0, 'action': 'create_root'}


@pytest.mark.parametrize('nominal,available,peak,warning', [(20, 3, 8, True), (2, 10, 8, False), (2, 8, 8, False)])
def test_peak_warning_compares_with_peak_date_capacity(nominal, available, peak, warning):
    component = Mock(return_value=SimpleNamespace(action=None))
    with patch('streamlit.components.v2.component', return_value=component):
        resource_pool_tree(PoolHierarchy([ResourcePool('Pool', id=1)]), {1: nominal}, 1,
                           peak_demands={1: peak}, peak_capacities={1: available})
    assert component.call_args.kwargs['data']['rows'][0]['peak_exceeded'] is warning


@pytest.mark.parametrize('current,peak,expected', [
    (2, 2, (False, False)), (1, 0, (False, False)),
    (3, 1, (True, False)), (1, 3, (False, True)), (3, 3, (True, True)),
])
def test_capacity_warnings_compare_each_value_strictly_to_pool_capacity(current, peak, expected):
    tree = PoolHierarchy([ResourcePool('Root', id=1), ResourcePool('Leaf', id=2, parent_pool_id=1)])
    component = Mock(return_value=SimpleNamespace(action=None))
    with patch('streamlit.components.v2.component', return_value=component):
        resource_pool_tree(tree, {1: 2, 2: 2}, 1,
                           assigned_capacities={1: current, 2: current},
                           peak_demands={1: peak, 2: peak})
    for row in component.call_args.kwargs['data']['rows']:
        assert (row['current_exceeded'], row['peak_exceeded']) == expected
