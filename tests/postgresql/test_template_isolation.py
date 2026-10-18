"""Prove independent native business/security state in migrated clones."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from hmac import compare_digest
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier, Event

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from app.domain.access.models import AccessDenied
from app.infrastructure.postgresql.revisions import RevisionSnapshot, snapshot
from tests.postgresql.conftest import (
    AuthorizedFixture,
    PostgreSQLFixture,
    authorized_database,
)
from tests.postgresql.template_database import DatabaseTemplateFactory
from tests.postgresql import template_database as support


def _snapshot(fixture: AuthorizedFixture) -> RevisionSnapshot:
    return snapshot(fixture.database, fixture.key, fixture.binding().access)


def _names(url: str, names: set[str]) -> set[str]:
    with psycopg.connect(make_conninfo(url, dbname="postgres")) as connection:
        return {row[0] for row in connection.execute(
            "SELECT datname FROM pg_database WHERE datname=ANY(%s)",
            (list(names),),
        )}


def test_sibling_clones_isolate_writes_sequences_cache_keys_and_sessions(
    database_factory: DatabaseTemplateFactory,
) -> None:
    """Equal business IDs retain independent writes, keys and revocations."""
    with ExitStack() as stack:
        first_db = stack.enter_context(database_factory.clone())
        second_db = stack.enter_context(database_factory.clone())
        first = stack.enter_context(authorized_database(first_db))
        second = stack.enter_context(authorized_database(second_db))
        keys_differ = not compare_digest(first.key, second.key)
        assert keys_differ
        before_first, before_second = _snapshot(first), _snapshot(second)
        assert before_first.identity[0] != before_second.identity[0]
        assert before_first.identity[1] != before_second.identity[1]
        assert before_first.scope == before_second.scope == (1, 2)
        assert before_first.token() != before_second.token()
        assert before_first.projects[0][1] != before_second.projects[0][1]
        with pytest.raises(AccessDenied):
            second.database.run(
                lambda connection: connection.execute("SELECT 1"),
                bind=first.binding(),
            )
        first.query("UPDATE eppm.project SET name='Only first' WHERE id=1",
                    write=True)
        assert first.query("SELECT name FROM eppm.project WHERE id=1") == [
            ("Only first",),
        ]
        assert second.query("SELECT name FROM eppm.project WHERE id=1") == [
            ("Editable",),
        ]
        assert _snapshot(first).token() != before_first.token()
        assert _snapshot(second) == before_second
        for fixture in (first, second):
            with psycopg.connect(fixture.setup.operator_url) as connection:
                assert connection.execute(
                    "INSERT INTO eppm.project(name) VALUES ('Independent') "
                    "RETURNING id"
                ).fetchone() == (4,)
        with psycopg.connect(first_db.operator_url) as connection:
            connection.execute(
                "UPDATE eppm.app_session SET revoked=true "
                "WHERE session_hash='session-1'"
            )
        with pytest.raises(AccessDenied):
            first.query("SELECT id FROM eppm.project")
        assert second.query("SELECT id FROM eppm.project ORDER BY id") == [
            (1,), (2,),
        ]
    # Writes and authentication seeds must never reach the closed source.
    with database_factory.clone() as pristine:
        with psycopg.connect(pristine.operator_url) as connection:
            assert connection.execute(
                "SELECT (SELECT count(*) FROM eppm.project),"
                "(SELECT count(*) FROM eppm.app_session),"
                "(SELECT count(*) FROM eppm.request_binding_key)"
            ).fetchone() == (0, 0, 0)


def test_simultaneous_invocations_never_remove_each_others_databases(
    empty_database: PostgreSQLFixture,
) -> None:
    """Independent factories sharing a worker label retain exact ownership."""
    ready = Barrier(2, timeout=30)
    first_closed = Event()
    names: set[str] = set()

    def run(index: int) -> set[str]:
        factory = DatabaseTemplateFactory(
            empty_database.operator_url, empty_database.runtime_url,
            worker="same-worker",
        )
        try:
            with factory.clone() as database:
                owned = set(factory.owned_names)
                ready.wait()
                if index:
                    assert first_closed.wait(30)
                    assert _names(empty_database.operator_url, owned) == owned
                    with psycopg.connect(database.operator_url) as connection:
                        assert connection.execute(
                            "SELECT 1"
                        ).fetchone() == (1,)
            return owned
        finally:
            factory.close()
            if not index:
                first_closed.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, index) for index in range(2)]
        for future in futures:
            owned = future.result(timeout=60)
            assert not names.intersection(owned)
            names.update(owned)
    assert _names(empty_database.operator_url, names) == set()
    assert _names(empty_database.operator_url, {empty_database.name}) == {
        empty_database.name,
    }


def test_clone_epoch_initialization_failure_cleans_only_its_owned_clone(
    database_factory: DatabaseTemplateFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure after cloning cannot expose or retain a copied identity."""
    with database_factory.clone():
        pass  # Build the template before faulting clone initialization.
    source = database_factory.owned_names
    execute = psycopg.Connection.execute

    def fail_epoch(
        connection: psycopg.Connection, query: object,
        *args: object, **kwargs: object,
    ) -> object:
        if isinstance(query, str) and query.startswith(
            "UPDATE eppm.database_identity"
        ):
            raise psycopg.OperationalError("injected epoch write failure")
        return execute(connection, query, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.Connection, "execute", fail_epoch)
        with pytest.raises(support.DatabaseFixtureError):
            with database_factory.clone():
                pytest.fail("An uninitialized identity cannot be yielded")
    assert database_factory.owned_names == source


