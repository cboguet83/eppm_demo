"""CSV syntax validation and lossless resource-pool catalog serialization."""

import pytest

from app.application.services.resource_pool_csv import export_pools, parse_pools
from app.domain.resources.models import ResourcePool


def test_csv_round_trip_keeps_flags_references_unicode_and_quoted_descriptions():
    pools = [ResourcePool('Équipe, "A"', id=12, description='Line one\nLine two; detail',
                          capacity_fte=2.75, parent_pool_id=9, hierarchy_type_id=3,
                          pool_type_id=2, deleted_flag=True), ResourcePool('Unspecified')]
    assert parse_pools(export_pools(pools).encode('utf-8-sig')) == pools
    assert 'exception' not in export_pools(pools).partition('\n')[0]


def test_minimal_csv_and_semicolon_files_use_documented_defaults():
    assert parse_pools(b'name\nNew pool\n') == [ResourcePool('New pool')]
    assert parse_pools(b'name;capacity_fte;deleted_flag\nNew;0;1\n') == [
        ResourcePool('New', capacity_fte=0, deleted_flag=True)]


@pytest.mark.parametrize('content,message', [
    (b'name\n', 'no pool records'),
    (b'pool_id\n2\n', 'name column'),
    (b'name,name\nA,B\n', 'duplicate column'),
    (b'name\n\xff', 'UTF-8'),
    (b'name,capacity_fte\nPool,-2\n', 'Row 2'),
    (b'name,capacity_fte\nPool,nan\n', 'Row 2'),
    (b'name,capacity_fte\nPool,infinity\n', 'Row 2'),
    (b'name,capacity_fte\nPool,abc\n', 'capacity_fte'),
    (b'name,deleted_flag\nPool,maybe\n', 'deleted_flag'),
    (b'name,pool_id\nPool,-1\n', 'pool_id'),
    (b'name,pool_id\nPool,1.5\n', 'pool_id'),
    (b'name,parent_pool_id\nPool,abc\n', 'parent_pool_id'),
    (b'name,pool_id\nA,1\nB,1\n', 'Duplicate pool_id'),
    (b'name,description\nPool\n', 'number of values'),
    (b'name\nPool,extra\n', 'number of values'),
    (b'name\n"unterminated', 'Invalid CSV'),
    (b'"unterminated', 'Invalid CSV header'),
    (b'name,description\n ,empty\n', 'cannot be empty'),
])
def test_invalid_csv_fails_with_actionable_error(content, message):
    with pytest.raises(ValueError, match=message):
        parse_pools(content)
