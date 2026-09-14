"""Warning evaluation uses calendar days without mutating project schedules."""

from copy import deepcopy

import pytest

from app.domain.planning.project_dependencies import evaluate_project_dependencies, normalize_project_dependency, positive_identity


@pytest.mark.parametrize('kind,gap', [('FS', -5), ('FF', 5), ('SS', 9), ('SF', 19)])
@pytest.mark.parametrize('offset,violated', [(-1, False), (0, False), (1, True)])
def test_all_link_types_compare_inclusive_calendar_day_boundaries(kind, gap, offset, violated):
    rows = [dict(link_type=kind, lag_days=gap + offset, start_date='2026-01-10', end_date='2026-01-20',
                 pred_start_date='2026-01-01', pred_end_date='2026-01-15',
                 predecessor_task_name=None, predecessor_project_name='Predecessor')]
    before = deepcopy(rows)
    result = evaluate_project_dependencies(rows)[0]
    assert result['is_evaluable'] and result['is_violated'] is violated
    assert bool(result['violation_text']) is violated
    assert rows == before


@pytest.mark.parametrize('kind', ['FS', 'FF', 'SS', 'SF'])
def test_undated_endpoints_are_unevaluable_and_extreme_lags_do_not_overflow(kind):
    row = dict(link_type=kind, lag_days=2**31 - 1, start_date=None, end_date=None,
               pred_start_date='0001-01-01', pred_end_date='9999-12-31',
               predecessor_task_name='Step', predecessor_project_name='Project')
    assert not evaluate_project_dependencies([row])[0]['is_evaluable']
    row.update(start_date='2026-01-01', end_date='2026-01-01')
    assert evaluate_project_dependencies([row])[0]['is_violated']
    row['lag_days'] = -(2**31)
    assert not evaluate_project_dependencies([row])[0]['is_violated']


@pytest.mark.parametrize('value', [None, True, 0, -1, 1.5, 'invalid', [], '0', 2**63])
def test_invalid_dependency_identities_are_rejected(value):
    with pytest.raises(ValueError):
        positive_identity(value)


@pytest.mark.parametrize('changes', [dict(predecessor_task_id=3), dict(predecessor_project_id=None),
                                     dict(predecessor_project_id=1), dict(link_type='invalid'),
                                     dict(lag_days=True), dict(lag_days=1.5), dict(lag_days=2**31), dict(id=0)])
def test_invalid_dependency_rows_are_rejected(changes):
    with pytest.raises(ValueError):
        normalize_project_dependency(1, dict(predecessor_project_id=2, predecessor_task_id=None) | changes)


def test_normalization_defaults_to_fs_zero_and_preserves_signed_lag_and_identity():
    assert normalize_project_dependency(1, dict(predecessor_project_id='2')) == dict(
        predecessor_project_id=2, predecessor_task_id=None, link_type='FS', lag_days=0)
    assert normalize_project_dependency(1, dict(predecessor_task_id='4', id='8', lag_days=-3)) == dict(
        predecessor_project_id=None, predecessor_task_id=4, link_type='FS', lag_days=-3, id=8)


@pytest.mark.parametrize('identity', [True, 1.5, None, [], 2**63])
def test_project_component_actions_validate_identity_before_scalar_coercion(identity):
    from app.presentation.components.planning_events import validate_event

    with pytest.raises(ValueError):
        validate_event({'action': 'save_project_dependencies', 'project_id': identity})
