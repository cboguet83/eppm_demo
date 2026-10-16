"""Preserve active assignment membership, invoker security and upgrade history."""

from pathlib import Path

import psycopg

from app.infrastructure.postgresql.migration import discover_migrations, migrate
from app.infrastructure.postgresql.seed_plan import ensure_operator_plan
from tests.postgresql.conftest import PostgreSQLFixture


def test_assignment_lookup_upgrade_preserves_membership_records_and_security(
    empty_database: PostgreSQLFixture, tmp_path: Path,
) -> None:
    """Keep NULL/live task membership and exclude deleted/inactive task rows."""
    migrations = discover_migrations()
    repair = next(item for item in migrations if item.version == 68)
    for migration in migrations[:repair.version - 1]:
        with (tmp_path / migration.name).open('w', encoding='utf-8') as stream:
            stream.write(migration.sql)
    migrate(empty_database.operator_url, directory=tmp_path)
    ledger_query = 'SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version'
    metadata = (
        'SELECT relowner,relacl::text,reloptions FROM pg_class '
        "WHERE oid='eppm.current_resource_pool_assignment'::regclass"
    )
    membership_query = 'SELECT id,task_id FROM eppm.current_resource_pool_assignment ORDER BY id'
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
        connection.execute("INSERT INTO eppm.project(id,name) VALUES (1,'Retained owner')")
        plan_id = ensure_operator_plan(connection, 1)
        inactive = connection.execute(
            "INSERT INTO eppm.project_plan(project_id,version,name,status_id,is_current,author,created_at) "
            "VALUES (1,2,'Inactive',1,false,'test setup',CURRENT_TIMESTAMP) RETURNING id"
        ).fetchone()[0]
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (1,'Retained pool',1)")
        connection.execute(
            "INSERT INTO eppm.project_task(id,project_id,project_plan_id,task_name,start_date,end_date,is_deleted) "
            "VALUES (1,1,%s,'Live','2026-01-01','2026-01-02',false),"
            "(2,1,%s,'Deleted','2026-01-01','2026-01-02',true),"
            "(3,1,%s,'Inactive','2026-01-01','2026-01-02',false)",
            (plan_id, plan_id, inactive),
        )
        connection.execute(
            'INSERT INTO eppm.resource_pool_assignment '
            '(id,pool_id,project_id,project_plan_id,task_id,fte_assigned) '
            'VALUES (1,1,1,%s,NULL,.1),(2,1,1,%s,1,.2),'
            '(3,1,1,%s,2,.3),(4,1,1,%s,3,.4)',
            (plan_id, plan_id, plan_id, inactive),
        )
        ledger = connection.execute(ledger_query).fetchall()
        security = connection.execute(metadata).fetchone()
        records = connection.execute('SELECT * FROM eppm.resource_pool_assignment ORDER BY id').fetchall()
        expected = connection.execute(membership_query).fetchall()
        assert expected == [(1, None), (2, 1)]

    assert migrate(empty_database.operator_url) == tuple(
        item.name for item in migrations[repair.version - 1:]
    )

    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute(membership_query).fetchall() == expected
        assert connection.execute(metadata).fetchone() == security
        assert connection.execute(ledger_query).fetchall()[:len(ledger)] == ledger
        assert connection.execute('SELECT * FROM eppm.resource_pool_assignment ORDER BY id').fetchall() == records
