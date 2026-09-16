"""Disposable PostgreSQL snapshots for operator-run planning diagnostics.

These component diagnostics use a synthetic identity only inside their restored
copy. They do not measure OIDC login or authenticated multi-user acceptance.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from secrets import token_bytes, token_urlsafe
from tempfile import TemporaryDirectory
from time import time
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from uuid import uuid4

from dotenv import load_dotenv
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.pq import Conninfo

from app.application.services.access import AccessService, AuthorizationPolicy, DeploymentAccessService, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import VerifiedIdentity
from app.infrastructure.postgresql.access import PostgresAccessGateway, PostgresDeploymentAccessGateway
from app.infrastructure.postgresql.authorization import ActorBinding, configure_signing_key
from app.infrastructure.postgresql.backup import PostgresBackup, PostgresTools, restore_database
from app.infrastructure.postgresql.migration import check_schema
from app.infrastructure.postgresql.pool import Database, OperatorDatabase
from app.runtime import RuntimeResources
from app.shared.config.database import DatabaseConfig, validate_database_url


@dataclass(frozen=True)
class BenchmarkContext:
    """Restricted resources and an actor confined to one disposable database."""

    resources: RuntimeResources = field(repr=False)
    access: BusinessAccess = field(repr=False)
    name: str

    def counts(self) -> tuple[int, int, int]:
        """Count visible projects, tasks and resource pools outside render timing."""
        return self.resources.database.run(
            lambda connection: connection.execute(
                'SELECT (SELECT count(*) FROM eppm.project), '
                '(SELECT count(*) FROM eppm.current_project_task), '
                '(SELECT count(*) FROM eppm.resource_pool)'
            ).fetchone(), bind=ActorBinding(self.access, self.resources.key),
        )

    def project_ids(self, limit: int) -> list[int]:
        """Select a deterministic visible project set; zero means all projects."""
        if type(limit) is not int or limit < 0:
            raise ValueError('Project count must be a nonnegative integer.')
        return self.resources.database.run(
            lambda connection: [row[0] for row in connection.execute(
                'SELECT id FROM eppm.project ORDER BY id LIMIT %s', (limit or None,)
            )], bind=ActorBinding(self.access, self.resources.key),
        )

    def task_id(self, requested: int | None = None) -> int:
        """Resolve an existing task, preferring one with resource assignments."""
        if requested is not None and (type(requested) is not int or requested <= 0):
            raise ValueError('Task reference must be a positive integer.')
        row = self.resources.database.run(
            lambda connection: connection.execute(
                'SELECT t.id FROM eppm.current_project_task t WHERE %s::bigint IS NULL OR t.id=%s '
                'ORDER BY EXISTS(SELECT 1 FROM eppm.current_resource_pool_assignment a '
                'WHERE a.task_id=t.id) DESC, t.id LIMIT 1', (requested, requested)
            ).fetchone(), bind=ActorBinding(self.access, self.resources.key),
        )
        if row is None:
            raise ValueError('No matching task is available for the modal benchmark.')
        return row[0]


class _ContainerClients(PostgresTools):
    """Use the explicitly selected database container's local archive clients."""

    def __init__(self, container: str) -> None:
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', container) is None:
            raise ValueError('Specify a valid local PostgreSQL container name.')
        variables = sorted({option.envvar.decode() for option in Conninfo.get_defaults() if option.envvar})
        super().__init__(('docker', 'exec', '-i', *(part for name in variables for part in ('--env', name)), container))

    def _environment(self, url: str | None) -> dict[str, str]:
        return super()._environment(url) | {'PGHOST': '127.0.0.1', 'PGPORT': '5432'}


def add_database_arguments(parser: ArgumentParser) -> None:
    """Add explicit operator configuration without accepting credentials in argv."""
    parser.add_argument('--env-file', help='Ignored environment file, loaded only when specified')
    parser.add_argument('--client-container', help='Use clients inside this PostgreSQL server container')


def configured_benchmark(arguments: Namespace) -> AbstractContextManager[BenchmarkContext]:
    """Load the selected environment and construct an isolated benchmark context."""
    if arguments.env_file:
        load_dotenv(arguments.env_file, override=True)
    tools = _ContainerClients(arguments.client_container) if arguments.client_container else PostgresTools()
    return isolated_benchmark(os.environ.get('DATABASE_OPERATOR_URL', ''),
                              os.environ.get('DATABASE_URL', ''), tools=tools)


