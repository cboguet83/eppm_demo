"""Verify ordered WBS helper hardening without rewriting historical truth."""

from pathlib import Path

import psycopg
import pytest

from app.infrastructure.postgresql.migration import discover_migrations, migrate
from tests.postgresql.conftest import PostgreSQLFixture


HELPERS = [
    'eppm.guard_wbs_total()',
    'eppm.guard_team_parent_cycle()',
    'eppm.guard_pool_type_parent_cycle()',
]


def test_clean_schema_uses_explicit_trusted_wbs_helper_path(
    pg_database: PostgreSQLFixture,
) -> None:
    """Install the protected helper configuration on an empty database."""
    with psycopg.connect(pg_database.operator_url) as connection:
        result = connection.execute(
            "SELECT proconfig FROM pg_proc "
            "WHERE oid=ANY(%s::regprocedure[])", (HELPERS,),
        ).fetchall()

    assert result == [
        (["search_path=pg_catalog, eppm, pg_temp"],)
    ] * len(HELPERS)


def test_hardening_upgrade_preserves_body_ledger_records_and_constraint(
    empty_database: PostgreSQLFixture, tmp_path: Path,
) -> None:
    """Keep prior bytes and business records while retaining allocation checks."""
    migrations = discover_migrations()
    hardening = next(
        item for item in migrations if item.name == '0065_wbs_helper_search_path.sql'
    )
    for migration in migrations[:hardening.version - 1]:
        with (tmp_path / migration.name).open('w', encoding='utf-8') as stream:
            stream.write(migration.sql)
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        body = connection.execute(
            "SELECT proname,prosrc FROM pg_proc "
            "WHERE oid=ANY(%s::regprocedure[]) ORDER BY proname", (HELPERS,),
        ).fetchall()
        ledger = connection.execute(
            "SELECT version,name,checksum FROM eppm.schema_migration "
            "ORDER BY version"
        ).fetchall()
        connection.execute(
            "INSERT INTO eppm.project_type(id,name,is_general) "
            "VALUES (1,'General',true)"
        )
        project_id = connection.execute(
            "INSERT INTO eppm.project(name,status) "
            "VALUES ('Retained hardening fixture','In Progress') RETURNING id"
        ).fetchone()[0]
        wbs_id = connection.execute(
            "INSERT INTO eppm.wbs(code) VALUES ('HARDENING') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO eppm.project_wbs VALUES (%s,%s,80)",
            (project_id, wbs_id),
        )
        retained = connection.execute(
            "SELECT project_id,wbs_id,percentage FROM eppm.project_wbs"
        ).fetchall()

    assert migrate(empty_database.operator_url) == tuple(
        item.name for item in migrations[hardening.version - 1:]
    )

    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute(
            "SELECT proname,prosrc FROM pg_proc "
            "WHERE oid=ANY(%s::regprocedure[]) ORDER BY proname", (HELPERS,),
        ).fetchall() == body
        assert connection.execute(
            "SELECT version,name,checksum FROM eppm.schema_migration "
            "ORDER BY version"
        ).fetchall()[:len(ledger)] == ledger
        assert connection.execute(
            "SELECT project_id,wbs_id,percentage FROM eppm.project_wbs"
        ).fetchall() == retained
        # Decoy temporary records cannot hide the trusted 80% allocation.
        connection.execute('CREATE TEMP TABLE project_wbs(percentage numeric)')
        connection.execute('INSERT INTO pg_temp.project_wbs VALUES (0)')
        other = connection.execute(
            "INSERT INTO eppm.project(name,status) "
            "VALUES ('Rejected allocation','In Progress') RETURNING id"
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO eppm.project_wbs VALUES (%s,%s,30)",
                (other, wbs_id),
            )
