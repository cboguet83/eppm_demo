"""Scoped cache fingerprints, transactional invalidation and independent writers."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from app.application.exceptions import ProjectStorageError
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, Actor
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.migration import migrate
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.revisions import read_revisions, snapshot
from app.shared.config.database import DatabaseConfig
from tests.postgresql.conftest import database_url


# Explicit business-source contract, independent of migration implementation.
# Authentication housekeeping and Finance history do not invalidate these views.
DISPLAY_SOURCE_TABLES = frozenset({
    'hierarchy_type', 'hierarchy_type_translation', 'wbs', 'project_wbs',
    'employee', 'employee_calendar_exception', 'function', 'function_type',
    'project', 'project_contact', 'project_event_type', 'project_event_type_translation',
    'project_link', 'project_log_event', 'project_property_value', 'project_property_value_item',
    'project_role', 'project_role_translation', 'project_tag', 'project_task', 'project_type',
    'project_type_property', 'project_type_property_default', 'project_type_property_default_item',
    'project_type_property_rule', 'resource_pool', 'resource_pool_assignment',
    'resource_pool_group', 'resource_pool_group_member', 'resource_pool_mapping',
    'resource_pool_tag', 'schema_groups', 'schema_param_options', 'schema_parameter_translation',
    'schema_parameters', 'tag_dictionnary', 'tag_group', 'task_dependencies', 'task_tag',
    'team', 'team_function',
})


def revisions(authorized, user_id=1):
    return snapshot(authorized.database, authorized.key, authorized.binding(user_id).access)


@pytest.fixture
def sources(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (1,'First',1),(2,'Second',2)")
        connection.execute("""INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date)
            VALUES (1,1,'One','2026-01-01','2026-01-05'),(2,2,'Two','2026-01-01','2026-01-06'),
                   (3,3,'Hidden','2026-01-01','2026-01-07')""")
        connection.execute('INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES (1,1,1,0.5),(1,3,3,5),(2,2,2,1)')
    return authorized


def test_all_business_sources_are_tracked_but_authentication_and_cache_tables_are_excluded(sources):
    with psycopg.connect(sources.setup.operator_url) as connection:
        tracked = {row[0] for row in connection.execute("""SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='eppm' AND t.tgname='cache_revision'""")}
    assert tracked == DISPLAY_SOURCE_TABLES
    for table in ('project_cache_revision', 'pool_cache_revision', 'catalog_cache_revision'):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sources.query(sql.SQL('SELECT * FROM eppm.{}').format(sql.Identifier(table)), user_id=4)


def test_fingerprints_are_stable_opaque_and_isolated_by_actor_scope_and_session(sources):
    before = revisions(sources)
    assert before == revisions(sources) and before.scope == (1, 2)
    assert set(before.project_tokens()) == {1, 2} and set(before.pool_tokens()) == {1, 2}
    assert dict(before.pool_sources) == {1: (1,), 2: (2,)}
    assert len(before.token()) == 64 and before.token().isalnum()
    assert 'session-1' not in before.token() + repr(before)
    assert revisions(sources, 2).scope == (3,)
    assert revisions(sources, 4).token() != before.token()
    sources.query('SELECT eppm.session_activity()', write=True)
    assert revisions(sources) == before
    with psycopg.connect(sources.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.app_session VALUES ('other-session',1,950,2000,980,false,false)")
    other_access = BusinessAccess(Actor(1, 'other-session', 'request'), sources.binding(1).access.policy)
    assert snapshot(sources.database, sources.key, other_access).token() != before.token()
    with pytest.raises(AccessDenied):
        revisions(sources, 3)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sources.database.run(lambda connection: connection.execute('SELECT eppm.display_cache_revisions()').fetchall())


def test_project_and_pool_keys_ignore_unrelated_and_hidden_demand_updates(sources):
    before, admin = revisions(sources), revisions(sources, 4)
    sources.query('UPDATE eppm.resource_pool_assignment SET fte_assigned=fte_assigned+1 WHERE project_id=3', user_id=4, write=True)
    assert revisions(sources) == before
    assert revisions(sources, 4).pool_tokens()[1] != admin.pool_tokens()[1]
    sources.query("UPDATE eppm.project_task SET end_date='2026-01-08' WHERE id=2", user_id=4, write=True)
    after = revisions(sources)
    assert after.catalog == before.catalog and after.pools == before.pools
    assert after.project_tokens()[1] == before.project_tokens()[1]
    assert after.project_tokens()[2] != before.project_tokens()[2]
    assert after.pool_tokens()[1] == before.pool_tokens()[1]
    assert after.pool_tokens()[2] != before.pool_tokens()[2]
    sources.query('UPDATE eppm.resource_pool SET capacity_fte=3 WHERE id=1', user_id=4, write=True)
    final = revisions(sources)
    assert final.pool_tokens()[1] != after.pool_tokens()[1]
    assert final.pool_tokens()[2] == after.pool_tokens()[2] and final.projects == after.projects


def test_predecessor_fingerprints_use_only_visible_endpoints_and_terminate_cycles(sources):
    sources.query('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES (1,2),(2,1),(1,3)', user_id=4, write=True)
    sources.query('UPDATE eppm.project_task SET predecessor_id=3 WHERE id=1', user_id=4, write=True)
    before = revisions(sources)
    assert dict(before.dependencies) == {1: (2,), 2: (1,)}
    sources.query("UPDATE eppm.project_task SET task_name='Still hidden' WHERE id=3", user_id=4, write=True)
    assert revisions(sources) == before
    sources.query("UPDATE eppm.project_task SET end_date='2026-01-08' WHERE id=2", user_id=4, write=True)
    after = revisions(sources)
    assert after.projects[0] == before.projects[0]
    assert after.project_tokens()[1] != before.project_tokens()[1]
    assert after.pool_tokens()[1] == before.pool_tokens()[1]


def test_moving_the_last_visible_assignment_changes_both_pool_source_sets_and_project_revisions(sources):
    before = revisions(sources)
    sources.query('''UPDATE eppm.resource_pool_assignment SET pool_id=2,project_id=2,task_id=2
        WHERE project_id=1''', user_id=4, write=True)
    after = revisions(sources)
    assert dict(after.pool_sources) == {1: (), 2: (2,)}
    assert after.pools == before.pools and after.catalog == before.catalog
    assert all(after.project_tokens()[identity] != before.project_tokens()[identity] for identity in (1, 2))
    assert all(after.pool_tokens()[identity] != before.pool_tokens()[identity] for identity in (1, 2))


def test_scope_grants_and_permission_changes_are_part_of_the_same_revision_snapshot(sources):
    before = revisions(sources)
    grant = sources.query("SELECT eppm.admin_grant(1,'project_viewer',%s)",
                          (Jsonb({'kind': 'projects', 'project_ids': [3]}),), user_id=5, write=True)[0][0]
    after = revisions(sources)
    assert after.scope == (1, 2, 3) and after.security > before.security and after.token() != before.token()
    sources.query('SELECT eppm.admin_revoke(%s)', (grant,), user_id=5, write=True)
    final = revisions(sources)
    assert final.scope == before.scope and final.token() != before.token()
    sources.query("SELECT eppm.admin_grant(1,'project_editor',%s)",
                  (Jsonb({'kind': 'projects', 'project_ids': [2]}),), user_id=5, write=True)
    permissions = revisions(sources)
    assert permissions.scope == final.scope and permissions.projects == final.projects
    assert permissions.security > final.security and permissions.token() != final.token()


def test_property_based_membership_changes_are_detected_without_an_access_grant_change(sources):
    with psycopg.connect(sources.setup.operator_url) as connection:
        type_id = connection.execute("INSERT INTO eppm.project_type(name) VALUES ('Selected') RETURNING id").fetchone()[0]
    scope = {'kind': 'properties', 'conditions': [{'property_id': 'project_type_id', 'operator': 'eq', 'value_ids': [type_id]}]}
    sources.query("SELECT eppm.admin_grant(1,'project_viewer',%s)", (Jsonb(scope),), user_id=5, write=True)
    before = revisions(sources)
    assert before.scope == (1, 2)
    sources.query('UPDATE eppm.project SET project_type_id=%s WHERE id=3', (type_id,), user_id=4, write=True)
    after = revisions(sources)
    assert after.scope == (1, 2, 3) and after.security == before.security
    assert after.token() != before.token() and dict(after.pool_sources)[1] == (1, 3)
    sources.query('UPDATE eppm.project SET project_type_id=1 WHERE id=3', user_id=4, write=True)
    assert revisions(sources).scope == (1, 2)


def test_generation_ids_prevent_reuse_after_project_or_pool_recreation(sources):
    before = revisions(sources, 4)
    with psycopg.connect(sources.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.resource_pool_assignment WHERE project_id=2')
        connection.execute('DELETE FROM eppm.project_task WHERE project_id=2')
        connection.execute('DELETE FROM eppm.project WHERE id=2')
        connection.execute("INSERT INTO eppm.project(id,name) VALUES (2,'Read only')")
        connection.execute('DELETE FROM eppm.resource_pool WHERE id=2')
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (2,'Second',2)")
    after = revisions(sources, 4)
    assert after.projects[1][1] != before.projects[1][1] and after.pools[1][1] != before.pools[1][1]
    assert after.project_tokens()[2] != before.project_tokens()[2] and after.pool_tokens()[2] != before.pool_tokens()[2]


def test_rollback_restores_source_and_revision_changes_together(sources):
    before = revisions(sources)
    with psycopg.connect(sources.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='Rolled back' WHERE id=1")
        connection.execute("UPDATE eppm.resource_pool SET name='Rolled back' WHERE id=1")
        connection.execute("INSERT INTO eppm.tag_group(tag_group_name) VALUES ('Rolled back')")
        connection.rollback()
    assert revisions(sources) == before
    with psycopg.connect(sources.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.tag_group(tag_group_name) VALUES ('Committed')")
    assert revisions(sources).catalog == before.catalog + 1


def test_independent_project_writer_does_not_wait_on_another_project_or_shared_pool_revision(sources):
    with psycopg.connect(sources.setup.operator_url) as held:
        held.execute('SELECT project_id FROM eppm.project_cache_revision WHERE project_id=1 FOR UPDATE')
        held.execute('SELECT pool_id FROM eppm.pool_cache_revision WHERE pool_id=2 FOR UPDATE')
        held.execute('SELECT singleton FROM eppm.catalog_cache_revision FOR UPDATE')
        def edit(connection):
            connection.execute("SET LOCAL lock_timeout='200ms'")
            connection.execute("UPDATE eppm.project_task SET task_name='Independent' WHERE id=2")
        sources.database.run(edit, write=True, bind=sources.binding(4))
    assert sources.query('SELECT task_name FROM eppm.project_task WHERE id=2') == [('Independent',)]


def test_revision_and_membership_read_remains_consistent_during_a_concurrent_edit(sources):
    ready, changed = Event(), Event()
    access = sources.binding(1).access
    def read():
        def operation(connection):
            before = read_revisions(connection, access)
            ready.set()
            assert changed.wait(timeout=10)
            return before, read_revisions(connection, access)
        return run_business(sources.database, sources.key, access, operation)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(read)
        assert ready.wait(timeout=10)
        try:
            sources.query("UPDATE eppm.project SET name='Changed' WHERE id=1", write=True)
        finally:
            changed.set()
        before, after = future.result()
    assert before == after and revisions(sources) != before


@pytest.mark.parametrize('table,where', [('project_cache_revision', 'project_id=1'), ('pool_cache_revision', 'pool_id=1'),
                                      ('catalog_cache_revision', 'singleton'), ('database_identity', 'singleton')])
def test_missing_revision_metadata_fails_closed_without_a_cache_key(sources, table, where):
    with psycopg.connect(sources.setup.operator_url) as connection:
        connection.execute(sql.SQL('DELETE FROM eppm.{} WHERE ').format(sql.Identifier(table)) + sql.SQL(where))
    with pytest.raises(ProjectStorageError, match='could not be accessed'):
        revisions(sources)


def test_copied_epoch_in_a_recreated_database_cannot_reuse_the_previous_incarnation(sources):
    before = revisions(sources)
    name = 'eppm_test_' + uuid4().hex
    maintenance = database_url(sources.setup.operator_url, 'postgres')
    operator_url = database_url(sources.setup.operator_url, name)
    with psycopg.connect(maintenance, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        migrate(operator_url)
        configure_signing_key(operator_url, sources.key.hex())
        with psycopg.connect(operator_url) as connection:
            connection.execute('UPDATE eppm.database_identity SET epoch=%s', (before.identity[0],))
            connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
            connection.execute("INSERT INTO eppm.project(id,name) VALUES (1,'Editable'),(2,'Read only')")
            connection.execute("INSERT INTO eppm.app_user(id,status,created_at,updated_at) VALUES (1,'active',900,900)")
            connection.execute("INSERT INTO eppm.app_session VALUES ('session-1',1,950,2000,980,false,false)")
            connection.execute("""INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
                VALUES (1,'project_viewer','{"kind":"all"}',900,'test setup')""")
        database = Database(DatabaseConfig(database_url(sources.setup.runtime_url, name), pool_min=1, pool_max=2))
        database.open()
        try:
            restored = snapshot(database, sources.key, sources.binding(1).access)
        finally:
            database.close()
        assert restored.identity[0] == before.identity[0] and restored.identity[1] != before.identity[1]
        assert restored.identity[2:] == before.identity[2:] and restored.access_key != before.access_key
    finally:
        # Only the fresh random database created by this test is removed.
        with psycopg.connect(maintenance, autocommit=True) as connection:
            connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
