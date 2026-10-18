"""Verify measurements stay complete, invocation-local and sanitized."""

import json
from pathlib import Path

import pytest

from tests.test_full_suite import _write, suite


pytest_plugins = ("pytester",)


def _configure(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    root = Path(__file__).resolve().parents[1]
    output = suite.path / "measurements"
    monkeypatch.setenv("PYTHONPATH", str(root))
    monkeypatch.setenv("EPPM_TEST_MEASUREMENT_DIRECTORY", str(output))
    _write(suite.path / "tests/postgresql/test_database.py", '''
import pytest
@pytest.fixture
def pg_database():
    yield 'fixture-value-not-logged'
def test_example(pg_database):
    assert pg_database == 'fixture-value-not-logged'
''')
    return output


@pytest.mark.parametrize("workers", [0, 2])
def test_measurements_record_preparation_and_complete_canonical_outcomes(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, workers: int,
) -> None:
    """Record setup timing and outcomes without exposing fixture values."""
    output = _configure(suite, monkeypatch)
    result = suite.runpytest_subprocess(
        "-p", "xdist.plugin", "-p", "tests.performance.template_metrics",
        "-n", str(workers), "--dist=loadgroup", "--require-full-suite", "-q",
    )
    assert result.ret == pytest.ExitCode.OK
    records = []
    for path in output.glob("*.json"):
        with path.open(encoding="utf-8") as stream:
            text = stream.read()
        assert "fixture-value-not-logged" not in text
        records.append(json.loads(text))
    runs = [row for row in records if row["worker"] != "controller"]
    assert len(runs) == (2 if workers else 1)
    assert all(len(row["collected"]) == 2 for row in runs)
    assert all(row["collected"] == runs[0]["collected"] for row in runs)
    preparations = [item for row in runs for item in row["preparations"]]
    assert len(preparations) == 1
    assert preparations[0]["fixture"] == "pg_database"
    assert preparations[0]["seconds"] >= 0
    reports = (next(row for row in records if row["worker"] == "controller")
               if workers else runs[0])["reports"]
    assert sum(row["phase"] == "call" for row in reports) == 2
    assert sum(row["phase"] == "teardown" for row in reports) == 2


def test_measurements_refuse_reused_output_directory(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale data must fail before executing a new measurement."""
    output = _configure(suite, monkeypatch)
    output.mkdir()
    with (output / "obsolete.json").open("w", encoding="utf-8") as stream:
        stream.write("{}")
    result = suite.runpytest_subprocess(
        "-p", "tests.performance.template_metrics", "-q",
    )
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "fresh output directory" in result.stderr.str()


def test_measurements_require_explicit_output_directory(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require an explicit evidence directory."""
    _configure(suite, monkeypatch)
    monkeypatch.delenv("EPPM_TEST_MEASUREMENT_DIRECTORY")
    result = suite.runpytest_subprocess(
        "-p", "tests.performance.template_metrics", "-q",
    )
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "EPPM_TEST_MEASUREMENT_DIRECTORY" in result.stderr.str()


def test_failed_fixture_preparation_is_measured_without_claiming_success(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record a setup failure's timing while retaining its failing exit code."""
    output = _configure(suite, monkeypatch)
    _write(suite.path / "tests/postgresql/test_database.py", '''
import pytest
@pytest.fixture
def pg_database():
    raise ValueError('controlled preparation failure')
def test_example(pg_database):
    assert False
''')
    result = suite.runpytest_subprocess(
        "-p", "tests.performance.template_metrics", "-q",
    )
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    with (output / "serial.json").open() as stream:
        record = json.load(stream)
    assert len(record["preparations"]) == 1
    assert any(row["phase"] == "setup" and row["outcome"] == "failed"
               for row in record["reports"])