def test_new_factory_revalidates_changed_migration_checksums(
    empty_database: PostgreSQLFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new invocation cannot reuse an earlier checksum-valid source."""
    from dataclasses import replace

    with ExitStack() as cleanup:
        first = DatabaseTemplateFactory(
            empty_database.operator_url, empty_database.runtime_url,
        )
        cleanup.callback(first.close)
        with first.clone():
            pass  # Keep the first closed template alive during a second run.
        sources = support.discover_migrations()
        changed = (*sources[:-1], replace(sources[-1], checksum="0" * 64))
        monkeypatch.setattr(support, "discover_migrations", lambda: changed)
        second = DatabaseTemplateFactory(
            empty_database.operator_url, empty_database.runtime_url,
        )
        cleanup.callback(second.close)
        with pytest.raises(ValueError, match="ledger"), second.clone():
            pytest.fail("A stale ledger cannot supply a clone")
        assert not second.owned_names
        assert len(first.owned_names) == 1


_PROCESS_TEST = '''"""Exercise cleanup in an isolated pytest process."""
from collections.abc import Iterator
import json
import os
from pathlib import Path
import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from tests.postgresql.template_database import (
    DatabaseTemplateFactory, PostgreSQLFixture,
)

@pytest.fixture
def clone() -> Iterator[PostgreSQLFixture]:
    """Record exact resource ownership before intentional process failure."""
    factory = DatabaseTemplateFactory(
        os.environ['POSTGRES_TEST_ADMIN_URL'],
        os.environ['POSTGRES_TEST_RUNTIME_URL'],
        worker='process-check',
    )
    try:
        with factory.clone() as database:
            with psycopg.connect(make_conninfo(
                database.operator_url, dbname='postgres',
            )) as connection:
                rows = connection.execute(
                    'SELECT datname,oid,datdba FROM pg_database '
                    'WHERE datname=ANY(%s)', (list(factory.owned_names),),
                ).fetchall()
            with Path(os.environ['EPPM_TEST_RESOURCE_RECORD']).open(
                'w', encoding='utf-8',
            ) as stream:
                json.dump(rows, stream)
            yield database
    finally:
        factory.close()

def test_first(clone: PostgreSQLFixture) -> None:
    """Stop before any following case and exercise owned fixture cleanup."""
    if os.environ['EPPM_TEST_PROCESS_MODE'] == 'crash':
        os._exit(7)
    assert False, 'intentional fail-fast cleanup probe'

def test_never_reached() -> None:
    """Record an error if fail-fast unexpectedly schedules another case."""
    Path(os.environ['EPPM_TEST_UNREACHED']).touch()
'''


@pytest.mark.parametrize("mode", ["fail-fast", "crash"])
def test_process_failure_has_bounded_exact_resource_recovery(
    empty_database: PostgreSQLFixture, tmp_path: Path, mode: str,
) -> None:
    """Normal fail-fast cleans up; a hard exit needs proven exact recovery."""
    script = tmp_path / "test_owned_process.py"
    with script.open("w", encoding="utf-8") as stream:
        stream.write(_PROCESS_TEST)
    record, unreached = tmp_path / "resources.json", tmp_path / "unreached"
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment.update({
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "EPPM_TEST_RESOURCE_RECORD": str(record),
        "EPPM_TEST_UNREACHED": str(unreached),
        "EPPM_TEST_PROCESS_MODE": mode,
    })
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(script), "-x", "-q",
         "--rootdir", str(tmp_path), "-c", "/dev/null"],
        env=environment, cwd=tmp_path, capture_output=True, timeout=60,
        check=False,
    )
    assert result.returncode == (7 if mode == "crash" else 1)
    assert not unreached.exists()
    with record.open(encoding="utf-8") as stream:
        resources = json.load(stream)
    assert len(resources) == 2
    names = {name for name, _, _ in resources}
    try:
        remaining = _names(empty_database.operator_url, names)
        assert remaining == (names if mode == "crash" else set())
    finally:
        # A controller may recover only recorded names with matching OID/owner.
        with psycopg.connect(make_conninfo(
            empty_database.operator_url, dbname="postgres",
        ), autocommit=True) as connection:
            for name, oid, owner in reversed(resources):
                actual = connection.execute(
                    "SELECT oid,datdba FROM pg_database WHERE datname=%s",
                    (name,),
                ).fetchone()
                if actual == (oid, owner):
                    connection.execute(sql.SQL(
                        "DROP DATABASE {} WITH (FORCE)"
                    ).format(sql.Identifier(name)))
    assert _names(empty_database.operator_url, names) == set()
    assert _names(empty_database.operator_url, {empty_database.name}) == {
        empty_database.name,
    }
