"""Enforce complete PostgreSQL and browser verification when requested."""

from collections import Counter
from collections.abc import Sequence
import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from xdist.workermanage import WorkerController


REQUIRED_GROUPS = ("PostgreSQL", "authenticated browser")
HEAVY_GROUP = "browser-benchmark-deployment"
HEAVY_MODULES = frozenset({
    "test_direct_employee_priority.py", "test_employee_functions.py",
    "test_employee_profile_cleanup.py", "test_mapping_allocation.py",
    "test_seeded_project_forms.py", "test_deployed_recovery.py",
    "test_parallel_resources.py", "test_full_suite.py",
    "test_full_suite_parallel.py", "test_test_scheduling.py",
    "test_parallel_coverage.py",
    "test_template_measurements.py",
    "test_planning_distributions.py", "test_planning_installed_consumers.py",
    "test_resource_grid_headers.py",
})


def _execution_group(nodeid: str) -> str | None:
    """Identify audited native browser, benchmark and deployment modules."""
    path = nodeid.replace("\\", "/").split("::", 1)[0]
    filename = path.rsplit("/", 1)[-1]
    if ("browser" in filename or "benchmark" in filename
            or filename in HEAVY_MODULES):
        return HEAVY_GROUP
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Group shared observers and native processes without deselection."""
    for item in items:
        group = _execution_group(item.nodeid)
        if group:
            item.add_marker(pytest.mark.xdist_group(name=group))


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_node_collection_finished(ids: Sequence[str]) -> None:
    """Reject conflicting groups at the controller before dispatch."""
    for nodeid in ids:
        group = _execution_group(nodeid)
        if group and not nodeid.endswith("@" + group):
            raise pytest.UsageError(
                "Heavy workloads cannot combine conflicting xdist groups."
            )


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
        default="template",
        help="Prepare PostgreSQL tests through fresh migrations or clones.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Bound parallel scheduling and enable explicitly requested strict proof.

    Args:
        config: The current pytest configuration.

    Raises:
        pytest.UsageError: Required prerequisites are missing or invalid.
    """
    config.addinivalue_line(
        "markers", "xdist_group(name): audited worker group",
    )
    workers = getattr(config.option, "numprocesses", 0)
    if workers and (workers != 2 or config.option.dist != "loadgroup"):
        raise pytest.UsageError(
            "Parallel test execution requires -n 2 --dist=loadgroup; "
            "use -n 0 for serial diagnostics."
        )
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
    if getattr(config.option, "numprocesses", 0):
        config.option.maxworkerrestart = 0
    config.pluginmanager.register(
        _FullSuiteGate(config), "eppm-full-suite-gate",
    )


class _FullSuiteGate:
    """Reconcile full collection, required skips and distributed completion."""

    _skipped: set[str]

    def __init__(self, config: pytest.Config) -> None:
        """Initialize session-local state without application dependencies."""
        self._skipped = set()
        self._config = config
        self._worker = hasattr(config, "workerinput")
        self._parallel = bool(
            getattr(config.option, "numprocesses", 0)
        ) and not self._worker
        self._expected: tuple[str, ...] | None = None
        self._collected_workers: set[str] = set()
        self._finished_workers: set[str] = set()
        self._completed: Counter[str] = Counter()
        self._calls: Counter[str] = Counter()
        self._setup_stopped: set[str] = set()
        self._issues: set[str] = set()

    def _check_collection(self, ids: Sequence[str]) -> None:
        groups = {_required_group(nodeid) for nodeid in ids}
        missing = [name for name in REQUIRED_GROUPS if name not in groups]
        if missing:
            raise pytest.UsageError(
                "--require-full-suite did not collect required groups: "
                + ", ".join(missing)
            )

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        """Require both critical groups after selection and deselection.

        Args:
            session: The collected pytest session.

        Raises:
            pytest.UsageError: A required integration group was not collected.
        """
        if session.testsfailed or self._worker or self._parallel:
            return
        self._check_collection([item.nodeid for item in session.items])

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(
        self, node: "WorkerController", ids: Sequence[str],
    ) -> None:
        """Compare complete ordered worker collections at the controller."""
        identity = node.gateway.id
        if identity in self._collected_workers:
            self._issues.add("Worker repeated collection")
        self._collected_workers.add(identity)
        current = tuple(ids)
        if len(set(current)) != len(current):
            self._issues.add("Collection contains duplicate test identifiers")
        if self._expected is None:
            self._expected = current
        elif self._expected != current:
            self._issues.add("Worker collections differ")
        try:
            self._check_collection(current)
        except pytest.UsageError as error:
            self._issues.add(str(error))

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(
        self, node: "WorkerController", error: object | None,
    ) -> None:
        """Require every original worker's completion and forwarded skips."""
        if error is not None:
            self._issues.add("Worker exited without successful completion")
            return
        self._finished_workers.add(node.gateway.id)
        proof = node.workeroutput.get("eppm_full_suite_skipped")
        if not isinstance(proof, list):
            self._issues.add("Worker omitted full-suite completion proof")
            return
        self._skipped.update(proof)

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
        if not self._parallel or hasattr(report, "context"):
            return
        if report.when == "setup" and not report.passed:
            self._setup_stopped.add(report.nodeid)
        if report.when == "call":
            self._calls[report.nodeid] += 1
        if report.when == "teardown":
            self._completed[report.nodeid] += 1


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
        if self._worker:
            # workeroutput is the documented dynamic xdist transport boundary.
            self._config.workeroutput["eppm_full_suite_skipped"] = sorted(
                self._skipped,
            )
            return
        if self._parallel:
            self._reconcile_completion()
        if exitstatus == pytest.ExitCode.OK and (
            self._skipped or self._issues
        ):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def _reconcile_completion(self) -> None:
        if not self._expected:
            self._issues.add("No complete worker collection was received")
        count = self._config.option.numprocesses
        if len(self._collected_workers) != count:
            self._issues.add("Not every worker supplied a collection")
        if self._finished_workers != self._collected_workers:
            self._issues.add("Not every collected worker finished")
        expected = set(self._expected or ())
        if set(self._completed) != expected:
            self._issues.add("Collected tests lack final reports")
        if any(value != 1 for value in self._completed.values()):
            self._issues.add("Tests completed more than once")
        calls = expected - self._setup_stopped
        if set(self._calls) != calls or any(
            value != 1 for value in self._calls.values()
        ):
            self._issues.add(
                "Test execution reports are missing or duplicated"
            )

    def pytest_terminal_summary(
        self, terminalreporter: pytest.TerminalReporter
    ) -> None:
        """Explain strict skip failures using test identifiers only.

        Args:
            terminalreporter: Pytest's terminal output interface.
        """
        if self._skipped:
            terminalreporter.write_sep(
                "=", "Required full-suite tests skipped",
            )
            for nodeid in sorted(self._skipped):
                terminalreporter.write_line(nodeid)
        if self._issues:
            terminalreporter.write_sep("=", "Full-suite completion failed")
            for issue in sorted(self._issues):
                terminalreporter.write_line(issue)
