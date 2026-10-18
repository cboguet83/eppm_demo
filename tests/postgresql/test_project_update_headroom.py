"""Preserve project truth and security while reserving update page space."""

from pathlib import Path

import psycopg
import pytest

from app.infrastructure.postgresql.errors import MigrationError
from app.infrastructure.postgresql.migration import discover_migrations, migrate
from tests.postgresql.conftest import PostgreSQLFixture


LEDGER_QUERY = (
    'SELECT version,name,checksum,applied_at FROM eppm.schema_migration '
    'ORDER BY version'
)
PROJECT_QUERY = 'SELECT * FROM eppm.project ORDER BY id'
SHARES_QUERY = 'SELECT * FROM eppm.project_wbs ORDER BY project_id'
REVISIONS_QUERY = (
    'SELECT * FROM eppm.project_cache_revision ORDER BY project_id'
)
STORAGE_QUERY = (
    'SELECT relfilenode,reloptions FROM pg_class '
    "WHERE oid='eppm.project'::regclass"
)
HOT_QUERY = (
    'SELECT n_tup_hot_upd FROM pg_stat_xact_user_tables '
    "WHERE relid='eppm.project'::regclass"
)


def _seed(connection: psycopg.Connection) -> None:
    """Fill consecutive project pages with retained rows of realistic width."""
    connection.execute(
        "INSERT INTO eppm.project_type(name,is_general) "
        "VALUES ('General',true)"
    )
    connection.execute(
        "INSERT INTO eppm.project(name,status) "
        "SELECT 'Retained ' || lpad(value::text,5,'0') || repeat('x',90),'Draft' "
        'FROM generate_series(1,1000) value'
    )
    connection.execute("INSERT INTO eppm.wbs(code) VALUES ('RETAINED')")
    connection.execute('INSERT INTO eppm.project_wbs VALUES (1,1,40),(2,1,60)')


def _security(
    connection: psycopg.Connection,
) -> tuple[list[tuple[object, ...]], ...]:
    """Snapshot project authority and integrity independently of storage files."""
    queries = (
        "SELECT relowner,relacl::text,relrowsecurity,relforcerowsecurity "
        "FROM pg_class WHERE oid='eppm.project'::regclass",
        "SELECT polname,polcmd,polpermissive,polroles,pg_get_expr(polqual,polrelid),"
        "pg_get_expr(polwithcheck,polrelid) FROM pg_policy "
        "WHERE polrelid='eppm.project'::regclass ORDER BY polname",
        "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='eppm.project'::regclass OR confrelid='eppm.project'::regclass "
        "ORDER BY conrelid,conname",
        'SELECT indexrelid,indisvalid,indisunique,indisprimary,'
        'pg_get_indexdef(indexrelid) '
        "FROM pg_index WHERE indrelid='eppm.project'::regclass ORDER BY indexrelid",
    )
    return tuple(connection.execute(query).fetchall() for query in queries)


def test_clean_project_pages_have_room_for_hot_title_updates(
    pg_database: PostgreSQLFixture,
) -> None:
    """Keep adjacent title updates on-page without relying on delayed counters."""
    with psycopg.connect(pg_database.operator_url) as connection:
        _seed(connection)
    with psycopg.connect(pg_database.operator_url) as connection:
        options = connection.execute(
            "SELECT reloptions FROM pg_class WHERE oid='eppm.project'::regclass"
        ).fetchone()[0]
        connection.execute(
            "UPDATE eppm.project SET name='Saved ' || lpad(id::text,5,'0') "
            "|| repeat('y',90) "
            'WHERE id BETWEEN 1 AND 10'
        )
        assert connection.execute(HOT_QUERY).fetchone()[0] == 10
        assert 'fillfactor=70' in (options or [])


@pytest.mark.parametrize('rollback', [False, True], ids=['upgrade', 'rollback'])
def test_populated_upgrade_preserves_truth_authority_and_prior_history(
    empty_database: PostgreSQLFixture, tmp_path: Path, rollback: bool,
) -> None:
    """Repack old dense rows atomically and retain the ledger on reentry."""
    migrations = discover_migrations()
    repair = next(item for item in migrations if item.version == 69)
    for migration in migrations[:repair.version - 1]:
        with (tmp_path / migration.name).open('w', encoding='utf-8') as stream:
            stream.write(migration.sql)
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        _seed(connection)
        ledger = connection.execute(LEDGER_QUERY).fetchall()
        projects = connection.execute(PROJECT_QUERY).fetchall()
        shares = connection.execute(SHARES_QUERY).fetchall()
        revisions = connection.execute(REVISIONS_QUERY).fetchall()
        security = _security(connection)
        storage = connection.execute(STORAGE_QUERY).fetchone()

    if rollback:
        with (tmp_path / repair.name).open('w', encoding='utf-8') as stream:
            stream.write(repair.sql + '\nSELECT 1/0;\n')
        with pytest.raises(MigrationError):
            migrate(empty_database.operator_url, directory=tmp_path)
        with psycopg.connect(empty_database.operator_url) as connection:
            assert connection.execute(LEDGER_QUERY).fetchall() == ledger
            assert connection.execute(STORAGE_QUERY).fetchone() == storage
            assert connection.execute(PROJECT_QUERY).fetchall() == projects
            assert _security(connection) == security

    assert migrate(empty_database.operator_url) == tuple(
        item.name for item in migrations[repair.version - 1:]
    )
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute(PROJECT_QUERY).fetchall() == projects
        assert connection.execute(SHARES_QUERY).fetchall() == shares
        assert (
            connection.execute(REVISIONS_QUERY).fetchall() == revisions
        )
        assert _security(connection) == security
        assert connection.execute(LEDGER_QUERY).fetchall()[:len(ledger)] == ledger
        assert connection.execute(
            "SELECT relfilenode<>%s,'fillfactor=70'=ANY(reloptions) "
            "FROM pg_class WHERE oid='eppm.project'::regclass", (storage[0],),
        ).fetchone() == (True, True)
        connection.execute(
            "UPDATE eppm.project SET name='Saved ' || lpad(id::text,5,'0') "
            "|| repeat('y',90) "
            'WHERE id BETWEEN 1 AND 10'
        )
        assert connection.execute(HOT_QUERY).fetchone()[0] == 10
    assert migrate(empty_database.operator_url) == ()
