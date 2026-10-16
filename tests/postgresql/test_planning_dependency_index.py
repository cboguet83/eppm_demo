"""Install stable endpoint indexes without changing stored planning records."""

from pathlib import Path

import psycopg

from app.infrastructure.postgresql.migration import discover_migrations, migrate
from app.infrastructure.postgresql.seed_plan import ensure_operator_plan
from tests.postgresql.conftest import PostgreSQLFixture


def test_dependency_index_upgrade_preserves_prior_ledger_and_tasks(
    empty_database: PostgreSQLFixture, tmp_path: Path,
) -> None:
    """Add the lookup index to an existing schema without rewriting records."""
    migrations = discover_migrations()
    index = next(item for item in migrations if item.version == 67)
    for migration in migrations[:index.version - 1]:
        with (tmp_path / migration.name).open('w', encoding='utf-8') as stream:
            stream.write(migration.sql)
    migrate(empty_database.operator_url, directory=tmp_path)
    ledger_query = 'SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version'
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
        connection.execute("INSERT INTO eppm.project(id,name) VALUES (1,'Retained owner')")
        plan_id = ensure_operator_plan(connection, 1)
        connection.execute(
            "INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date) "
            "VALUES (1,%s,'Retained task','2026-01-01','2026-01-02')", (plan_id,)
        )
        tasks = connection.execute('SELECT * FROM eppm.project_task').fetchall()
        ledger = connection.execute(ledger_query).fetchall()

    assert migrate(empty_database.operator_url) == tuple(
        migration.name for migration in migrations[index.version - 1:]
    )

    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute('SELECT * FROM eppm.project_task').fetchall() == tasks
        assert connection.execute(ledger_query).fetchall()[:len(ledger)] == ledger
        definition = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='eppm' "
            "AND indexname='project_task_stable_reference'"
        ).fetchone()[0]
        assert '(stable_task_id)' in definition
        assert 'WHERE (stable_task_id IS NOT NULL)' in definition
