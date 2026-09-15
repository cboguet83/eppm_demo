"""Atomic, operator-only conversion of legacy groups into a pool forest."""

from collections import defaultdict

import psycopg

from app.infrastructure.postgresql.errors import MigrationError


def convert_pool_groups(connection: psycopg.Connection) -> None:
    """Validate all legacy links before converting; never choose a parent silently.

    Args:
        connection: Operator transaction holding the migration lock.

    Raises:
        MigrationError: Memberships, names or cycles need an explicit data decision.
    """
    connection.execute("LOCK TABLE eppm.resource_pool_group, eppm.resource_pool_group_member IN ACCESS EXCLUSIVE MODE")
    groups = connection.execute(
        "SELECT id,name,description,created_at,hierarchy_type_id FROM eppm.resource_pool_group ORDER BY id"
    ).fetchall()
    pools = dict(connection.execute("SELECT id,name FROM eppm.resource_pool").fetchall())
    edges = connection.execute(
        "SELECT group_id,pool_id,child_group_id FROM eppm.resource_pool_group_member ORDER BY id"
    ).fetchall()
    parents: dict[tuple[str, int], set[int]] = defaultdict(set)
    for parent, pool, child in edges:
        parents[("pool", pool) if pool is not None else ("group", child)].add(parent)
    conflicts = [f"{kind} #{identity}: parent groups {sorted(values)}"
                 for (kind, identity), values in parents.items() if len(values) > 1]
    conflicts.extend(f"group #{identity}: name already used by a pool"
                     for identity, name, *_ in groups if name in pools.values())
    for identity, *_ in groups:
        visited: set[int] = set()
        current = identity
        while current is not None:
            if current in visited:
                conflicts.append(f"group #{identity}: circular parent links")
                break
            visited.add(current)
            current = next(iter(parents.get(("group", current), set())), None)
    if conflicts:
        raise MigrationError("Pool hierarchy migration blocked; no changes applied. "
                             "Resolve these conflicts first: " + "; ".join(conflicts))
    converted: dict[int, int] = {}
    for identity, name, description, created_at, hierarchy_type in groups:
        converted[identity] = connection.execute(
            "INSERT INTO eppm.resource_pool(name,description,created_at,hierarchy_type_id) "
            "VALUES (%s,%s,%s,%s) RETURNING id", (name, description, created_at, hierarchy_type)
        ).fetchone()[0]
    for parent, pool, child in edges:
        connection.execute("UPDATE eppm.resource_pool SET parent_pool_id=%s WHERE id=%s",
                           (converted[parent], pool if pool is not None else converted[child]))
    connection.execute("DROP TABLE eppm.resource_pool_group_member")
    connection.execute("DROP TABLE eppm.resource_pool_group")
    connection.execute("DROP FUNCTION eppm.guard_pool_group_cycle()")
