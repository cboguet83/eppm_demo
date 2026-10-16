"""Bounded key generation retains fail-closed guards and existing cached data."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from secrets import token_bytes

import psycopg
from psycopg.types.json import Jsonb
import pytest

from app.application.exceptions import PlanningStorageError, ResourcePoolStorageError
from app.application.services.access import AuthorizationPolicy, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.infrastructure.postgresql.authorization import ActorBinding, ServerRequestSigner, configure_signing_key
from app.infrastructure.postgresql.migration import check_schema, discover_migrations, migrate
from tests.postgresql.test_derived_cache import DAY, cache
from tests.postgresql.test_pool_capacity import staffing as staffing
from tests.postgresql.conftest import PostgreSQLFixture


@pytest.mark.parametrize('kind,error', [('planning', PlanningStorageError), ('capacity', ResourcePoolStorageError)])
@pytest.mark.parametrize('source,predicate', [
    ('project_cache_revision', 'project_id=2'), ('pool_cache_revision', 'pool_id=6'),
    ('catalog_cache_revision', 'singleton'),
])
def test_selected_or_empty_reads_still_reject_missing_required_metadata(staffing, kind, error, source, predicate):
    derived = cache(staffing)
    known = [derived.read(kind, [1], DAY, False, [])[0][1]]
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute(f'DELETE FROM eppm.{source} WHERE {predicate}')

    for selected in ([1], []):
        with pytest.raises(error, match='could not be accessed'):
            derived.read(kind, selected, DAY, False, known)


def test_missing_hidden_project_revision_does_not_change_reader_cache_keys(staffing):
    derived = cache(staffing)
    before = {kind: derived.read(kind, [1], DAY, False, []) for kind in ('planning', 'capacity')}
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.project_cache_revision WHERE project_id=3')

    for kind, expected in before.items():
        assert derived.read(kind, [1], DAY, False, []) == expected


def test_cache_key_upgrade_preserves_published_entries_and_ledger_checksums(
    empty_database: PostgreSQLFixture, tmp_path: Path
) -> None:
    """Keep cached reads stable across 0024 and preserve older ledger entries."""
    migrations = discover_migrations()
    for migration in migrations[:23]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    key = token_bytes(32)
    configure_signing_key(empty_database.operator_url, key.hex())
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
        connection.execute("INSERT INTO eppm.project(name) VALUES ('Retained')")
        connection.execute("INSERT INTO eppm.resource_pool(name,capacity_fte) VALUES ('Retained pool',1)")
        connection.execute("INSERT INTO eppm.app_user(id,status,created_at,updated_at) VALUES (1,'active',900,900)")
        connection.execute("INSERT INTO eppm.app_session VALUES ('session-1',1,950,2000,980,false,false)")
        connection.execute("INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by) "
                           "VALUES (1,'project_viewer',%s,900,'test setup')", (Jsonb({'kind': 'all'}),))
        ledger = connection.execute('SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version').fetchall()
    binding = ActorBinding(BusinessAccess(Actor(1, 'session-1', 'cache-upgrade'),
                           AuthorizationPolicy(lambda: 1000, SessionLimits())), key)
    query = 'SELECT * FROM eppm.read_derived_cache(%s,ARRAY[1]::bigint[],%s,1,false,ARRAY[]::text[])'
    before = {}
    with psycopg.connect(empty_database.runtime_url) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        binding(connection)
        for kind, identity_field in (('planning', 'id'), ('capacity', 'pool_id')):
            token = connection.execute(query, (kind, date(2026, 1, 3))).fetchone()[1]
            payload = {identity_field: 1, 'assignments': [], 'contributing_resources': []}
            body = json.dumps({'kind': kind, 'day': '2026-01-03', 'version': 1,
                               'entries': [{'entity_id': 1, 'token': token, 'summary': payload, 'detail': payload}]})
            document, signature = ServerRequestSigner(key).sign(connection, 'cache.publish',
                                  {'body_hash': sha256(body.encode()).hexdigest()})
            assert connection.execute('SELECT eppm.publish_derived_cache(%s,%s,%s)', (document, signature, body)).fetchone()[0]
            before[kind] = connection.execute(query, (kind, date(2026, 1, 3))).fetchall()
            assert before[kind][0][3]

    bounded_keys = migrations[23]
    with (tmp_path / bounded_keys.name).open('wb') as stream:
        stream.write(bounded_keys.sql.encode('utf-8'))
    assert migrate(empty_database.operator_url, directory=tmp_path) == (
        bounded_keys.name,
    )

    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute('SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version').fetchall()[:23] == ledger
    with psycopg.connect(empty_database.runtime_url) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        binding(connection)
        for kind, expected in before.items():
            assert connection.execute(query, (kind, date(2026, 1, 3))).fetchall() == expected

    # Later feature migrations may legitimately invalidate derived cache tokens.
    # Check their ledger/runtime compatibility separately from the 0024 contract.
    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[24:])
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute('SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version').fetchall()[:23] == ledger
    with psycopg.connect(empty_database.runtime_url) as connection:
        check_schema(connection)
