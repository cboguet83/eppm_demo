"""Scoped source fingerprints without a global business-write revision hotspot."""

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import cast

import psycopg

from app.application.exceptions import ProjectStorageError
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger


logger = get_logger(__name__)
type EntityRevision = tuple[int, str, int]


@dataclass(frozen=True)
class RevisionSnapshot:
    """Effective scope and source revisions read under one authorized snapshot.

    Actor/session identity remains server-side. Opaque digests are comparison
    tokens, never permission to read a response without current authorization.
    """

    identity: tuple[str, int, int, str] = field(repr=False)
    catalog: int
    security: int
    projects: tuple[EntityRevision, ...]
    dependencies: tuple[tuple[int, tuple[int, ...]], ...]
    pools: tuple[EntityRevision, ...]
    pool_sources: tuple[tuple[int, tuple[int, ...]], ...]
    pool_names: tuple[tuple[int, str], ...]

    @property
    def scope(self) -> tuple[int, ...]:
        """Return current visible project membership without hidden identities."""
        return tuple(project[0] for project in self.projects)

    @property
    def access_key(self) -> tuple:
        """Bind calculations to database incarnation, actor, catalogs and security."""
        return self.identity, self.catalog, self.security, self.scope

    def key(self) -> tuple:
        """Return complete display sources for the existing tuple-token contract."""
        return self.access_key, self.projects, self.dependencies, self.pools, self.pool_sources, self.pool_names

    def token(self) -> str:
        """Produce a compact opaque browser fingerprint without raw identifiers."""
        return _digest(self.key())

    def project_tokens(self) -> dict[int, str]:
        """Include visible predecessor generations without traversing cycles."""
        by_project = {row[0]: row for row in self.projects}
        sources = dict(self.dependencies)
        access = _digest(self.access_key)
        return {identity: _digest((access, row, tuple(by_project[source] for source in sources[identity])))
                for identity, row in by_project.items()}

    def pool_tokens(self) -> dict[int, str]:
        """Include pool configuration and only its visible consuming project data."""
        projects = {row[0]: row for row in self.projects}
        sources = dict(self.pool_sources)
        access = _digest(self.access_key)
        return {row[0]: _digest((access, row, tuple(projects[source] for source in sources[row[0]])))
                for row in self.pools}

    def task_tokens(self, project_ids: list[int], task_pools: set[tuple[int, int]]) -> dict[int, str]:
        """Include pool labels for project links and full capacity sources for tasks."""
        selected = set(project_ids)
        projects = self.project_tokens()
        pools = self.pool_tokens()
        configurations = {row[0]: _digest(('planning.pool.v1', row)) for row in self.pools}
        assigned = {identity: [] for identity in selected if identity in projects}
        for pool_id, consumers in self.pool_sources:
            for identity in consumers:
                if identity in assigned:
                    token = pools[pool_id] if (identity, pool_id) in task_pools else configurations[pool_id]
                    assigned[identity].append((pool_id, token))
        return {identity: _digest(('planning.tasks.v2', projects[identity], tuple(sorted(sources))))
                for identity, sources in assigned.items()}


def _digest(value: tuple) -> str:
    """Match PostgreSQL JSONB array formatting for database-checked fingerprints."""
    return sha256(json.dumps(value, ensure_ascii=False).encode('utf-8')).hexdigest()


def read_task_pool_pairs(connection: psycopg.Connection, project_ids: list[int]) -> set[tuple[int, int]]:
    """Read task allocation ownership in the caller's authorized revision snapshot."""
    return set(connection.execute('SELECT DISTINCT project_id,pool_id FROM eppm.current_resource_pool_assignment '
                                  'WHERE project_id=ANY(%s::bigint[]) AND task_id IS NOT NULL', (project_ids,)).fetchall())


def read_revisions(connection: psycopg.Connection, access: BusinessAccess) -> RevisionSnapshot:
    """Read protected revision metadata on a caller's already-bound connection."""
    # run_business has already validated the actual actor. JSON is the dynamic
    # driver boundary; the fixed SQL function owns this complete record shape.
    actor = cast(Actor, access.actor)
    payload = connection.execute('SELECT eppm.display_cache_revisions()').fetchone()[0]
    projects = tuple((row[0], row[1], row[2]) for row in payload['projects'])
    pools = tuple((row[0], row[1], row[2]) for row in payload['pools'])
    return RevisionSnapshot(
        (payload['epoch'], payload['database_oid'], actor.user_id, actor.session_hash),
        payload['catalog'], payload['security'], projects,
        tuple((row[0], tuple(row[3])) for row in payload['projects']), pools,
        tuple((row[0], tuple(row[4])) for row in payload['pools']),
        tuple((row[0], row[3]) for row in payload['pools']),
    )


def snapshot(database: Database, key: bytes, access: BusinessAccess) -> RevisionSnapshot:
    """Reauthorize every source-key lookup and translate unavailable metadata safely."""
    try:
        return run_business(database, key, access, lambda connection: read_revisions(connection, access))
    except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
        logger.error('Display revision read failed (%s)', type(error).__name__)
        raise ProjectStorageError('Project display data could not be accessed. Please try again.') from None
