"""Minimal native budget report reads with Decimal euro amounts."""

import psycopg

from app.application.exceptions import ProjectStorageError
from app.application.ports.budgets import ProjectBudget
from app.application.services.business_access import BusinessAccess
from app.domain.projects.budgets import BudgetAmounts
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger

logger = get_logger(__name__)


class PostgresBudgetReader:
    """Read a minimal, actor-visible reporting snapshot without project hydration."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the runtime pool, trusted server key and explicit actor policy."""
        self.database, self.key, self.access = database, key, access

    def read_budgets(self) -> list[ProjectBudget]:
        """Return native numeric amounts after row policies filter hidden projects."""
        def operation(connection: psycopg.Connection) -> list[ProjectBudget]:
            return [ProjectBudget(row[0], row[1], row[2], BudgetAmounts(row[3], row[4]))
                    for row in connection.execute('SELECT id,name,status,COALESCE(planned_budget,0),COALESCE(actual_budget,0) '
                                                  'FROM eppm.project ORDER BY id')]
        try:
            return run_business(self.database, self.key, self.access, operation)
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Budget storage operation failed (%s)', type(error).__name__)
            raise ProjectStorageError('Project data could not be accessed. Please try again.') from None
