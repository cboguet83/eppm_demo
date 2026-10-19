"""Validate direct-link component inputs before numeric coercion or writes."""

import pytest

from app.presentation.components.planning_events import validate_event


@pytest.mark.parametrize('changes', [
    {'project_id': True}, {'task_id': True}, {'predecessor_task_id': False},
    {'predecessor_project_id': 2}, {'predecessor_task_id': None},
    {'lag_days': True}, {'lag_days': 1}, {'link_type': 'bad'},
    {'source_tokens': {}}, {'source_tokens': []},
    {'source_tokens': {'1': False}}, {'source_tokens': {'bad': 'token'}},
])
def test_direct_link_boundary_rejects_malformed_input(changes: dict[str, object]) -> None:
    """Bad identities, endpoints, types, and sources fail before dispatch."""
    event = dict(action='create_dependency', project_id=1, task_id=3,
                 predecessor_task_id=4, predecessor_project_id=None,
                 link_type='FS', lag_days=0, source_tokens={'1': 'source'})
    with pytest.raises(ValueError):
        validate_event(event | changes)


def test_direct_link_boundary_normalizes_fingerprint_owners() -> None:
    """JSON dictionary keys become validated project IDs without exposing values."""
    result = validate_event(dict(action='create_dependency', project_id='1', task_id=None,
                                 predecessor_task_id=None, predecessor_project_id='2',
                                 link_type='SF', lag_days=0, source_tokens={'1': 'a', '2': 'b'}))
    assert result['source_tokens'] == {1: 'a', 2: 'b'}
    assert result['predecessor_project_id'] == 2
