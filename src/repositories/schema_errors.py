"""SQLite exception compatibility for remaining schema repository callers."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.application.exceptions import SchemaConflictError, SchemaStorageError


@contextmanager
def legacy_schema_errors() -> Iterator[None]:
    """Retain historical database exception types outside the migrated core."""
    try:
        yield
    except SchemaConflictError as exc:
        raise sqlite3.IntegrityError(str(exc.__cause__ or exc)) from exc
    except SchemaStorageError as exc:
        if isinstance(exc.__cause__, sqlite3.DatabaseError):
            raise exc.__cause__ from None
        raise
