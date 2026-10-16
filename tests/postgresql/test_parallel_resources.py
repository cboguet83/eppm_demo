"""Prove live worker resource isolation and cross-process benchmark locking."""

import json
import os
from pathlib import Path
import subprocess
import sys

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from tests.postgresql.benchmark_lock import benchmark_cluster_lock
from tests.postgresql.template_database import (
    DatabaseFixtureError, PostgreSQLFixture,
)


_PROBE = '''"""Coordinate two actual workers without shared business state."""
import json
import os
from pathlib import Path
from time import monotonic, sleep
import psycopg
import pytest
from tests.postgresql.benchmark_lock import benchmark_cluster_lock

@pytest.mark.parametrize('identity', [
    0, pytest.param(1, marks=pytest.mark.xdist_group(
        name='browser-benchmark-deployment',
    )),
])
def test_live_workers(identity, pg_database, database_factory):
    directory = Path(os.environ['EPPM_TEST_WORKER_RECORDS'])
    record = {
        'worker': os.environ['PYTEST_XDIST_WORKER'], 'pid': os.getpid(),
        'owned': sorted(database_factory.owned_names),
    }
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute(
            "INSERT INTO eppm.project_type(name,is_general) "
            "VALUES ('General',true)"
        )
        connection.execute(
            "INSERT INTO eppm.project(name) VALUES (%s)",
            (f'Only worker {identity}',),
        )
    with (directory / f'{identity}.json').open('w') as stream:
        json.dump(record, stream)
    other = directory / f'{1 - identity}.json'
    deadline = monotonic() + 30
    while not other.exists():
        assert monotonic() < deadline
        sleep(0.01)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute(
            'SELECT id,name FROM eppm.project'
        ).fetchall() == [(1, f'Only worker {identity}')]
    with benchmark_cluster_lock(pg_database):
        started = monotonic()
        sleep(0.1)
        finished = monotonic()
    with (directory / f'lock-{identity}.json').open('w') as stream:
        json.dump([started, finished], stream)
'''


def test_real_workers_isolate_clones_and_serialize_cluster_observations(
    empty_database: PostgreSQLFixture, tmp_path: Path,
) -> None:
    """Two scheduler groups own distinct resources and one cluster lock."""
    root = Path(__file__).resolve().parents[2]
    target = tmp_path / "tests" / "postgresql"
    target.mkdir(parents=True)
    for source, destination in (
        (root / "tests/conftest.py", tmp_path / "conftest.py"),
        (root / "tests/postgresql/conftest.py", target / "conftest.py"),
    ):
        with source.open(encoding="utf-8") as stream:
            content = stream.read()
        with destination.open("w", encoding="utf-8") as stream:
            stream.write(content)
    with (target / "test_workers.py").open("w", encoding="utf-8") as stream:
        stream.write(_PROBE)
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment.update({
        "PYTHONPATH": str(root), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "EPPM_TEST_WORKER_RECORDS": str(tmp_path),
    })
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "xdist.plugin", "-n", "2",
         "--dist=loadgroup", "--postgres-test-db-mode=template", "-q", "-x"],
        cwd=tmp_path, env=environment, capture_output=True, timeout=60,
        check=False,
    )
    with (tmp_path / "worker-output.log").open("wb") as stream:
        stream.write(result.stdout)
        stream.write(result.stderr)
    assert result.returncode == 0
    records, intervals = [], []
    for identity in range(2):
        with (tmp_path / f"{identity}.json").open() as stream:
            records.append(json.load(stream))
        with (tmp_path / f"lock-{identity}.json").open() as stream:
            intervals.append(json.load(stream))
    assert records[0]["worker"] != records[1]["worker"]
    assert records[0]["pid"] != records[1]["pid"]
    owned = [set(record["owned"]) for record in records]
    assert len(owned[0]) == len(owned[1]) == 2
    assert owned[0].isdisjoint(owned[1])
    intervals.sort()
    assert intervals[0][1] <= intervals[1][0]
    with psycopg.connect(make_conninfo(
        empty_database.operator_url, dbname="postgres",
    )) as connection:
        assert connection.execute(
            "SELECT datname FROM pg_database WHERE datname=ANY(%s)",
            (list(owned[0] | owned[1]),),
        ).fetchall() == []
        assert connection.execute(
            "SELECT count(*) FROM pg_database WHERE datname=%s",
            (empty_database.name,),
        ).fetchone() == (1,)


def test_contended_benchmark_lock_fails_with_bounded_sanitized_error(
    empty_database: PostgreSQLFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second session cannot enter or expose driver details after timeout."""
    execute = psycopg.Connection.execute

    def short_timeout(
        connection: psycopg.Connection, query: object,
        *args: object, **kwargs: object,
    ) -> object:
        if query == "SET lock_timeout='180s'":
            query = "SET lock_timeout='30ms'"
        return execute(connection, query, *args, **kwargs)

    with benchmark_cluster_lock(empty_database):
        with monkeypatch.context() as patch:
            patch.setattr(psycopg.Connection, "execute", short_timeout)
            with pytest.raises(DatabaseFixtureError) as failure:
                with benchmark_cluster_lock(empty_database):
                    pytest.fail("A contending session cannot enter")
            assert str(failure.value) == (
                "Test benchmark observation lock failed."
            )
            assert failure.value.__suppress_context__
    with benchmark_cluster_lock(empty_database):
        pass  # The original holder released the lock despite nested failure.
