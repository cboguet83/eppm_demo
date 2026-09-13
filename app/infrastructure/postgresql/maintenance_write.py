"""Pre-operation archives outside bounded, replayable operator mutations."""

from collections.abc import Callable

import psycopg

from app.application.exceptions import DatabaseMaintenanceError
from app.infrastructure.postgresql.backup import PostgresBackup
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.seed_plan import source_fingerprint
from app.shared.logging import get_logger


logger = get_logger(__name__)


def backed_up_write[Result](database: OperatorDatabase, backup: PostgresBackup, *, reason: str,
                            fingerprint: str, operation: Callable[[psycopg.Connection], Result]) -> Result:
    """Archive once, then recheck frozen sources before every complete attempt.

    Callers prepare and freeze command inputs before entering this boundary.
    Failed archives prevent mutations. Serialization failures can replay database
    work; external archive creation and uncertain commits are never replayed.
    """
    def apply(connection: psycopg.Connection) -> Result:
        if source_fingerprint(connection) != fingerprint:
            raise ValueError('Database changed during preparation; rerun to prepare a fresh plan.')
        return operation(connection)

    try:
        backup.create(reason)
        return database.run(apply, write=True)
    except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError, OSError) as error:
        logger.error('PostgreSQL maintenance failed (%s)', type(error).__name__)
        raise DatabaseMaintenanceError('Database maintenance could not complete. Any pre-operation backup is retained.') from None
