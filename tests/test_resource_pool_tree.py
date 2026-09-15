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


@pytest.mark.parametrize('action', ['select', 'edit', 'create'])
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
