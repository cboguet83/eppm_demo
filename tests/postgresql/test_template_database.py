"""Exercise owned template lifecycle without borrowing application data."""

from collections.abc import Iterator
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from tests.postgresql.conftest import PostgreSQLFixture as ExistingFixture
from tests.postgresql import template_database as support
from tests.postgresql.template_database import DatabaseTemplateFactory


@pytest.fixture
def factory(
    empty_database: ExistingFixture,
) -> Iterator[DatabaseTemplateFactory]:
    """Own a separate factory and clean it even when a regression raises."""
    result = DatabaseTemplateFactory(
        empty_database.operator_url, empty_database.runtime_url,
    )
    try:
        yield result
    finally:
        result.close()


def existing_names(url: str, names: frozenset[str]) -> set[str]:
    """Inspect only explicitly supplied test identifiers on the test server."""
    with psycopg.connect(make_conninfo(url, dbname="postgres")) as connection:
        rows = connection.execute(
            "SELECT datname FROM pg_database WHERE datname=ANY(%s)",
            (list(names),),
        ).fetchall()
    return {name for name, in rows}


def test_template_migrates_once_and_is_closed_between_independent_clones(
    factory: DatabaseTemplateFactory, monkeypatch: pytest.MonkeyPatch,
    empty_database: ExistingFixture,
) -> None:
    """Reuse only migration state and remove every owned clone/template."""
    native = support.migrate
    calls = 0

    def tracked(url: str) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        return native(url)

    monkeypatch.setattr(support, "migrate", tracked)
    names: set[str] = set()
    for _ in range(3):
        with factory.clone() as database:
            names.add(database.name)
            with psycopg.connect(database.runtime_url) as connection:
                assert connection.execute(
                    "SELECT count(*) FROM eppm.schema_migration"
                ).fetchone() == (len(support.discover_migrations()),)
    assert calls == 1
    assert len(names) == 3
    assert len(factory.owned_names) == 1
    template = next(iter(factory.owned_names))
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute(
            "SELECT datallowconn FROM pg_database WHERE datname=%s",
            (template,),
        ).fetchone() == (False,)
    owned = factory.owned_names | frozenset(names)
    factory.close()
    assert existing_names(empty_database.operator_url, owned) == set()


def test_empty_and_fresh_paths_remain_distinct_from_template_clones(
    factory: DatabaseTemplateFactory,
) -> None:
    """Retain real clean migration execution and a truly empty database."""
    with factory.empty() as empty, factory.fresh() as fresh:
        assert empty.name != fresh.name
        with psycopg.connect(empty.operator_url) as connection:
            assert connection.execute(
                "SELECT to_regclass('eppm.schema_migration')"
            ).fetchone() == (None,)
        with psycopg.connect(fresh.operator_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM eppm.schema_migration"
            ).fetchone() == (len(support.discover_migrations()),)
        assert len(factory.owned_names) == 2
    assert factory.owned_names == frozenset()


