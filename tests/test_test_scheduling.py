"""Audit scheduling without removing any canonical collection identity."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.conftest import HEAVY_GROUP, _execution_group
from tests.test_full_suite import suite


pytest_plugins = ("pytester",)


@pytest.mark.parametrize("arguments", [
    ("-n", "auto", "--dist=loadgroup"),
    ("-n", "3", "--dist=loadgroup"), ("-n", "2", "--dist=load"),
])
def test_parallel_policy_requires_two_loadgroup_workers(
    suite: pytest.Pytester, arguments: tuple[str, ...],
) -> None:
    """Reject unsupported concurrency before starting any worker."""
    result = suite.runpytest_subprocess(
        "-p", "xdist.plugin", *arguments, "-q",
    )
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "requires -n 2 --dist=loadgroup" in result.stderr.str()


def test_all_native_creators_and_cluster_observers_share_a_group() -> None:
    """New browser/benchmark callers require explicit policy coverage."""
    root = Path(__file__).resolve().parents[1]
    creators = {
        "native_server", "sync_playwright", "async_playwright",
        "isolated_benchmark",
    }
    discovered: set[str] = set()
    for path in (root / "tests").rglob("test_*.py"):
        with path.open(encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        calls = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        if not calls.intersection(creators):
            continue
        relative = path.relative_to(root).as_posix()
        discovered.add(relative)
        assert _execution_group(relative) == HEAVY_GROUP, relative
    assert "tests/postgresql/test_benchmark_tools.py" in discovered
    assert "tests/postgresql/test_employee_functions.py" in discovered
    assert _execution_group("tests/postgresql/test_deployed_recovery.py") == (
        HEAVY_GROUP
    )
    assert _execution_group("tests/test_oidc_browser_e2e.py") == HEAVY_GROUP


def test_heavy_workload_cannot_split_into_a_combined_group(
    suite: pytest.Pytester,
) -> None:
    """Reject marks that xdist would concatenate into a different group."""
    with (suite.path / "tests/test_dialog_browser.py").open("w") as stream:
        stream.write(
            "import pytest\n@pytest.mark.xdist_group(name='other')\n"
            "def test_dialog():\n    assert True\n"
        )
    result = suite.runpytest_subprocess(
        "-p", "xdist.plugin", "-n", "2", "--dist=loadgroup", "-q",
    )
    assert result.ret != pytest.ExitCode.OK
    assert "conflicting xdist groups" in (
        result.stdout.str() + result.stderr.str()
    )


def test_loadgroup_retains_canonical_ids_and_serializes_heavy_members(
    suite: pytest.Pytester,
) -> None:
    """A real scheduler keeps heavy members together and every test once."""
    with (suite.path / "tests/test_dialog_browser.py").open("w") as stream:
        stream.write("def test_dialog():\n    assert True\n")
    with (suite.path / "conftest.py").open("a") as stream:
        stream.write('''
import json
from pathlib import Path

def pytest_runtest_logreport(report):
    if report.when == 'call' and hasattr(report, 'worker_id'):
        with Path('scheduled.jsonl').open('a') as stream:
            stream.write(json.dumps([report.nodeid, report.worker_id]) + '\\n')
''')
    serial = suite.runpytest_subprocess("--collect-only", "-q")
    expected = {
        line for line in serial.stdout.lines if line.startswith("tests/")
    }
    result = suite.runpytest_subprocess(
        "-p", "xdist.plugin", "-n", "2", "--dist=loadgroup",
        "--require-full-suite", "-q",
    )
    assert result.ret == pytest.ExitCode.OK
    with (suite.path / "scheduled.jsonl").open() as stream:
        rows = [json.loads(line) for line in stream]
    canonical = [nodeid.rsplit("@", 1)[0] for nodeid, _ in rows]
    assert set(canonical) == expected
    assert len(canonical) == len(expected) == 3
    workers = {
        worker for nodeid, worker in rows if "@" + HEAVY_GROUP in nodeid
    }
    assert len(workers) == 1


def test_complete_repository_manifest_matches_both_worker_collections(
    tmp_path: Path,
) -> None:
    """Compare the actual full manifest without running application cases."""
    root = Path(__file__).resolve().parents[1]
    with (tmp_path / "manifest_probe.py").open("w") as stream:
        stream.write('''
import json
import os
from pathlib import Path
import pytest

def pytest_collection_finish(session):
    identity = getattr(session.config, 'workerinput', {}).get(
        'workerid', 'serial',
    )
    target = Path(os.environ['EPPM_TEST_MANIFESTS']) / (identity + '.json')
    with target.open('w') as stream:
        json.dump([item.nodeid for item in session.items], stream)

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    return True
''')
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment.update({
        "PYTHONPATH": os.pathsep.join((str(tmp_path), str(root))),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "EPPM_RUN_OIDC_E2E": "1",
        "EPPM_TEST_MANIFESTS": str(tmp_path),
    })
    base = [sys.executable, "-m", "pytest", "-p", "manifest_probe",
            "-p", "xdist.plugin", "-p", "no:cacheprovider", "-q"]
    for arguments in (["--collect-only"], ["-n", "2", "--dist=loadgroup"]):
        result = subprocess.run(
            [*base, *arguments], cwd=root, env=environment,
            capture_output=True, timeout=60, check=False,
        )
        assert result.returncode == 0
    with (tmp_path / "serial.json").open() as stream:
        reference = json.load(stream)
    assert len(reference) > 3000
    assert len(set(reference)) == len(reference)
    for worker in ("gw0", "gw1"):
        with (tmp_path / f"{worker}.json").open() as stream:
            actual = json.load(stream)
        assert [nodeid.removesuffix("@" + HEAVY_GROUP)
                for nodeid in actual] == reference