def _validate_sources(operator_url: str, runtime_url: str) -> None:
    for url in (operator_url, runtime_url):
        validate_database_url(url)
        # A path replacement must not be overridden by libpq query coordinates.
        if {'dbname', 'host', 'hostaddr', 'port', 'user', 'password'} & dict(parse_qsl(urlsplit(url).query)).keys():
            raise ValueError('Put database connection coordinates in the URL authority and path.')
    operator, runtime = conninfo_to_dict(operator_url), conninfo_to_dict(runtime_url)
    if (any(operator.get(key) != runtime.get(key) for key in ('host', 'hostaddr', 'port', 'dbname'))
            or operator.get('user') == runtime.get('user')):
        raise ValueError('Use separate operator and runtime users for the same source database.')
    if operator['dbname'] in {'postgres', 'template0', 'template1'}:
        raise ValueError('Select an application database as the benchmark source.')


def _copy_url(original: str, name: str) -> str:
    return urlunsplit(urlsplit(original)._replace(path=f'/{name}'))


def _benchmark_access(resources: RuntimeResources, operator_url: str) -> BusinessAccess:
    clock = lambda: int(time())
    policy = AuthorizationPolicy(clock, SessionLimits())
    service = AccessService(PostgresAccessGateway(resources.database, resources.key, policy),
                            policy, 'https://benchmark.example.invalid', lambda: token_urlsafe(32))
    now = clock()
    cookie = service.sign_in(VerifiedIdentity(service.issuer, uuid4().hex, '',
                                              'Isolated benchmark', now, now + 3600, True))
    actor = service.actor(cookie)
    deployment = DeploymentAccessService(PostgresDeploymentAccessGateway(OperatorDatabase(operator_url)),
                                         clock, 'isolated-benchmark', lambda: token_urlsafe(16))
    deployment.recover(actor.user_id, 'Synthetic diagnostic identity in a disposable restored database only')
    service.grant(actor, actor.user_id, 'business_admin', {'kind': 'all'})
    return BusinessAccess(actor, policy)


@contextmanager
def isolated_benchmark(operator_url: str, runtime_url: str, *,
                       tools: PostgresTools | None = None) -> Iterator[BenchmarkContext]:
    """Restore a consistent snapshot, then drop only the database created here.

    Args:
        operator_url: Explicit source credentials with database creation rights.
        runtime_url: Restricted credentials for the same source database.
        tools: Installed PostgreSQL clients or an explicit local transport.

    The source is only inspected and dumped. Keys, identities, grants and business
    edits are changed solely in the copy. Cleanup also runs after render failures.
    """
    _validate_sources(operator_url, runtime_url)
    with psycopg.connect(operator_url, connect_timeout=5) as source:
        check_schema(source)
        owner = source.execute('SELECT pg_get_userbyid(datdba) FROM pg_database '
                               'WHERE datname=current_database()').fetchone()[0]
    name = 'eppm_benchmark_' + uuid4().hex
    maintenance = make_conninfo(operator_url, dbname='postgres')
    target_operator, target_runtime = _copy_url(operator_url, name), _copy_url(runtime_url, name)
    with TemporaryDirectory(prefix='eppm-benchmark-') as directory:
        archive = PostgresBackup(operator_url, Path(directory), tools=tools).create('benchmark')
        with psycopg.connect(maintenance, autocommit=True, connect_timeout=5) as connection:
            connection.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(owner)))
        try:
            restore_database(archive, target_operator, tools=tools)
            key = token_bytes(32)
            configure_signing_key(target_operator, key.hex())
            database = Database(DatabaseConfig(target_runtime, pool_min=1, pool_max=4))
            try:
                database.open()
                resources = RuntimeResources(database, key)
                yield BenchmarkContext(resources, _benchmark_access(resources, target_operator), name)
            finally:
                database.close()
        finally:
            # This locally generated name is never taken from an argument or URL.
            with psycopg.connect(maintenance, autocommit=True, connect_timeout=5) as connection:
                connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