@pytest.mark.parametrize("failure", ["migration", "ledger", "metadata"])
def test_failed_template_initialization_drops_its_partial_database(
    factory: DatabaseTemplateFactory, monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Do not retain a partial source after any initialization stage fails."""
    def reject(*_args: object) -> None:
        raise ValueError("injected initialization failure")

    if failure == "migration":
        monkeypatch.setattr(support, "migrate", reject)
    elif failure == "metadata":
        monkeypatch.setattr(factory, "_snapshot_metadata", reject)
    else:
        version, name, _ = factory._ledger[-1]
        factory._ledger = (*factory._ledger[:-1], (version, name, "0" * 64))
    with pytest.raises(ValueError), factory.clone():
        pytest.fail("A partial template cannot yield a clone")
    assert factory.owned_names == frozenset()


def test_failed_clone_initialization_preserves_only_its_closed_template(
    factory: DatabaseTemplateFactory, monkeypatch: pytest.MonkeyPatch,
    empty_database: ExistingFixture,
) -> None:
    """Register clone cleanup before configuration can raise."""
    with factory.clone() as database:
        assert database.name in factory.owned_names
    source = factory.owned_names
    created: set[str] = set()
    native_create = factory._create

    def tracked_create(
        *, template: str | None = None,
    ) -> support.PostgreSQLFixture:
        result = native_create(template=template)
        created.add(result.name)
        return result

    def reject(*_args: object) -> None:
        raise ValueError("injected clone initialization failure")

    monkeypatch.setattr(factory, "_create", tracked_create)
    monkeypatch.setattr(factory, "_apply_metadata", reject)
    with pytest.raises(ValueError, match="clone initialization"):
        with factory.clone():
            pytest.fail("A failed clone cannot be yielded")
    assert factory.owned_names == source
    assert existing_names(
        empty_database.operator_url, frozenset(created),
    ) == set()


def test_clone_creation_failure_keeps_the_template_and_foreign_data(
    factory: DatabaseTemplateFactory, monkeypatch: pytest.MonkeyPatch,
    empty_database: ExistingFixture,
) -> None:
    """A failed CREATE does not redirect cleanup to a selected database."""
    with factory.clone() as database:
        assert database.name in factory.owned_names
    source = factory.owned_names

    def reject(*, template: str | None = None) -> support.PostgreSQLFixture:
        assert template in source
        raise support.DatabaseFixtureError("injected CREATE failure")

    monkeypatch.setattr(factory, "_create", reject)
    with pytest.raises(support.DatabaseFixtureError), factory.clone():
        pytest.fail("A rejected CREATE cannot yield a clone")
    assert factory.owned_names == source
    assert existing_names(
        empty_database.operator_url, frozenset({empty_database.name}),
    ) == {empty_database.name}


def test_driver_error_hides_credentials_and_does_not_register_a_database(
    factory: DatabaseTemplateFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanitize external driver errors at the secret-bearing I/O boundary."""
    def reject(*_args: object, **_kwargs: object) -> None:
        raise psycopg.OperationalError("fixture-secret-must-not-escape")

    with monkeypatch.context() as patch:
        patch.setattr(psycopg, "connect", reject)
        with pytest.raises(support.DatabaseFixtureError) as failure:
            with factory.empty():
                pytest.fail("A failed connection cannot yield a database")
    assert "fixture-secret" not in str(failure.value)
    assert failure.value.__suppress_context__
    assert factory.owned_names == frozenset()


def test_migration_failure_hides_its_payload_and_cleans_the_partial_template(
    factory: DatabaseTemplateFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep operator URLs out of migration failure traceback chains."""
    def reject(_url: str) -> tuple[str, ...]:
        raise support.MigrationError("fixture-secret-must-not-escape")

    monkeypatch.setattr(support, "migrate", reject)
    with pytest.raises(support.DatabaseFixtureError) as failure:
        with factory.clone():
            pytest.fail("A failed migration cannot yield a database")
    assert "fixture-secret" not in str(failure.value)
    assert failure.value.__suppress_context__
    assert factory.owned_names == frozenset()


def test_clone_copies_database_acl_connection_limit_and_role_settings(
    factory: DatabaseTemplateFactory, monkeypatch: pytest.MonkeyPatch,
    empty_database: ExistingFixture,
) -> None:
    """Reapply database metadata PostgreSQL omits from template copying."""
    native = support.migrate
    runtime_role = conninfo_to_dict(empty_database.runtime_url)["user"]

    def configured(url: str) -> tuple[str, ...]:
        result = native(url)
        name = urlsplit(url).path.lstrip("/")
        with psycopg.connect(
            make_conninfo(url, dbname="postgres"), autocommit=True,
        ) as connection:
            connection.execute(sql.SQL(
                "REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC"
            ).format(sql.Identifier(name)))
            connection.execute(sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO {} WITH GRANT OPTION"
            ).format(sql.Identifier(name), sql.Identifier(runtime_role)))
            connection.execute(sql.SQL(
                "ALTER DATABASE {} SET timezone TO 'Europe/Paris'"
            ).format(sql.Identifier(name)))
            connection.execute(sql.SQL(
                "ALTER DATABASE {} CONNECTION LIMIT 7"
            ).format(sql.Identifier(name)))
            connection.execute(sql.SQL(
                "ALTER ROLE {} IN DATABASE {} "
                "SET statement_timeout TO '1234ms'"
            ).format(sql.Identifier(runtime_role), sql.Identifier(name)))
        return result

    monkeypatch.setattr(support, "migrate", configured)
    with factory.clone() as database:
        with psycopg.connect(database.runtime_url) as connection:
            assert connection.execute("SHOW timezone").fetchone() == (
                "Europe/Paris",
            )
            assert connection.execute("SHOW statement_timeout").fetchone() == (
                "1234ms",
            )
            assert connection.execute(
                "SELECT has_database_privilege(current_user,"
                "current_database(),'TEMPORARY')"
            ).fetchone() == (False,)
            assert connection.execute(
                "SELECT datconnlimit FROM pg_database "
                "WHERE datname=current_database()"
            ).fetchone() == (7,)
            assert connection.execute(
                "SELECT has_database_privilege(current_user,"
                "current_database(),'CONNECT WITH GRANT OPTION')"
            ).fetchone() == (True,)


def test_cleanup_refuses_foreign_database_and_closed_factory_cannot_reopen(
    factory: DatabaseTemplateFactory, empty_database: ExistingFixture,
) -> None:
    """Reject arbitrary cleanup targets and reuse after session shutdown."""
    with pytest.raises(ValueError, match="unowned"):
        factory._drop(empty_database.name)
    assert existing_names(
        empty_database.operator_url, frozenset({empty_database.name}),
    ) == {empty_database.name}
    factory.close()
    factory.close()
    with pytest.raises(RuntimeError, match="closed"), factory.clone():
        pytest.fail("Closed factories cannot create resources")


@pytest.mark.parametrize("query", ["dbname=other", "service=external"])
def test_database_query_override_is_rejected_before_any_connection(
    query: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A query cannot redirect writes away from generated database names."""
    def reject(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Invalid coordinates must not perform I/O")

    monkeypatch.setattr(psycopg, "connect", reject)
    with pytest.raises(ValueError, match="override"):
        DatabaseTemplateFactory(
            f"postgresql://operator@invalid.test/source?{query}",
            "postgresql://runtime@invalid.test/source",
        )


@pytest.mark.parametrize("name", ["", "a/b", "a?dbname=other", "x" * 64])
def test_generated_database_identifier_cannot_redirect_the_url(
    name: str,
) -> None:
    """Reject identifiers selecting another database or causing truncation."""
    with pytest.raises(ValueError, match="identifier"):
        support.database_url("postgresql://operator@invalid.test/source", name)
