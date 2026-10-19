"""Reconcile full execution against a separately collected canonical manifest."""

import json
from pathlib import Path
from collections.abc import Sequence
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from xdist.workermanage import WorkerController


SUFFIX = "@browser-benchmark-deployment"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register explicit canonical collection output and execution reference."""
    parser.addoption("--write-full-manifest", type=Path)
    parser.addoption("--full-manifest", type=Path)


def pytest_configure(config: pytest.Config) -> None:
    """Install independent collection reconciliation when a reference is given."""
    reference = config.getoption("--full-manifest")
    if reference is not None:
        with reference.open(encoding="utf-8") as stream:
            expected = json.load(stream)
        if (not isinstance(expected, list) or not expected
                or any(not isinstance(value, str) for value in expected)
                or len(set(expected)) != len(expected)):
            raise pytest.UsageError("Invalid canonical full-suite manifest.")
        config.pluginmanager.register(_ManifestProof(expected, config), "full-manifest-proof")


def pytest_collection_finish(session: pytest.Session) -> None:
    """Write reference IDs only after a successful unfiltered serial collection."""
    target = session.config.getoption("--write-full-manifest")
    if target is None:
        return
    if session.testsfailed or not session.config.option.collectonly:
        raise pytest.UsageError("Canonical manifest requires successful collection only.")
    ids = [item.nodeid for item in session.items]
    if not ids or len(ids) != len(set(ids)):
        raise pytest.UsageError("Canonical collection is empty or duplicated.")
    with target.open("x", encoding="utf-8") as stream:
        json.dump(ids, stream)


class _ManifestProof:
    """Require each serial/worker collection to equal the independent reference."""

    expected: list[str]
    config: pytest.Config
    compared: set[str]
    mismatch: bool

    def __init__(self, expected: list[str], config: pytest.Config) -> None:
        self.expected = expected
        self.config = config
        self.compared: set[str] = set()
        self.mismatch = False

    def _compare(self, identity: str, ids: Sequence[str]) -> None:
        canonical = [value.removesuffix(SUFFIX) for value in ids]
        if identity in self.compared or canonical != self.expected:
            self.mismatch = True
        self.compared.add(identity)

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        """Reconcile serial execution; distributed workers report to controller."""
        if not getattr(self.config.option, "numprocesses", 0):
            self._compare("serial", [item.nodeid for item in session.items])

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(
        self, node: "WorkerController", ids: Sequence[str],
    ) -> None:
        """Reconcile every original worker's entire ordered collection."""
        self._compare(node.gateway.id, ids)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        """A matching required-group subset cannot become full acceptance."""
        if hasattr(self.config, "workerinput"):
            return
        expected_count = getattr(self.config.option, "numprocesses", 0) or 1
        if self.mismatch or len(self.compared) != expected_count:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            reporter = self.config.pluginmanager.get_plugin("terminalreporter")
            if reporter is not None:
                reporter.write_line("Full execution differs from canonical collection.")
