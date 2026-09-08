"""Connection lifetime and safe error translation for project storage."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager

from app.application.exceptions import ProjectConflictError, ProjectStorageError
from app.infrastructure.database.connection import get_db
from app.shared.logging import get_logger

logger = get_logger(__name__)


@contextmanager
def project_connection(db_path: str | None, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    """Commit or roll back one snapshot and always close its connection."""
    try:
        with closing(get_db(db_path)) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
    except sqlite3.IntegrityError as exc:
        raise ProjectConflictError("The project change conflicts with an existing reference or constraint") from exc
    except sqlite3.DatabaseError as exc:
        logger.error("Project storage operation failed (%s)", type(exc).__name__)
        raise ProjectStorageError("Project data could not be accessed. Please try again.") from exc
