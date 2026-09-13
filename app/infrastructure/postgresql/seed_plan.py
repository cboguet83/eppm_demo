"""Read-only operator plans and source fingerprints for backed-up application."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json

import psycopg
from psycopg import sql


type SeedValue = str | int | float | date | None


@dataclass(frozen=True)
class SeedInsert:
    """One immutable native insert prepared by trusted operator code."""

    table: str
    columns: tuple[str, ...]
    values: tuple[SeedValue, ...]

    def apply(self, connection: psycopg.Connection) -> None:
        """Execute parameterized values with safely quoted fixed identifiers."""
        connection.execute(sql.SQL('INSERT INTO eppm.{} ({}) VALUES ({})').format(
            sql.Identifier(self.table), sql.SQL(',').join(map(sql.Identifier, self.columns)),
            sql.SQL(',').join(sql.Placeholder() for _ in self.values)), self.values)


def next_seed_identity(connection: psycopg.Connection, table: str) -> int:
    """Read a provisional identity without consuming or rewinding a sequence."""
    sequence = connection.execute('SELECT pg_get_serial_sequence(%s,%s)', (f'eppm.{table}', 'id')).fetchone()[0]
    schema, name = sequence.split('.', 1)
    last, called = connection.execute(sql.SQL('SELECT last_value,is_called FROM {}.{}').format(
        sql.Identifier(schema), sql.Identifier(name))).fetchone()
    maximum = connection.execute(sql.SQL('SELECT coalesce(max(id),0) FROM eppm.{}').format(sql.Identifier(table))).fetchone()[0]
    return max(last + int(called), maximum + 1)


def source_fingerprint(connection: psycopg.Connection) -> str:
    """Hash operator business sources in the caller's consistent read snapshot.

    Sources include all project/pool generations, the shared catalog and
    installation markers. Authentication activity,
    retained finance history and derived-cache publication are not seed inputs.
    This token belongs to maintenance previews, not runtime stale-form handling.
    """
    identity = connection.execute('SELECT d.epoch::text,c.revision, '
        '(SELECT oid FROM pg_database WHERE datname=current_database()) '
        'FROM eppm.database_identity d CROSS JOIN eppm.catalog_cache_revision c').fetchone()
    projects = connection.execute('SELECT p.id,r.generation::text,r.revision FROM eppm.project p '
        'LEFT JOIN eppm.project_cache_revision r ON r.project_id=p.id ORDER BY p.id').fetchall()
    pools = connection.execute('SELECT p.id,r.generation::text,r.revision FROM eppm.resource_pool p '
        'LEFT JOIN eppm.pool_cache_revision r ON r.pool_id=p.id ORDER BY p.id').fetchall()
    if identity is None or any(row[1] is None for row in (*projects, *pools)):
        raise ValueError('Maintenance source metadata is unavailable.')
    markers = connection.execute('SELECT catalog FROM eppm.operator_seed_state ORDER BY catalog').fetchall()
    # PostgreSQL sequences are not transactional. A rolled-back attempt may
    # advance one without changing any committed source: it must remain replayable.
    return sha256(json.dumps((identity, projects, pools, markers), ensure_ascii=False).encode()).hexdigest()
