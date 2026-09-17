"""CSV catalog transfer with atomic hierarchy validation in Python."""

import csv
from dataclasses import dataclass, replace
from io import StringIO

from app.application.ports.resource_pools import ResourcePoolStore
from app.domain.resources.hierarchy import PoolHierarchy
from app.domain.resources.models import ResourcePool
from app.domain.resources.rules import normalize_pool

CSV_COLUMNS = ('pool_id', 'name', 'description', 'capacity_fte', 'parent_pool_id',
               'pool_type_id', 'hierarchy_type_id', 'deleted_flag')


@dataclass(frozen=True)
class PoolImportResult:
    """Counts of catalog records created and updated by a committed import."""

    created: int
    updated: int
    deactivated: int = 0


def export_pools(pools: list[ResourcePool]) -> str:
    """Serialize pool attributes; relationships and exceptions remain separate."""
    output = StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for pool in pools:
        writer.writerow({column: pool.id if column == 'pool_id' else
                         str(pool.deleted_flag).lower() if column == 'deleted_flag' else
                         getattr(pool, column) for column in CSV_COLUMNS})
    return output.getvalue()


def _identity(value: str, column: str) -> int | None:
    if not value:
        return None
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f'{column} must be a positive integer.') from error
    if result <= 0:
        raise ValueError(f'{column} must be a positive integer.')
    return result


def _parse_row(row: dict[str, str]) -> ResourcePool:
    deleted = row.get('deleted_flag', '').lower() or 'false'
    if deleted not in {'true', 'false', '1', '0'}:
        raise ValueError('deleted_flag must be true or false (or 1 or 0).')
    capacity = row.get('capacity_fte', '')
    try:
        capacity_fte = float(capacity) if capacity else None
    except ValueError as error:
        raise ValueError('capacity_fte must be a number or blank.') from error
    return normalize_pool(ResourcePool(
        name=row['name'], id=_identity(row.get('pool_id', ''), 'pool_id'),
        description=row.get('description', ''), capacity_fte=capacity_fte,
        parent_pool_id=_identity(row.get('parent_pool_id', ''), 'parent_pool_id'),
        pool_type_id=_identity(row.get('pool_type_id', ''), 'pool_type_id') or 1,
        hierarchy_type_id=_identity(row.get('hierarchy_type_id', ''), 'hierarchy_type_id'),
        deleted_flag=deleted in {'true', '1'},
    ))


def parse_pools(content: bytes) -> list[ResourcePool]:
    """Read UTF-8 comma/semicolon CSV and report invalid rows before writes."""
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise ValueError('The CSV must use UTF-8 encoding.') from error
    delimiter = ';' if ';' in text.partition('\n')[0] else ','
    reader = csv.DictReader(StringIO(text, newline=''), delimiter=delimiter, strict=True)
    try:
        columns = reader.fieldnames
    except csv.Error as error:
        raise ValueError(f'Invalid CSV header: {error}') from error
    if not columns or 'name' not in columns:
        raise ValueError('The CSV requires a name column. Download the template for the supported columns.')
    if len(set(columns)) != len(columns):
        raise ValueError('The CSV contains duplicate column headers.')
    result: list[ResourcePool] = []
    identities: set[int] = set()
    try:
        for number, row in enumerate(reader, start=2):
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('The number of values does not match the CSV header.')
                pool = _parse_row({key: value.strip() for key, value in row.items()})
                if pool.id is not None:
                    if pool.id in identities:
                        raise ValueError(f'Duplicate pool_id {pool.id}.')
                    identities.add(pool.id)
                result.append(pool)
            except ValueError as error:
                raise ValueError(f'Row {number}: {error}') from error
    except csv.Error as error:
        raise ValueError(f'Invalid CSV near line {reader.line_num}: {error}') from error
    if not result:
        raise ValueError('The CSV contains no pool records.')
    return result


def import_pools(store: ResourcePoolStore, pools: list[ResourcePool]) -> PoolImportResult:
    """Apply a complete batch inside the caller's authorized transaction.

    Unknown source IDs are aliases only: the database sequence supplies new IDs.
    Resolve the final forest before enforcing live-parent and leaf-only rules.
    Any failure rolls back every catalog write, including provisional new rows.
    """
    existing = {pool.id: pool for pool in store.get_all_pools(include_deleted=True)}
    source_ids = set(existing) | {pool.id for pool in pools if pool.id is not None}
    if any(pool.parent_pool_id is not None and pool.parent_pool_id not in source_ids for pool in pools):
        raise ValueError('A parent_pool_id is unknown: use an existing pool ID or a pool_id from this CSV.')
    aliases: dict[int, int] = {}
    resolved: list[ResourcePool] = []
    created = 0
    for pool in pools:
        identity = pool.id
        if identity not in existing:
            identity = store.create_pool(replace(pool, id=None, parent_pool_id=None))
            created += 1
        if pool.id is not None:
            aliases[pool.id] = identity
        resolved.append(replace(pool, id=identity))
    included = {pool.id for pool in resolved}
    omitted = {identity for identity, pool in existing.items() if identity not in included and not pool.deleted_flag}
    final = {identity: replace(pool, deleted_flag=True) if identity in omitted else pool
             for identity, pool in existing.items()}
    for pool in resolved:
        final[pool.id] = replace(pool, parent_pool_id=aliases.get(pool.parent_pool_id, pool.parent_pool_id))
    PoolHierarchy(final.values())
    active = PoolHierarchy(pool for pool in final.values() if not pool.deleted_flag)
    for identity in active.children:
        if active.children[identity]:
            final[identity] = replace(final[identity], capacity_fte=0.0)
    # Write parents and children as one snapshot; references can include retained
    # deleted parents, but the active forest above can never reference one.
    for identity, pool in final.items():
        if pool != existing.get(identity):
            store.write_imported_pool(pool)
    occupied = store.assigned_pool_ids()
    mapped = {mapping.pool_id for mapping in store.get_all_mappings()}
    containers = [identity for identity, children in active.children.items() if children]
    exceptions = {item.pool_id for item in store.capacity_exceptions(containers)}
    configured = occupied | mapped | exceptions
    for identity in containers:
        if identity in configured:
            raise ValueError(f'Cannot make "{final[identity].name}" a container: remove its project/task '
                             'assignments, resource mappings and capacity exceptions first.')
    # Invalidate former parents even when their stored attributes did not change.
    former_parents = {existing[pool.id].parent_pool_id for pool in resolved if pool.id in existing}
    for identity in former_parents - {None}:
        if final[identity] == existing[identity]:
            store.write_imported_pool(final[identity])
    return PoolImportResult(created, len(pools) - created, len(omitted))
