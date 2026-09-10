"""Typed relational property values shared by migrations, projects, and templates.

Callers own the connection and transaction. A missing row means absent; a row
with kind ``null`` or ``empty`` records an explicitly cleared scalar value.
Flexible dictionaries here support legacy migration inputs and SQL row metadata;
project use cases expose typed records and validate values through the domain.
"""

import json
import sqlite3
from typing import Any

from app.domain.projects.property_values import encode_property_value
from app.domain.projects.project_types import resolve_template


def parameters(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cursor = conn.execute("SELECT * FROM schema_parameters ORDER BY param_id")
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def resolve_keys(conn: sqlite3.Connection, values: dict[str, Any]) -> dict[str, Any]:
    """Resolve legacy names/aliases without silently losing ambiguous values."""
    definitions = parameters(conn)
    ids = {p["param_id"] for p in definitions}
    result = {}
    for key, value in values.items():
        if key in ids:
            pid = key
        else:
            matches = [p["param_id"] for p in definitions if p["param_name"] == key]
            if not matches:
                matches = [p["param_id"] for p in definitions if p["alias"] and p["alias"] == key]
            if len(matches) != 1:
                raise ValueError(f"Unknown or ambiguous property key: {key!r}")
            pid = matches[0]
        if pid in result and result[pid] != value:
            raise ValueError(f"Conflicting values for property {pid}")
        result[pid] = value
    return result


def encode_value(conn: sqlite3.Connection, pid: str, value: Any) -> tuple:
    row = conn.execute("SELECT param_type FROM schema_parameters WHERE param_id = ?", (pid,)).fetchone()
    if not row:
        raise ValueError(f"Unknown property: {pid}")
    choices = {r[0] for r in conn.execute(
        "SELECT option_value FROM schema_param_options WHERE param_id = ?", (pid,)
    )}
    return encode_property_value(pid, row[0], value, choices)


def write_value(conn: sqlite3.Connection, owner_id: int, pid: str, value: Any, *, defaults: bool = False) -> None:
    table, owner = ("project_type_property_default", "project_type_id") if defaults else ("project_property_value", "project_id")
    kind, text, number, date, items = encode_value(conn, pid, value)
    conn.execute(f"DELETE FROM main.{table}_item WHERE {owner} = ? AND param_id = ?", (owner_id, pid))
    conn.execute(
        f"INSERT INTO main.{table} ({owner}, param_id, kind, text_value, number_value, date_value) VALUES (?, ?, ?, ?, ?, ?) "
        f"ON CONFLICT ({owner}, param_id) DO UPDATE SET kind=excluded.kind, text_value=excluded.text_value, number_value=excluded.number_value, date_value=excluded.date_value",
        (owner_id, pid, kind, text, number, date),
    )
    conn.executemany(f"INSERT INTO main.{table}_item ({owner}, param_id, position, value) VALUES (?, ?, ?, ?)",
                     [(owner_id, pid, i, item) for i, item in enumerate(items)])


def read_values(conn: sqlite3.Connection, *, defaults: bool = False, owner_id: int | None = None,
                param_ids: list[str] | None = None) -> dict[int, dict[str, Any]]:
    """Load all values in two queries, avoiding per-project portfolio queries."""
    table, owner = ("project_type_property_default", "project_type_id") if defaults else ("project_property_value", "project_id")
    where = f" WHERE {owner} = ?" if owner_id is not None else ""
    args = (owner_id,) if owner_id is not None else ()
    if param_ids is not None:
        if not param_ids:
            return {}
        where += (' AND ' if where else ' WHERE ') + 'param_id IN (SELECT value FROM json_each(?))'
        args += (json.dumps(param_ids),)
    result: dict[int, dict[str, Any]] = {}
    for oid, pid, kind, text, number, date in conn.execute(f"SELECT {owner}, param_id, kind, text_value, number_value, date_value FROM {table}{where}", args):
        result.setdefault(oid, {})[pid] = {"null": None, "empty": "", "list": [], "text": text, "number": number, "date": date}[kind]
    for oid, pid, value in conn.execute(f"SELECT {owner}, param_id, value FROM {table}_item{where} ORDER BY {owner}, param_id, position", args):
        result[oid][pid].append(value)
    return result


def effective_template(conn: sqlite3.Connection, type_id: int) -> list[dict[str, Any]]:
    if not conn.execute("SELECT 1 FROM project_type WHERE id = ?", (type_id,)).fetchone():
        raise ValueError("Unknown project type")
    selected = {r[0] for r in conn.execute("SELECT param_id FROM project_type_property WHERE project_type_id = ?", (type_id,))}
    overrides = dict(conn.execute("SELECT param_id, mandatory_override FROM project_type_property_rule WHERE project_type_id = ?", (type_id,)))
    defaults = read_values(conn, defaults=True, owner_id=type_id).get(type_id, {})
    return resolve_template(parameters(conn), selected, overrides, defaults)
