"""Preserve cache tokens, records, and security across selected-source repair."""

from datetime import date
from pathlib import Path

import psycopg
import pytest

from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.migration import discover_migrations, migrate
from tests.postgresql.conftest import AuthorizedFixture, PostgreSQLFixture


@pytest.mark.parametrize('user_id', [1, 2, 4])
@pytest.mark.parametrize('deleted_endpoint', [False, True])
def test_selected_cache_matches_bulk_with_revised_and_hidden_endpoints(
    authorized: AuthorizedFixture, user_id: int, deleted_endpoint: bool,
) -> None:
    """Resolve active logical endpoints while preserving scoped bulk tokens."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        alternate = connection.execute(
            "INSERT INTO eppm.project_plan "
            "(project_id,version,name,status_id,is_current,author,created_at) "
            "VALUES (2,2,'Old revision',1,false,'test setup',CURRENT_TIMESTAMP) RETURNING id"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO eppm.project_task "
            "(id,project_id,project_plan_id,task_name,start_date,end_date) "
            "SELECT id,id,(SELECT id FROM eppm.project_plan "
            "WHERE project_id=p.id AND is_current),'Endpoint',"
            "'2026-01-01','2026-01-03' FROM eppm.project p"
        )
        connection.execute(
            'UPDATE eppm.project_task SET project_plan_id=%s WHERE id=2',
            (alternate,),
        )
        connection.execute(
            "INSERT INTO eppm.project_task "
            "(id,project_id,project_plan_id,stable_task_id,task_name,"
            "start_date,end_date,is_deleted) "
            "SELECT 20,2,id,2,'Active endpoint','2026-01-01','2026-01-03',%s "
            "FROM eppm.project_plan WHERE project_id=2 AND is_current",
            (deleted_endpoint,),
        )
        connection.execute(
            'UPDATE eppm.project_task SET predecessor_id=2 WHERE id=1'
        )
        connection.execute(
            'INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) '
            'VALUES (1,2),(1,3)'
        )
        connection.execute(
            'INSERT INTO eppm.project_dependency '
            '(project_id,project_plan_id,predecessor_task_id) '
            'SELECT 1,id,2 FROM eppm.project_plan '
            'WHERE project_id=1 AND is_current'
        )

    def inspect(connection: psycopg.Connection) -> None:
        query = (
            'SELECT * FROM eppm.read_derived_cache('
            "'planning',%s::bigint[],%s,1,false,ARRAY[]::text[])"
        )
        bulk = connection.execute(query, (None, date(2026, 1, 3))).fetchall()
        for selected in ([1], [2], [3], [1, 2, 3, 999], []):
            actual = connection.execute(
                query, (selected, date(2026, 1, 3)),
            ).fetchall()
            assert actual == [row for row in bulk if row[0] in selected]
        expected_ids = {1, 2} if user_id == 1 else {3} if user_id == 2 else {1, 2, 3}
        assert {row[0] for row in bulk} == expected_ids

    run_business(
        authorized.database, authorized.key,
        authorized.binding(user_id).access, inspect,
    )


def test_selected_cache_upgrade_preserves_records_ledger_and_security(
    empty_database: PostgreSQLFixture, tmp_path: Path,
) -> None:
    """Install the ordered query repair without altering data or helper grants."""
    migrations = discover_migrations()
    repair = next(
        item for item in migrations
        if item.name == '0066_selected_cache_sources.sql'
    )
    for migration in migrations[:repair.version - 1]:
        with (tmp_path / migration.name).open('w', encoding='utf-8') as stream:
            stream.write(migration.sql)
    migrate(empty_database.operator_url, directory=tmp_path)
    metadata = (
        'SELECT proowner,prosecdef,provolatile,proacl::text,proconfig '
        "FROM pg_proc WHERE oid='eppm.current_cache_keys(text,bigint[])'"
        '::regprocedure'
    )
    ledger_query = (
        'SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version'
    )
    with psycopg.connect(empty_database.operator_url) as connection:
        security = connection.execute(metadata).fetchone()
        ledger = connection.execute(ledger_query).fetchall()
        connection.execute(
            "INSERT INTO eppm.project_type(name,is_general) "
            "VALUES ('General',true)"
        )
        connection.execute(
            "INSERT INTO eppm.project(name) VALUES ('Retained cache owner')"
        )
        records = connection.execute('SELECT * FROM eppm.project').fetchall()

    assert migrate(empty_database.operator_url) == tuple(
        item.name for item in migrations[repair.version - 1:]
    )

    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute(metadata).fetchone() == security
        assert connection.execute(ledger_query).fetchall()[:len(ledger)] == ledger
        assert connection.execute('SELECT * FROM eppm.project').fetchall() == records
    with psycopg.connect(empty_database.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT * FROM eppm.current_cache_keys('planning',ARRAY[1]::bigint[])"
            )
