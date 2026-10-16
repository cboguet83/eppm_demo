"""Enforce complete PostgreSQL and browser verification when requested."""

import os

import pytest


REQUIRED_GROUPS = ("PostgreSQL", "authenticated browser")


def _required_group(nodeid: str) -> str | None:
    """Classify only the repository's required integration test paths."""
    path = nodeid.replace("\\", "/").split("::", 1)[0]
    if path.startswith("tests/postgresql/"):
        return "PostgreSQL"
    if path == "tests/test_oidc_browser_e2e.py":
        return "authenticated browser"
    return None


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the full verification gate without changing ordinary runs.

    Args:
        parser: Pytest's command-line option parser.
    """
    parser.addoption(
        "--require-full-suite",
        action="store_true",
        help="Require PostgreSQL/browser prerequisites, collection, no skips.",
    )
    parser.addoption(
        "--postgres-test-db-mode",
        choices=("fresh", "template"),
        default="fresh",
        help="Prepare PostgreSQL tests through fresh migrations or clones.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Enable strict verification only when explicitly requested.

    Args:
        config: The current pytest configuration.

    Raises:
        pytest.UsageError: Required prerequisites are missing or invalid.
    """
    if not config.getoption("--require-full-suite"):
        return

    required_urls = ("POSTGRES_TEST_ADMIN_URL", "POSTGRES_TEST_RUNTIME_URL")
    missing = [
        name for name in required_urls if not os.environ.get(name, "").strip()
    ]
    if os.environ.get("EPPM_RUN_OIDC_E2E") != "1":
        missing.append("EPPM_RUN_OIDC_E2E=1")
    if missing:
        raise pytest.UsageError(
            "--require-full-suite requires: " + ", ".join(missing)
        )
    if config.option.collectonly:
        raise pytest.UsageError(
            "--require-full-suite requires test execution."
        )
    config.pluginmanager.register(_FullSuiteGate(), "eppm-full-suite-gate")


class _FullSuiteGate:
    """Track required collection and skips within one pytest session."""

    _skipped: set[str]

    def __init__(self) -> None:
        """Initialize session-local state without application dependencies."""
        self._skipped = set()

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        """Require both critical groups after selection and deselection.

        Args:
            session: The collected pytest session.

        Raises:
            pytest.UsageError: A required integration group was not collected.
        """
        if session.testsfailed:
            return
        groups = {_required_group(item.nodeid) for item in session.items}
        missing = [name for name in REQUIRED_GROUPS if name not in groups]
        if missing:
            raise pytest.UsageError(
                "--require-full-suite did not collect required groups: "
                + ", ".join(missing)
            )

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        """Record required modules skipped during import or collection.

        Args:
            report: A collection outcome supplied by pytest.
        """
        self._record_skip(report)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Record required tests skipped in setup, execution, or teardown.

        Args:
            report: A test phase outcome supplied by pytest.
        """
        self._record_skip(report)

    def _record_skip(
        self, report: pytest.CollectReport | pytest.TestReport
    ) -> None:
        """Store identifiers without environment values or skip reasons."""
        if report.skipped and _required_group(report.nodeid):
            self._skipped.add(report.nodeid)

    def pytest_sessionfinish(
        self, session: pytest.Session, exitstatus: int
    ) -> None:
        """Fail a successful session containing required skips.

        Args:
            session: The completed pytest session.
            exitstatus: Original status, preserved when already failing.
        """
        if exitstatus == pytest.ExitCode.OK and self._skipped:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(
        self, terminalreporter: pytest.TerminalReporter
    ) -> None:
        """Explain strict skip failures using test identifiers only.

        Args:
            terminalreporter: Pytest's terminal output interface.
        """
        if not self._skipped:
            return
        terminalreporter.write_sep("=", "Required full-suite tests skipped")
        for nodeid in sorted(self._skipped):
            terminalreporter.write_line(nodeid)
