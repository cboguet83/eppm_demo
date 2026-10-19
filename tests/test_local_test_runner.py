"""Verify explicit selection, inventory drift and real fast-lane isolation."""

import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import run_tests, test_inventory


pytest_plugins = ("pytester",)


def _inventory(root: Path) -> None:
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests/test_example.py").write_text(
        "def test_one(): assert True\n", encoding="utf-8",
    )
    (root / "tests/suites.json").write_text(json.dumps({
        "version": 1, "fast": ["tests/test_example.py"], "extended": [],
    }), encoding="utf-8")


def test_inventory_detects_new_modules_but_discovers_new_cases(tmp_path: Path) -> None:
    """Adding a case needs no frozen ID update; new modules need classification."""
    _inventory(tmp_path)
    module = tmp_path / "tests/test_example.py"
    module.write_text(module.read_text() + "def test_two(): assert True\n")
    assert test_inventory.load_inventory(tmp_path) == ("tests/test_example.py",)
    selected = run_tests.commands("fast", [], tmp_path)
    assert selected[0][-1] == "tests/test_example.py"
    (tmp_path / "tests/test_new.py").touch()
    with pytest.raises(ValueError, match="inventory drift"):
        test_inventory.load_inventory(tmp_path)


@pytest.mark.parametrize("value", [
    "../tests/test_example.py", "/tmp/test_example.py", "tests/../scripts",
    "tests\\test_example.py", "-k", "tests/missing.py", "tests//test_example.py",
])
def test_targeted_paths_cannot_escape_the_test_tree(tmp_path: Path, value: str) -> None:
    """The path interface cannot become arbitrary pytest option forwarding."""
    _inventory(tmp_path)
    with pytest.raises(ValueError):
        run_tests.commands("targeted", [value], tmp_path)


def test_targeted_commands_retain_the_explicit_node_id(tmp_path: Path) -> None:
    """Targeted feedback keeps its documented per-case selection."""
    _inventory(tmp_path)
    path = "tests/test_example.py::test_one"
    assert run_tests.commands("targeted", [path], tmp_path)[0][-1] == path
    for mode, paths in (("targeted", []), ("fast", [path])):
        with pytest.raises(ValueError):
            run_tests.commands(mode, paths, tmp_path)


def test_command_failure_stops_later_work_and_preserves_status(tmp_path: Path) -> None:
    """An unsuccessful child prevents a later command from running."""
    target = tmp_path / "should-not-exist"
    result = run_tests.run_commands([
        [sys.executable, "-c", "raise SystemExit(17)"],
        [sys.executable, "-c", f"from pathlib import Path; Path({str(target)!r}).touch()"],
    ], tmp_path, dict(os.environ))
    assert result == 17
    assert not target.exists()


@pytest.mark.parametrize("probe", [
    "import psycopg; psycopg.connect('invalid')",
    "import socket; socket.create_connection(('127.0.0.1', 1))",
    "import subprocess; subprocess.run(['docker', 'version'])",
])
def test_fast_resource_guard_stops_service_or_process_attempts(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, probe: str,
) -> None:
    """Even a newly introduced resource call fails before real work starts."""
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHONPATH", str(test_inventory.ROOT))
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    pytester.makepyfile("def test_resource():\n    " + probe + "\n")
    result = pytester.runpytest_subprocess("-p", "scripts.fast_test_guard", "-q")
    result.assert_outcomes(failed=1)
    assert "Fast tests cannot" in result.stdout.str()


def test_fast_guard_rejects_a_new_real_database_fixture(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dynamically requested integration fixtures cannot enter a fast module."""
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHONPATH", str(test_inventory.ROOT))
    directory = pytester.path / "tests/postgresql"
    directory.mkdir(parents=True)
    (directory / "conftest.py").write_text(
        "import pytest\n@pytest.fixture\ndef database():\n"
        "    raise AssertionError('fixture body must not execute')\n",
    )
    (directory / "test_resource.py").write_text(
        "def test_case(request): request.getfixturevalue('database')\n",
    )
    result = pytester.runpytest_subprocess("-p", "scripts.fast_test_guard", "-q")
    assert result.ret != 0
    assert "Real integration fixtures cannot" in result.stdout.str()


def test_dry_run_labels_partial_scope_and_rejects_hidden_selection(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """No subprocess is needed to inspect a selected command or reject addopts."""
    caplog.set_level(logging.INFO)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    assert run_tests.main(["targeted", "tests/test_finance.py", "--dry-run"]) == 0
    assert "Partial targeted feedback" in caplog.text
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k hidden")
    assert run_tests.main(["targeted", "tests/test_finance.py"]) == 2


def test_repository_inventory_remains_complete() -> None:
    """An unclassified new test module fails review instead of disappearing."""
    assert len(test_inventory.load_inventory()) > 50


@pytest.mark.parametrize("members", [
    ["tests/test_example.py", "tests/test_example.py"],
    ["tests/test_example.py::test_one"], ["tests/missing.py"],
])
def test_inventory_rejects_duplicate_partial_or_missing_members(
    tmp_path: Path, members: list[str],
) -> None:
    """Invalid selections cannot silently execute a different test universe."""
    _inventory(tmp_path)
    (tmp_path / "tests/suites.json").write_text(json.dumps({
        "version": 1, "fast": members, "extended": [],
    }))
    with pytest.raises(ValueError):
        test_inventory.load_inventory(tmp_path)
