"""Exercise controller proof with real independent xdist worker processes."""

import pytest

from tests.test_full_suite import PASSING_TEST, _write, suite


pytest_plugins = ("pytester",)


def _run(suite: pytest.Pytester, *arguments: str) -> pytest.RunResult:
    return suite.runpytest_subprocess(
        "-p", "xdist.plugin", "-n", "2", "--dist=load",
        "--require-full-suite", "-q", *arguments, timeout=45,
    )


def _append_plugin(suite: pytest.Pytester, source: str) -> None:
    with (suite.path / "conftest.py").open("a", encoding="utf-8") as stream:
        stream.write("\n" + source)


def test_parallel_gate_accepts_every_test_once(suite: pytest.Pytester) -> None:
    """Combine both required groups and ordinary outcomes from two workers."""
    _write(suite.path / "tests/test_ordinary.py", PASSING_TEST)
    result = _run(suite)
    result.assert_outcomes(passed=3)
    assert result.ret == pytest.ExitCode.OK


@pytest.mark.parametrize("name", [
    "POSTGRES_TEST_ADMIN_URL", "POSTGRES_TEST_RUNTIME_URL",
    "EPPM_RUN_OIDC_E2E",
])
def test_parallel_gate_requires_prerequisites(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, name: str,
) -> None:
    """Reject missing infrastructure before creating workers."""
    monkeypatch.delenv(name)
    result = _run(suite)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert name in result.stderr.str()


@pytest.mark.parametrize("selection", [
    ("tests/postgresql",), ("tests/test_oidc_browser_e2e.py",),
    ("-k", "database"),
])
def test_parallel_gate_rejects_missing_or_deselected_groups(
    suite: pytest.Pytester, selection: tuple[str, ...],
) -> None:
    """A controller cannot accept a passing partial worker collection."""
    result = _run(suite, *selection)
    assert result.ret != pytest.ExitCode.OK
    assert "did not collect required groups" in result.stdout.str()


@pytest.mark.parametrize("group", ["postgresql", "browser"])
@pytest.mark.parametrize(
    "phase", ["collection", "setup", "runtime", "teardown"],
)
def test_parallel_gate_forwards_required_skips_in_every_phase(
    suite: pytest.Pytester, group: str, phase: str,
) -> None:
    """Forward import skips even with another passing group member."""
    sources = {
        "collection": (
            "import pytest\npytest.skip('probe', allow_module_level=True)\n"
        ),
        "setup": (
            "import pytest\n@pytest.fixture(autouse=True)\ndef resource():\n"
            "    pytest.skip('probe')\n" + PASSING_TEST
        ),
        "runtime": (
            "import pytest\ndef test_example():\n    pytest.skip('probe')\n"
        ),
        "teardown": (
            "import pytest\n@pytest.fixture(autouse=True)\ndef resource():\n"
            "    yield\n    pytest.skip('probe')\n" + PASSING_TEST
        ),
    }
    path = ("tests/postgresql/test_skip.py" if group == "postgresql"
            else "tests/test_oidc_browser_e2e.py")
    _write(suite.path / path, sources[phase])
    result = _run(suite)
    assert result.ret != pytest.ExitCode.OK
    assert "Required full-suite tests skipped" in result.stdout.str()


def test_parallel_gate_rejects_divergent_worker_collections(
    suite: pytest.Pytester,
) -> None:
    """Different worker collections cannot establish complete execution."""
    _append_plugin(suite, '''
def pytest_collection_modifyitems(config, items):
    if config.workerinput['workerid'] == 'gw1':
        items.pop()
''')
    result = _run(suite)
    assert result.ret != pytest.ExitCode.OK
    assert "Worker collections differ" in result.stdout.str()


def test_parallel_gate_rejects_missing_test_reports(
    suite: pytest.Pytester,
) -> None:
    """A protocol returning without reports must not count as a test pass."""
    _append_plugin(suite, '''
@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    if 'postgresql/' in item.nodeid:
        return True
''')
    result = _run(suite)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert "Collected tests lack final reports" in result.stdout.str()


