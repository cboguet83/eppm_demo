"""Native source checks for task batches without full-portfolio graph expansion."""

from collections.abc import Callable

import psycopg

from app.application.exceptions import PlanningStorageError
from app.application.ports.planning_sources import PlanningDisplaySources
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.revisions import read_revisions
from app.shared.logging import get_logger


class PostgresPlanningSources:
    """Capture initial chart sources and reauthorize each bounded HTTP comparison."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the shared runtime pool and trusted request actor."""
        self.database, self.key, self.access = database, key, access

    def _run[Result](self, operation: Callable[[psycopg.Connection], Result], project_ids: list[int]) -> Result:
        try:
            return run_business(self.database, self.key, self.access, operation,
                                permission=Permission.READ, project_ids=project_ids)
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            get_logger(__name__).error('Planning source read failed (%s)', type(error).__name__)
            raise PlanningStorageError('Planning data could not be accessed. Please try again.') from None

    def capture(self, project_ids: list[int]) -> PlanningDisplaySources:
        """Bind chart cache identity and task fingerprints to one authorized snapshot."""
        def operation(connection: psycopg.Connection) -> PlanningDisplaySources:
            current = read_revisions(connection, self.access)
            return PlanningDisplaySources(current.key(), current.task_tokens(project_ids))
        return self._run(operation, project_ids)

    def read(self, project_ids: list[int]) -> dict[int, str]:
        """Read at most 25 task-project sources, including shared pool consumers."""
        return self._run(lambda connection: dict(connection.execute(
            'SELECT * FROM eppm.planning_task_source_keys(%s::bigint[])', (project_ids,),
        ).fetchall()), project_ids)
