"""Validate live resource references inside the caller's write transaction."""

from typing import Literal
from collections.abc import Collection

from psycopg import Connection, sql

type ResourceTable = Literal['team', 'function', 'employee', 'resource_pool', 'function_type', 'hierarchy_type']


def require_live_reference(connection: Connection, table: ResourceTable, identity: int | None) -> None:
    """Reject stale selections without discarding retained historical links."""
    if identity is None:
        return
    require_live_references(connection, table, [identity])


def require_live_references(connection: Connection, table: ResourceTable, identities: Collection[int]) -> None:
    """Validate a batch of resource selections with one bounded query."""
    if not identities:
        return
    key = 'id' if table in {'resource_pool', 'hierarchy_type'} else f'{table}_id'
    query = sql.SQL('SELECT count(*) FROM eppm.{} WHERE {}=ANY(%s::bigint[]) AND NOT deleted_flag').format(
        sql.Identifier(table), sql.Identifier(key))
    if connection.execute(query, (list(set(identities)),)).fetchone()[0] != len(set(identities)):
        raise ValueError(f'The selected {table.replace("_", " ")} no longer exists. Please refresh.')