def test_parallel_gate_rejects_missing_worker_completion_proof(
    suite: pytest.Pytester,
) -> None:
    """Worker exit alone does not prove collection skips were forwarded."""
    _append_plugin(suite, '''
@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session):
    if hasattr(session.config, 'workeroutput'):
        session.config.workeroutput.pop('eppm_full_suite_skipped', None)
''')
    result = _run(suite)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert "Worker omitted full-suite completion proof" in result.stdout.str()


def test_parallel_gate_rejects_worker_crash_without_restart_masking(
    suite: pytest.Pytester,
) -> None:
    """A lost worker is fatal even when a caller requests replacements."""
    _write(suite.path / "tests/postgresql/test_database.py",
           "import os\ndef test_crash():\n    os._exit(7)\n")
    result = _run(suite, "--max-worker-restart=3")
    assert result.ret != pytest.ExitCode.OK
    assert "Worker exited without successful completion" in result.stdout.str()
    assert "replacing crashed worker" not in result.stdout.str().lower()


def test_parallel_gate_preserves_fail_fast_failure(
    suite: pytest.Pytester,
) -> None:
    """Unexecuted cases after -x cannot be called full-suite success."""
    _write(suite.path / "tests/postgresql/test_database.py",
           "def test_failure():\n    assert False\n" + "\n".join(
               f"def test_later_{index}():\n    assert True\n"
               for index in range(10)
           ))
    result = _run(suite, "-x")
    assert result.ret != pytest.ExitCode.OK
    assert "Collected tests lack final reports" in result.stdout.str()


def test_parallel_gate_rejects_duplicate_collected_identifiers(
    suite: pytest.Pytester,
) -> None:
    """Duplicate collection cannot satisfy exactly-once execution."""
    _append_plugin(suite, '''
def pytest_collection_modifyitems(items):
    items.append(items[0])
''')
    result = _run(suite)
    assert result.ret != pytest.ExitCode.OK
    assert (
        "Collection contains duplicate test identifiers" in result.stdout.str()
    )


def test_parallel_gate_rejects_duplicate_completion_reports(
    suite: pytest.Pytester,
) -> None:
    """Duplicated transport reports cannot conceal repeated execution."""
    _append_plugin(suite, '''
@pytest.hookimpl(specname='pytest_configure')
def pytest_configure_duplicate_probe(config):
    global test_config
    test_config = config

def pytest_runtest_logreport(report):
    if report.when == 'teardown' and not getattr(
        report, 'probe_duplicate', False,
    ):
        report.probe_duplicate = True
        test_config.hook.pytest_runtest_logreport(report=report)
''')
    result = _run(suite)
    assert result.ret != pytest.ExitCode.OK
    assert "Tests completed more than once" in result.stdout.str()


def test_parallel_gate_accepts_subtests_and_optional_skips(
    suite: pytest.Pytester,
) -> None:
    """Passing subtests do not become additional collected test completions."""
    _write(suite.path / "tests/postgresql/test_database.py", '''
def test_subtests(subtests):
    for number in range(3):
        with subtests.test(number=number):
            assert number >= 0
''')
    _write(suite.path / "tests/test_optional.py", '''
import pytest
pytest.skip('optional platform', allow_module_level=True)
''')
    result = _run(suite)
    assert result.ret == pytest.ExitCode.OK
    assert "Full-suite completion failed" not in result.stdout.str()


def test_parallel_gate_preserves_collection_failure(
    suite: pytest.Pytester,
) -> None:
    """Collection errors remain failures with their original diagnostics."""
    _write(suite.path / "tests/test_broken.py",
           "raise ValueError('collection failure probe')\n")
    result = _run(suite)
    assert result.ret != pytest.ExitCode.OK
    assert "collection failure probe" in result.stdout.str()
