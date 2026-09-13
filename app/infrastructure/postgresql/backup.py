"""Explicit PostgreSQL archives and transactional restoration into empty databases."""

from collections.abc import Callable
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from secrets import token_hex
import subprocess
from typing import BinaryIO, Literal

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.pq import Conninfo

from app.application.exceptions import DatabaseMaintenanceError
from app.infrastructure.postgresql.errors import SchemaCompatibilityError
from app.infrastructure.postgresql.migration import check_schema
from app.shared.config.database import validate_database_url
from app.shared.logging import get_logger


logger = get_logger(__name__)
_FAILURE = 'Database backup or restore could not complete. Existing archives are retained.'
_RESTORE_LOCK = 4994576949004554829
_NONEMPTY = """SELECT
    EXISTS(SELECT 1 FROM pg_namespace WHERE nspname NOT IN ('public','information_schema') AND nspname !~ '^pg_')
    OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public')
    OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public')
    OR EXISTS(SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public')"""


class PostgresTools:
    """Run installed PostgreSQL clients without secrets in argv or diagnostic output.

    A trusted operator may supply a command prefix for a local container client.
    Commands are argument lists, never shell source. No operation is retried.
    """

    def __init__(self, prefix: tuple[str, ...] = (), *, timeout: float = 600) -> None:
        """Inject a deployment-owned client transport and a finite execution limit."""
        if type(timeout) not in {int, float} or not 0 < timeout <= 3600:
            raise ValueError('PostgreSQL tool timeout must be between zero and 3600 seconds.')
        self.prefix, self.timeout = tuple(prefix), timeout

    def _environment(self, url: str | None) -> dict[str, str]:
        """Replace inherited libpq defaults with explicit, validated connection values."""
        environment = {name: value for name, value in os.environ.items() if not name.startswith('PG')}
        if url is None:
            return environment
        validate_database_url(url)
        names = {option.keyword.decode(): option.envvar.decode() for option in Conninfo.get_defaults() if option.envvar}
        for key, value in conninfo_to_dict(url).items():
            if key not in names:
                raise ValueError('PostgreSQL client connection option is unsupported.')
            environment[names[key]] = value
        environment.setdefault('PGCONNECT_TIMEOUT', '5')
        return environment

    def run(self, tool: Literal['pg_dump', 'pg_restore'], arguments: tuple[str, ...], *,
            url: str | None = None, source: BinaryIO | None = None, destination: BinaryIO | None = None) -> None:
        """Run a fixed client with bounded time and private connection environment."""
        if tool not in {'pg_dump', 'pg_restore'}:
            raise ValueError('Unsupported PostgreSQL archive tool.')
        try:
            result = subprocess.run(
                [*self.prefix, tool, *arguments], env=self._environment(url),
                stdin=source if source is not None else subprocess.DEVNULL,
                stdout=destination if destination is not None else subprocess.DEVNULL,
                stderr=subprocess.PIPE, timeout=self.timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired, psycopg.Error, ValueError) as error:
            logger.error('PostgreSQL archive client failed (%s)', type(error).__name__)
            raise DatabaseMaintenanceError(_FAILURE) from None
        if result.returncode:
            logger.error('PostgreSQL archive client failed (exit %s)', result.returncode)
            raise DatabaseMaintenanceError(_FAILURE)


class PostgresBackup:
    """Create complete custom-format archives before explicit operator mutations."""

    def __init__(self, url: str, directory: Path, *, tools: PostgresTools | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        """Inject operator credentials, archive directory, client transport and clock."""
        validate_database_url(url)
        self._url, self.directory = url, directory.resolve()
        self.tools, self.clock = tools or PostgresTools(), clock

    def create(self, reason: str = 'seed') -> Path:
        """Publish an exclusive archive only after successful dump and format checks.

        PostgreSQL's dump snapshot includes committed data consistently. Ownership,
        grants, row policies and immutable records are retained. Failed attempts
        keep an explicitly incomplete file and never replace an existing archive.
        """
        if not isinstance(reason, str) or re.fullmatch('[a-z0-9-]{1,48}', reason) is None:
            raise ValueError('Use a short archive reason containing lowercase letters, digits and hyphens.')
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            name = f'eppm-before-{reason}-{self.clock():%Y%m%d-%H%M%S-%f}-{token_hex(8)}'
            partial, complete = self.directory / f'{name}.incomplete', self.directory / f'{name}.dump'
            descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as output:
                self.tools.run('pg_dump', ('--format=custom', '--no-password'), url=self._url, destination=output)
                output.flush()
                os.fsync(output.fileno())
            with partial.open('rb') as source:
                self.tools.run('pg_restore', ('--list',), source=source)
            # Linking is exclusive on both supported platforms; an existing file
            # cannot be overwritten between a path check and publication.
            os.link(partial, complete)
            partial.unlink()
        except OSError as error:
            logger.error('PostgreSQL archive file operation failed (%s)', type(error).__name__)
            raise DatabaseMaintenanceError(_FAILURE) from None
        logger.info('PostgreSQL archive created: %s', complete)
        return complete


def restore_database(archive: Path, target_url: str, *, tools: PostgresTools | None = None) -> None:
    """Restore into an explicitly supplied empty database and check compatibility.

    No database is created, cleared or dropped here. The single restore
    transaction retains owners, grants, row security and immutable history. A
    target-specific operator lock serializes these restoration attempts; native
    restore conflicts still fail atomically if another tool changes the target.
    """
    validate_database_url(target_url)
    options = conninfo_to_dict(target_url)
    if options.get('dbname') in {'postgres', 'template0', 'template1'}:
        raise ValueError('Restore requires a separate empty application database.')
    client = tools or PostgresTools()
    try:
        with archive.open('rb') as source, psycopg.connect(target_url, autocommit=True, connect_timeout=5) as connection:
            connection.execute("SET statement_timeout='10s'")
            connection.execute('SELECT pg_advisory_lock(%s)', (_RESTORE_LOCK,))
            if connection.execute(_NONEMPTY).fetchone()[0]:
                raise ValueError('Restore requires a separate empty application database.')
            client.run('pg_restore', ('--single-transaction', '--exit-on-error', '--no-password',
                       '--dbname', options['dbname']), url=target_url, source=source)
            check_schema(connection)
    except (OSError, psycopg.Error, SchemaCompatibilityError) as error:
        logger.error('PostgreSQL restoration failed (%s)', type(error).__name__)
        raise DatabaseMaintenanceError(_FAILURE) from None
