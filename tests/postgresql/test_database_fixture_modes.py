"""Preserve fresh/empty fixture contracts when migrated cloning is selected."""

import psycopg
from psycopg.conninfo import conninfo_to_dict

from tests.postgresql.conftest import PostgreSQLFixture


def test_empty_fixture_stays_unmigrated_beside_the_migrated_fixture(
    empty_database: PostgreSQLFixture, pg_database: PostgreSQLFixture,
) -> None:
    """Explicit requests for both fixtures must not share a database."""
    assert empty_database.name != pg_database.name
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute(
            "SELECT to_regclass('eppm.schema_migration')"
        ).fetchone() == (None,)
    with psycopg.connect(pg_database.runtime_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM eppm.schema_migration"
        ).fetchone()[0] > 0
    operator_user = conninfo_to_dict(pg_database.operator_url)["user"]
    runtime_user = conninfo_to_dict(pg_database.runtime_url)["user"]
    assert operator_user != runtime_user
    assert isinstance(pg_database, PostgreSQLFixture)


def test_migrated_fixture_has_no_business_or_authenticated_session_seeds(
    pg_database: PostgreSQLFixture,
) -> None:
    """Keep keys, accounts and business seeds outside reusable migrations."""
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute(
            "SELECT (SELECT count(*) FROM eppm.project),"
            "(SELECT count(*) FROM eppm.app_user),"
            "(SELECT count(*) FROM eppm.app_session),"
            "(SELECT count(*) FROM eppm.request_binding_key)"
        ).fetchone() == (0, 0, 0, 0)
