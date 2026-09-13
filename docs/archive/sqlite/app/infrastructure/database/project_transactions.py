"""Connection lifetime and safe error translation for project storage."""

import sqlite3
from collections.abc import Collection, Iterator
from app.domain.access.models import Permission
from contextlib import closing, contextmanager

from app.application.exceptions import ProjectConflictError, ProjectStorageError
from app.application.services.business_access import BusinessAccess
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.business_security import authorized_business_transaction
from app.shared.logging import get_logger

logger = get_logger(__name__)


@contextmanager
def project_connection(db_path: str | None, *, access: BusinessAccess, write: bool = False, permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Iterator[sqlite3.Connection]:
    """Commit or roll back one snapshot and always close its connection."""
    try:
        with closing(get_db(db_path)) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                with authorized_business_transaction(connection, access, permission=permission, project_ids=project_ids):
                    yield connection
    except sqlite3.IntegrityError as exc:
        raise ProjectConflictError("The project change conflicts with an existing reference or constraint") from exc
    except sqlite3.DatabaseError as exc:
        logger.error("Project storage operation failed (%s)", type(exc).__name__)
        raise ProjectStorageError("Project data could not be accessed. Please try again.") from exc
