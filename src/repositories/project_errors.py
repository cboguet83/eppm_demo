"""Temporary SQLite exception compatibility for unmigrated callers."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.application.exceptions import ProjectConflictError, ProjectStorageError


@contextmanager
def legacy_project_errors() -> Iterator[None]:
    """Preserve historical exception types at the legacy repository boundary."""
    try:
        yield
    except ProjectConflictError as exc:
        raise sqlite3.IntegrityError(str(exc)) from exc
    except ProjectStorageError as exc:
        if isinstance(exc.__cause__, sqlite3.DatabaseError):
            raise exc.__cause__ from None
        raise
