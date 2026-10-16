"""Verify combined worker and native child application coverage."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.postgresql.template_database import PostgreSQLFixture
from tests.test_full_suite import _write, suite


pytest_plugins = ("pytester",)


_WORKER = '''"""Exercise an application branch in an ordinary worker."""
import json
import os
from pathlib import Path
import pytest
from app.domain.tags.rules import validate_tag_group

def test_worker_branch():
    with pytest.raises(ValueError):
        validate_tag_group(' ')
    with Path('worker-unit.json').open('w') as stream:
        json.dump(os.environ.get('PYTEST_XDIST_WORKER', 'serial'), stream)
'''

_BROWSER = '''"""Exercise worker and native Streamlit child branches."""
import json
import os
from pathlib import Path
import pytest
from playwright.sync_api import expect, sync_playwright
from app.domain.tags.rules import validate_assignment
from tests.postgresql.browser import native_server

SCREEN = """
import streamlit as st
from app.domain.tags.rules import validate_tag
try:
    validate_tag(' ')
except ValueError:
    st.success('Native child coverage completed')
"""

def test_native_child_branch(authorized, tmp_path):
    with pytest.raises(ValueError):
        validate_assignment(None, None, None, entity='Project')
    with Path('worker-native.json').open('w') as stream:
        json.dump(os.environ.get('PYTEST_XDIST_WORKER', 'serial'), stream)
    with native_server(authorized, tmp_path, SCREEN) as server:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = server.new_page(browser)
                page.goto(server.origin)
                expect(page.get_by_text(
                    'Native child coverage completed', exact=True,
                )).to_be_visible(timeout=30000)
            finally:
                browser.close()
'''


@pytest.mark.parametrize("workers", [0, 2], ids=["serial", "parallel"])
def test_coverage_combines_worker_and_native_child_application_lines(
    empty_database: PostgreSQLFixture, tmp_path: Path, workers: int,
) -> None:
    """Combine exclusive branches from two workers and a native child."""
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
    for name, source in (
        ("test_worker_coverage.py", _WORKER),
        ("test_native_browser.py", _BROWSER),
    ):
        with (target / name).open("w", encoding="utf-8") as stream:
            stream.write(source)
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("COVERAGE", "COV_CORE"))
    }
    environment.pop("PYTEST_ADDOPTS", None)
    environment.update({
        "PYTHONPATH": str(root), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "COVERAGE_FILE": str(tmp_path / ".coverage-probe"),
    })
    command = [
        sys.executable, "-m", "pytest", "-p", "xdist.plugin",
        "-p", "pytest_cov.plugin", "-n", str(workers), "--dist=loadgroup",
        "--postgres-test-db-mode=template", "--cov=app",
        "--cov-config=" + str(root / "pyproject.toml"),
        "--cov-report=json:combined.json", "-q", "-x",
    ]
    result = subprocess.run(
        command, env=environment, cwd=tmp_path, capture_output=True,
        timeout=90, check=False,
    )
    with (tmp_path / "coverage-output.log").open("wb") as stream:
        stream.write(result.stdout)
        stream.write(result.stderr)
    assert result.returncode == 0
    with (tmp_path / "combined.json").open() as stream:
        report = json.load(stream)
    matches = [value for path, value in report["files"].items()
               if path.endswith("app/domain/tags/rules.py")]
    assert len(matches) == 1
    with (root / "app/domain/tags/rules.py").open() as stream:
        tree = ast.parse(stream.read())
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef)}
    for name in ("validate_tag_group", "validate_tag", "validate_assignment"):
        raised = next(node.lineno for node in ast.walk(functions[name])
                      if isinstance(node, ast.Raise))
        assert raised in matches[0]["executed_lines"]
    identities = set()
    for filename in ("worker-unit.json", "worker-native.json"):
        with (tmp_path / filename).open() as stream:
            identities.add(json.load(stream))
    assert len(identities) == (2 if workers else 1)


@pytest.mark.parametrize(
    "failure", ["missing-report", "worker-crash", "95-gate"],
)
def test_coverage_cannot_mask_missing_workers_or_completion_failures(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    """Reject partial execution and coverage below the existing gate."""
    root = Path(__file__).resolve().parents[2]
    for name in tuple(os.environ):
        if name.startswith(("COVERAGE", "COV_CORE")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("COVERAGE_FILE", str(suite.path / ".coverage-probe"))
    monkeypatch.setenv("PYTHONPATH", str(root))
    options = []
    if failure == "missing-report":
        with (suite.path / "conftest.py").open("a") as stream:
            stream.write('''
@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    if 'postgresql/' in item.nodeid:
        return True
''')
    elif failure == "worker-crash":
        _write(suite.path / "tests/postgresql/test_database.py",
               "import os\ndef test_crash():\n    os._exit(7)\n")
    else:
        options.append("--cov-fail-under=95")
    result = suite.runpytest_subprocess(
        "-p", "xdist.plugin", "-p", "pytest_cov.plugin", "-n", "2",
        "--dist=loadgroup", "--require-full-suite", "--cov=app",
        "--cov-config=" + str(root / "pyproject.toml"),
        "--cov-report=json:combined.json", "-q", *options,
    )
    assert result.ret != pytest.ExitCode.OK
    message = result.stdout.str()
    if failure == "missing-report":
        assert "Collected tests lack final reports" in message
    elif failure == "worker-crash":
        assert "Worker exited without successful completion" in message
    else:
        assert "Required test coverage of 95% not reached" in message
