"""Typed relational property values shared by migrations, projects, and templates.

Callers own the connection and transaction. A missing row means absent; a row
with kind ``null`` or ``empty`` records an explicitly cleared scalar value.
"""

import datetime
import json
import math
import sqlite3
from typing import Any

from src.models.constants import PARAM_TYPES


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
    ptype = row[0]
    if ptype not in PARAM_TYPES:
        raise ValueError(f"{pid}: unsupported property type {ptype}")
    if value is None:
        return ("null", None, None, None, [])
    if value == "":
        return ("empty", None, None, None, [])
    choices = {r[0] for r in conn.execute("SELECT option_value FROM schema_param_options WHERE param_id = ?", (pid,))}
    if ptype in ("MULTI_ENUM", "TAGS"):
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            raise ValueError(f"{pid}: expected a list of text values")
        if len(set(value)) != len(value):
            raise ValueError(f"{pid}: duplicate selections")
        # TAGS historically supports free text in addition to suggested options.
        if ptype == "MULTI_ENUM" and any(v not in choices for v in value):
            raise ValueError(f"{pid}: invalid selection")
        return ("list", None, None, None, value)
    if ptype == "NUMBER":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{pid}: expected a finite number")
        return ("number", None, value, None, [])
    if not isinstance(value, str):
        raise ValueError(f"{pid}: expected text")
    if ptype == "DATE":
        if datetime.date.fromisoformat(value).isoformat() != value:
            raise ValueError(f"{pid}: expected an ISO date")
        return ("date", None, None, value, [])
    if ptype == "ENUM" and value not in choices:
        raise ValueError(f"{pid}: invalid selection {value!r}")
    return ("text", value, None, None, [])


def write_value(conn: sqlite3.Connection, owner_id: int, pid: str, value: Any, *, defaults: bool = False) -> None:
    table, owner = ("project_type_property_default", "project_type_id") if defaults else ("project_property_value", "project_id")
    kind, text, number, date, items = encode_value(conn, pid, value)
    conn.execute(f"DELETE FROM {table}_item WHERE {owner} = ? AND param_id = ?", (owner_id, pid))
    conn.execute(
        f"INSERT INTO {table} ({owner}, param_id, kind, text_value, number_value, date_value) VALUES (?, ?, ?, ?, ?, ?) "
        f"ON CONFLICT ({owner}, param_id) DO UPDATE SET kind=excluded.kind, text_value=excluded.text_value, number_value=excluded.number_value, date_value=excluded.date_value",
        (owner_id, pid, kind, text, number, date),
    )
    conn.executemany(f"INSERT INTO {table}_item ({owner}, param_id, position, value) VALUES (?, ?, ?, ?)",
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
    result = []
    for p in parameters(conn):
        if p["applies_to_all"] or p["param_id"] in selected:
            pid = p["param_id"]
            p["mandatory_override"] = overrides.get(pid)
            p["mandatory"] = bool(p["mandatory"] if overrides.get(pid) is None else overrides[pid])
            p["has_default"] = pid in defaults
            p["default_value"] = defaults.get(pid)
            result.append(p)
    return result


def prepare_values(conn: sqlite3.Connection, type_id: int, submitted: dict[str, Any], *, creating: bool, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    template = effective_template(conn, type_id)
    allowed = {p["param_id"] for p in template}
    unknown = submitted.keys() - allowed
    if unknown:
        raise ValueError("Properties do not apply to this project type: " + ", ".join(sorted(unknown)))
    values = {pid: value for pid, value in (existing or {}).items() if pid in allowed}
    if creating:
        values.update({p["param_id"]: p["default_value"] for p in template if p["has_default"]})
    values.update(submitted)
    for p in template:
        pid = p["param_id"]
        value = values.get(pid)
        if p["mandatory"] and (value is None or value == [] or isinstance(value, str) and not value.strip()):
            raise ValueError(f"Required property: {p['param_name']}")
        if pid in values:
            encode_value(conn, pid, value)
    return values
