"""Load fixture expectations retain old image evidence and current seed coverage."""

import pytest

from tests.performance.deployment import COUNTS, validate_seed_counts


def test_seed_fixture_accepts_legacy_and_current_layouts():
    validate_seed_counts(COUNTS)
    validate_seed_counts(COUNTS | {'resource_pool': 33, 'resource_pool_group': 7,
                                 'allocated_projects': 9001, 'allocated_pools': 33})


@pytest.mark.parametrize('change', [{'allocated_projects': 9000}, {'allocated_pools': 32},
                                  {'resource_pool': 103}, {'resource_pool_assignment': 9000}])
def test_seed_fixture_rejects_incomplete_current_workload(change):
    counts = COUNTS | {'resource_pool': 33, 'resource_pool_group': 7,
                      'allocated_projects': 9001, 'allocated_pools': 33}
    with pytest.raises(AssertionError):
        validate_seed_counts(counts | change)
