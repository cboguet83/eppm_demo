"""Whole-view cache keys avoid graph hydration while retaining invalidation scope."""

import json

import psycopg
import pytest

from app.application.exceptions import ProjectStorageError
from app.domain.access.models import AccessDenied
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.migration import check_schema, discover_migrations, migrate
from app.infrastructure.postgresql.portfolio import PostgresPortfolioReader
from app.infrastructure.postgresql.revisions import snapshot
from tests.postgresql.business import business
from tests.postgresql.test_revision_plans import revision_workload


@pytest.mark.parametrize('statement,changed', [
    ("UPDATE eppm.project_task SET task_name='Hidden edit' WHERE id=20", False),
    ("UPDATE eppm.resource_pool_assignment SET fte_assigned=3 WHERE id=2", False),
    ("UPDATE eppm.task_dependencies SET lag_days=1 WHERE task_id=10", True),
    ("DELETE FROM eppm.task_dependencies WHERE task_id=10", True),
    ("UPDATE eppm.project_task SET predecessor_id=NULL WHERE id=10", True),
    ("UPDATE eppm.resource_pool SET name='Updated pool' WHERE id=1", True),
    ("UPDATE eppm.resource_pool_assignment SET fte_assigned=2 WHERE id=1", True),
])
def test_compact_revision_preserves_visible_dependency_and_demand_invalidation(pg_database, business, statement, changed):
    path, _, _, editor, _ = business
    reader = PostgresPortfolioReader(path.database, path.key, access=editor)
    before = reader.revision()
    previous_sources = snapshot(path.database, path.key, editor)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute(statement)
    assert (snapshot(path.database, path.key, editor) != previous_sources) is changed
    assert (reader.revision() != before) is changed


def test_compact_revision_is_actor_bound_and_rejects_revoked_read_access(pg_database, business):
    path, access, admin, editor, manager = business
    reader = PostgresPortfolioReader(path.database, path.key, access=editor)
    assert reader.revision() != PostgresPortfolioReader(path.database, path.key, access=manager).revision()
    with psycopg.connect(pg_database.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute('SELECT eppm.portfolio_cache_revision()')
    assignment = access.assignments(admin, editor.actor.user_id)[0]
    access.revoke(admin, assignment['id'])
    with pytest.raises(AccessDenied):
        reader.revision()


def test_compact_revision_tracks_current_property_scope_and_can_return_to_the_original_view(pg_database, business):
    path, access, admin, editor, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        property_id = connection.execute("SELECT 'enum:'||id FROM eppm.app_scope_property WHERE param_id='DEPT'").fetchone()[0]
        option_id = connection.execute("SELECT id FROM eppm.schema_param_options WHERE param_id='DEPT' AND option_value='Finance'").fetchone()[0]
    access.grant(admin, editor.actor.user_id, 'project_viewer', {'kind': 'properties', 'conditions': [
        {'property_id': property_id, 'operator': 'eq', 'value_ids': [option_id]}]})
    reader = PostgresPortfolioReader(path.database, path.key, access=editor)
    before = reader.revision()
    assert reader.get_metrics().total_projects == 1
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES(2,'DEPT','text','Finance')")
    expanded = reader.revision()
    assert expanded != before and reader.get_metrics().total_projects == 2
    other_actor = PostgresPortfolioReader(path.database, path.key, access=manager).revision()
    assert other_actor[1] == expanded[1] and other_actor[0] != expanded[0]
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("UPDATE eppm.project_property_value SET text_value='Delivery' WHERE project_id=2")
    assert reader.revision() == before
    assert reader.get_metrics().total_projects == 1


@pytest.mark.parametrize('table', ['project_cache_revision', 'pool_cache_revision'])
def test_compact_revision_fails_closed_when_source_generations_are_missing(pg_database, business, table):
    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute('DELETE FROM eppm.' + table)
    with pytest.raises(ProjectStorageError):
        PostgresPortfolioReader(path.database, path.key, access=editor).revision()


def test_compact_revision_upgrade_preserves_applied_history_and_calculation_fingerprints(empty_database, tmp_path):
    migrations = discover_migrations()
    for migration in migrations[:26]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    metadata = "SELECT prosrc,proowner,prosecdef,provolatile,proacl::text FROM pg_proc WHERE oid='eppm.display_cache_revisions()'::regprocedure"
    ledger = 'SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version'
    with psycopg.connect(empty_database.operator_url) as connection:
        before_function = connection.execute(metadata).fetchone()
        before_ledger = connection.execute(ledger).fetchall()

    # Isolate 0027 before later relational-plan/soft-deletion rewrites.
    (tmp_path / migrations[26].name).write_bytes(migrations[26].sql.encode('utf-8'))
    assert migrate(empty_database.operator_url, directory=tmp_path) == (migrations[26].name,)
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute(metadata).fetchone() == before_function
        assert connection.execute(ledger).fetchall()[:26] == before_ledger
    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[27:])
    with psycopg.connect(empty_database.runtime_url) as connection:
        check_schema(connection)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute('SELECT eppm.portfolio_cache_revision()')


def test_compact_revision_payload_and_query_work_remain_bounded_on_a_large_graph(revision_workload, record_property):
    fixture = revision_workload

    def inspect(connection):
        plans = {}
        for name in ('display_cache_revisions', 'portfolio_cache_revision'):
            query = 'SELECT eppm.' + name + '()'
            plans[name] = connection.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query).fetchone()[0][0]
        payload = connection.execute('SELECT eppm.portfolio_cache_revision()').fetchone()[0]
        return plans, payload

    plans, payload = run_business(fixture.database, fixture.key, fixture.binding(4).access, inspect)
    blocks = {name: plan['Plan']['Shared Hit Blocks'] + plan['Plan']['Shared Read Blocks']
              for name, plan in plans.items()}
    for name, plan in plans.items():
        record_property(name + '_ms', plan['Execution Time'])
        record_property(name + '_blocks', blocks[name])
    payload_bytes = len(json.dumps(payload).encode())
    record_property('portfolio_cache_revision_payload_bytes', payload_bytes)
    assert payload_bytes <= 256
    assert blocks['portfolio_cache_revision'] < blocks['display_cache_revisions'] / 2, blocks
    reader = PostgresPortfolioReader(fixture.database, fixture.key, access=fixture.binding(4).access)
    before = reader.revision()
    assert before[:2] == tuple(payload)
    # The reader appends financial transaction/snapshot/cancellation revisions.
    assert before[2:] == ('d41d8cd98f00b204e9800998ecf8427e', 0, 0)
    fixture.query("UPDATE eppm.project SET name='Changed final project' WHERE id=10001", user_id=4, write=True)
    after = reader.revision()
    assert after[0] == before[0] and after[1] != before[1]
    fixture.query("UPDATE eppm.resource_pool SET name='Changed final pool' WHERE id=100", user_id=4, write=True)
    assert reader.revision() != after
