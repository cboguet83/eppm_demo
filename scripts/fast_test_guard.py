"""Reject real services and child processes in the explicitly partial fast lane.

The guard is a test hygiene check, not a sandbox for adversarial Python code.
Mocked boundaries remain usable; full pytest runs do not load this plugin.
"""

import inspect
from pathlib import Path
import socket
import sys

import psycopg
import pytest


_active = False
_patch: pytest.MonkeyPatch | None = None


def _deny_connection(*args: object, **kwargs: object) -> None:
    raise RuntimeError("Fast tests cannot connect to real services.")


def _audit(event: str, arguments: tuple[object, ...]) -> None:
    if _active and event in {"socket.connect", "subprocess.Popen", "os.system"}:
        raise RuntimeError("Fast tests cannot start processes or connect to services.")


def pytest_sessionstart(session: pytest.Session) -> None:
    """Activate resource guards before collection/import can start a service."""
    global _active, _patch
    sys.addaudithook(_audit)
    _patch = pytest.MonkeyPatch()
    _patch.setattr(socket, "create_connection", _deny_connection)
    _patch.setattr(psycopg, "connect", _deny_connection)
    _patch.setattr(psycopg.Connection, "connect", _deny_connection)
    _patch.setattr(psycopg.AsyncConnection, "connect", _deny_connection)
    _active = True


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_setup(fixturedef: pytest.FixtureDef, request: pytest.FixtureRequest) -> None:
    """Reject real service fixture owners, including dynamically requested ones."""
    source = inspect.getsourcefile(fixturedef.func)
    path = Path(source).as_posix() if source else ""
    if "/tests/postgresql/" in path or path.endswith("/test_oidc_browser_e2e.py"):
        raise pytest.UsageError("Real integration fixtures cannot run in the fast lane.")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Restore ordinary process behavior after this explicitly selected lane."""
    global _active
    _active = False
    if _patch is not None:
        _patch.undo()
