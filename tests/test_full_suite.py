"""Exercise full-suite enforcement in isolated sessions without services."""

from pathlib import Path

import pytest


pytest_plugins = ("pytester",)
PASSING_TEST = "def test_example():\n    assert True\n"
ADMIN_URL = "postgresql://fixture-only-admin@invalid.test/unused"
RUNTIME_URL = "postgresql://fixture-only-runtime@invalid.test/unused"


def _write(path: Path, source: str) -> None:
    """Create an isolated test fixture using an explicitly closed stream."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        stream.write(source)


@pytest.fixture
def suite(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> pytest.Pytester:
    """Create a fake complete test tree with no database or browser operations.

    Args:
        pytester: Pytest's isolated session builder.
        monkeypatch: Scoped environment overrides.

    Returns:
        An isolated runner containing the production gate and passing groups.
    """
    source = Path(__file__).with_name("conftest.py")
    with source.open(encoding="utf-8") as stream:
        pytester.makeconftest(stream.read())
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.setenv("POSTGRES_TEST_ADMIN_URL", ADMIN_URL)
    monkeypatch.setenv("POSTGRES_TEST_RUNTIME_URL", RUNTIME_URL)
    monkeypatch.setenv("EPPM_RUN_OIDC_E2E", "1")
    _write(pytester.path / "tests/postgresql/test_database.py", PASSING_TEST)
    _write(pytester.path / "tests/test_oidc_browser_e2e.py", PASSING_TEST)
    return pytester


def test_full_suite_accepts_execution_of_both_required_groups(
    suite: pytest.Pytester,
) -> None:
    """Accept a successful complete run with valid prerequisite names."""
    result = suite.runpytest_subprocess("--require-full-suite", "-q")

    result.assert_outcomes(passed=2)
    assert result.ret == pytest.ExitCode.OK


@pytest.mark.parametrize(
    "name,value",
    [
        ("POSTGRES_TEST_ADMIN_URL", None),
        ("POSTGRES_TEST_RUNTIME_URL", None),
        ("POSTGRES_TEST_ADMIN_URL", " "),
        ("POSTGRES_TEST_RUNTIME_URL", ""),
        ("EPPM_RUN_OIDC_E2E", None),
        ("EPPM_RUN_OIDC_E2E", "0"),
    ],
)
def test_full_suite_rejects_missing_prerequisites_without_values(
    suite: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str | None,
) -> None:
    """Report variable names without printing the values of other variables."""
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)

    result = suite.runpytest_subprocess("--require-full-suite", "-q")

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert name in result.stderr.str()
    assert ADMIN_URL not in result.stderr.str()
    assert RUNTIME_URL not in result.stderr.str()


@pytest.mark.parametrize(
    "selection,missing",
    [
        ("tests/postgresql", "authenticated browser"),
        ("tests/test_oidc_browser_e2e.py", "PostgreSQL"),
        ("-k database", "authenticated browser"),
    ],
)
def test_full_suite_rejects_missing_or_deselected_required_groups(
    suite: pytest.Pytester, selection: str, missing: str
) -> None:
    """A passing partial run cannot claim to be full verification."""
    result = suite.runpytest_subprocess(
        "--require-full-suite", *selection.split(), "-q"
    )

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert missing in result.stderr.str()


@pytest.mark.parametrize("group", ["postgresql", "browser"])
@pytest.mark.parametrize(
    "phase", ["collection", "setup", "runtime", "teardown"]
)
def test_full_suite_fails_required_skips_in_every_phase(
    suite: pytest.Pytester, group: str, phase: str
) -> None:
    """Detect module, fixture, test-body, and teardown skips."""
    sources = {
        "collection": (
            "import pytest\n"
            "pytest.skip('fixture skip', allow_module_level=True)\n"
        ),
        "setup": (
            "import pytest\n@pytest.fixture(autouse=True)\n"
            "def resource():\n    pytest.skip('fixture skip')\n" + PASSING_TEST
        ),
        "runtime": (
            "import pytest\ndef test_skip():\n"
            "    pytest.skip('fixture skip')\n"
        ),
        "teardown": (
            "import pytest\n@pytest.fixture(autouse=True)\n"
            "def resource():\n    yield\n    pytest.skip('fixture skip')\n"
            + PASSING_TEST
        ),
    }
    if group == "postgresql":
        target = suite.path / "tests/postgresql/test_skipped.py"
    else:
        target = suite.path / "tests/test_oidc_browser_e2e.py"
    _write(target, sources[phase])

    result = suite.runpytest_subprocess("--require-full-suite", "-q")

    assert result.ret != pytest.ExitCode.OK
    assert "Required full-suite tests skipped" in result.stdout.str()


def test_full_suite_allows_unrelated_conditional_skips(
    suite: pytest.Pytester,
) -> None:
    """An optional module skip does not fail the required groups."""
    _write(
        suite.path / "tests/test_optional.py",
        "import pytest\n"
        "pytest.skip('optional platform', allow_module_level=True)\n",
    )

    result = suite.runpytest_subprocess("--require-full-suite", "-q")

    result.assert_outcomes(passed=2, skipped=1)
    assert result.ret == pytest.ExitCode.OK


@pytest.mark.parametrize("strict", [False, True])
def test_gate_preserves_existing_test_failure_status(
    suite: pytest.Pytester, strict: bool
) -> None:
    """A required skip must never turn an actual failing run into success."""
    _write(
        suite.path / "tests/test_failure.py",
        "def test_failure():\n    assert False\n",
    )
    _write(
        suite.path / "tests/postgresql/test_skip.py",
        "import pytest\ndef test_skip():\n    pytest.skip('fixture skip')\n",
    )

    options = ["--require-full-suite"] if strict else []
    result = suite.runpytest_subprocess(*options, "-q")

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.assert_outcomes(passed=2, failed=1, skipped=1)


def test_full_suite_preserves_collection_error_status(
    suite: pytest.Pytester,
) -> None:
    """Collection errors keep their original exit status and diagnostics."""
    _write(
        suite.path / "tests/test_broken.py",
        "raise ValueError('collection failure')\n",
    )

    result = suite.runpytest_subprocess("--require-full-suite", "-q")

    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert "collection failure" in result.stdout.str()


def test_ordinary_partial_run_retains_skip_behavior_without_prerequisites(
    suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Normal pytest remains useful without infrastructure or strict mode."""
    names = (
        "POSTGRES_TEST_ADMIN_URL",
        "POSTGRES_TEST_RUNTIME_URL",
        "EPPM_RUN_OIDC_E2E",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    _write(
        suite.path / "tests/postgresql/test_skip.py",
        "import pytest\ndef test_skip():\n    pytest.skip('fixture skip')\n",
    )

    result = suite.runpytest_subprocess("tests/postgresql", "-q")

    result.assert_outcomes(passed=1, skipped=1)
    assert result.ret == pytest.ExitCode.OK


def test_full_suite_rejects_collection_only_as_acceptance(
    suite: pytest.Pytester,
) -> None:
    """Collecting tests without executing them cannot satisfy the gate."""
    result = suite.runpytest_subprocess(
        "--require-full-suite", "--collect-only", "-q"
    )

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "requires test execution" in result.stderr.str()
