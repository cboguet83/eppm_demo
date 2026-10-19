"""Prevent partial selection and stale collection from becoming full acceptance."""

import json
from pathlib import Path

import pytest

from scripts import run_tests
from scripts.test_inventory import ROOT
from tests.test_full_suite import suite


pytest_plugins = ("pytester",)


def _reference(suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    target = suite.path / "reference.json"
    result = suite.runpytest_subprocess(
        "-p", "scripts.full_test_proof", "--collect-only",
        "--write-full-manifest", str(target), "-q",
    )
    assert result.ret == 0
    return target


@pytest.mark.parametrize("arguments", [[], ["-p", "xdist.plugin", "-n", "2", "--dist=loadgroup"]])
def test_full_reference_accepts_all_cases_in_serial_and_each_worker(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, arguments: list[str],
) -> None:
    """New discovered tests join both the reference and every execution worker."""
    (suite.path / "tests/test_extra.py").write_text("def test_new(): assert True\n")
    target = _reference(suite, monkeypatch)
    assert len(json.loads(target.read_text())) == 3
    result = suite.runpytest_subprocess(
        "-p", "scripts.full_test_proof", "--full-manifest", str(target),
        "--require-full-suite", *arguments, "-q",
    )
    result.assert_outcomes(passed=3)
    assert result.ret == 0


@pytest.mark.parametrize("arguments", [
    ["-k", "example"],
    ["tests/postgresql", "tests/test_oidc_browser_e2e.py"],
    ["--deselect", "tests/test_extra.py::test_new"],
])
def test_subset_with_both_required_groups_cannot_claim_full_execution(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, arguments: list[str],
) -> None:
    """Both integration groups can be present while a third case is missing."""
    (suite.path / "tests/test_extra.py").write_text("def test_new(): assert True\n")
    target = _reference(suite, monkeypatch)
    result = suite.runpytest_subprocess(
        "-p", "scripts.full_test_proof", "--full-manifest", str(target),
        "--require-full-suite", *arguments, "-q",
    )
    assert result.ret != 0
    assert "differs from canonical collection" in result.stdout.str()


def test_stale_reference_cannot_omit_a_newly_added_test(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execution cannot reuse a reference from before a source change."""
    target = _reference(suite, monkeypatch)
    (suite.path / "tests/test_extra.py").write_text("def test_new(): assert True\n")
    result = suite.runpytest_subprocess(
        "-p", "scripts.full_test_proof", "--full-manifest", str(target), "-q",
    )
    assert result.ret != 0
    assert "differs from canonical collection" in result.stdout.str()


@pytest.mark.parametrize("path", ["tests", "tests/test_finance.py", "-k", "--collect-only"])
def test_full_cli_never_forwards_selection(path: str) -> None:
    """Full mode has no interface for narrowing canonical execution."""
    with pytest.raises((ValueError, SystemExit)):
        if path.startswith("-"):
            run_tests.main(["full", path])
        else:
            run_tests.commands("full", [path])


def test_full_command_preserves_all_acceptance_gates() -> None:
    """Coverage, templates, workers, JS suites and assets remain mandatory."""
    selected = run_tests.commands("full", [])
    assert len(selected) == 5
    full = selected[1]
    assert {"--require-full-suite", "--cov=app", "--cov-fail-under=95",
            "--cov-config=pyproject.toml", "--postgres-test-db-mode=template",
            "--dist=loadgroup", "--max-worker-restart=0"} <= set(full)
    assert full[full.index("-n") + 1] == "2"
    assert full[full.index("--full-manifest") + 1] == selected[0][-2]
    assert selected[2][:2] == selected[3][:2] == ["node", "--test"]
    assert selected[2][2:] and selected[3][2:]
    assert selected[4][-2:] == ["scripts.build_planning_assets", "--check"]


@pytest.mark.parametrize("variable", ["PYTEST_ADDOPTS", "PYTEST_PLUGINS"])
def test_full_command_rejects_implicit_selection(
    monkeypatch: pytest.MonkeyPatch, variable: str,
) -> None:
    """An inherited pytest override cannot modify the published full command."""
    monkeypatch.setenv(variable, "selection-probe")
    assert run_tests.main(["full"]) == 2


def test_missing_prerequisites_report_names_without_values() -> None:
    """The runner fails before execution without displaying environment secrets."""
    with pytest.raises(ValueError) as error:
        run_tests.require_full_environment({"POSTGRES_TEST_ADMIN_URL": "private-value"})
    assert "POSTGRES_TEST_RUNTIME_URL" in str(error.value)
    assert "private-value" not in str(error.value)


@pytest.mark.parametrize("replacement", [
    ('testpaths = ["tests"]', 'testpaths = ["tests/postgresql"]'),
    ('testpaths = ["tests"]', 'testpaths = ["tests"]\naddopts = "-k example"'),
    ('source = ["app"]', 'source = ["app/domain"]'),
])
def test_full_runner_rejects_silently_narrowed_configuration(
    tmp_path: Path, replacement: tuple[str, str],
) -> None:
    """Configuration selection and coverage narrowing fail before execution."""
    source = (ROOT / "pyproject.toml").read_text()
    (tmp_path / "pyproject.toml").write_text(source.replace(*replacement))
    with pytest.raises(ValueError):
        run_tests.validate_full_config(tmp_path)
