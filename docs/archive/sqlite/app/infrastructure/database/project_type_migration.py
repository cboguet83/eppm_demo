"""Versioned migration from project JSON to typed relational values."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.infrastructure.database.property_store import read_values, resolve_keys, write_value
from app.shared.logging import get_logger

logger = get_logger(__name__)


def backup_legacy_database(path: str) -> None:
    if path == ":memory:" or not Path(path).is_file():
        return
    with closing(sqlite3.connect(path)) as source:
        legacy = any(r[1] == "dynamic_attributes" for r in source.execute("PRAGMA table_info(project)"))
        legacy = legacy or bool(source.execute("SELECT 1 FROM sqlite_master WHERE name='projects'").fetchone())
        if legacy:
            backup = Path(str(path) + ".before-project-types.bak")
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as target:
                    source.backup(target)


def migrate_project_types(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migration (version TEXT PRIMARY KEY)")
    if conn.execute("SELECT 1 FROM schema_migration WHERE version='project-types-v1'").fetchone():
        return
    # Older seeders disabled foreign keys. Preserve unrelated legacy orphans;
    # this migration must neither delete their data nor introduce new violations.
    existing_violations = set(conn.execute("PRAGMA foreign_key_check").fetchall())
    conn.execute("""CREATE TABLE project_type (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK(length(trim(name)) > 0),
        description TEXT NOT NULL DEFAULT '', is_general INTEGER NOT NULL DEFAULT 0 CHECK(is_general IN (0,1)))""")
    conn.execute("CREATE UNIQUE INDEX one_general_project_type ON project_type(is_general) WHERE is_general=1")
    conn.execute("INSERT INTO project_type(id, name, is_general) VALUES (1, 'General', 1)")
    conn.execute("ALTER TABLE project ADD COLUMN project_type_id INTEGER NOT NULL DEFAULT 1 REFERENCES project_type(id) ON DELETE RESTRICT")
    conn.execute("ALTER TABLE schema_parameters ADD COLUMN applies_to_all INTEGER NOT NULL DEFAULT 1 CHECK(applies_to_all IN (0,1))")
    conn.execute("""CREATE TABLE project_type_property (
        project_type_id INTEGER NOT NULL REFERENCES project_type(id) ON DELETE CASCADE,
        param_id TEXT NOT NULL REFERENCES schema_parameters(param_id) ON DELETE CASCADE,
        PRIMARY KEY(project_type_id, param_id))""")
    conn.execute("""CREATE TABLE project_type_property_rule (
        project_type_id INTEGER NOT NULL REFERENCES project_type(id) ON DELETE CASCADE,
        param_id TEXT NOT NULL REFERENCES schema_parameters(param_id) ON DELETE CASCADE,
        mandatory_override INTEGER CHECK(mandatory_override IN (0,1)),
        PRIMARY KEY(project_type_id, param_id))""")
    for table, owner, parent in [("project_property_value", "project_id", "project"), ("project_type_property_default", "project_type_id", "project_type")]:
        conn.execute(f"""CREATE TABLE {table} (
            {owner} INTEGER NOT NULL REFERENCES {parent}(id) ON DELETE CASCADE,
            param_id TEXT NOT NULL REFERENCES schema_parameters(param_id) ON DELETE RESTRICT,
            kind TEXT NOT NULL CHECK(kind IN ('null','empty','text','number','date','list')),
            text_value TEXT, number_value REAL, date_value TEXT,
            CHECK ((kind='text' AND text_value IS NOT NULL AND number_value IS NULL AND date_value IS NULL)
                OR (kind='number' AND number_value IS NOT NULL AND text_value IS NULL AND date_value IS NULL)
                OR (kind='date' AND date_value IS NOT NULL AND text_value IS NULL AND number_value IS NULL)
                OR (kind IN ('null','empty','list') AND text_value IS NULL AND number_value IS NULL AND date_value IS NULL)),
            PRIMARY KEY({owner}, param_id))""")
        conn.execute(f"CREATE INDEX idx_{table}_param ON {table}(param_id)")
        conn.execute(f"""CREATE TABLE {table}_item (
            {owner} INTEGER NOT NULL, param_id TEXT NOT NULL, position INTEGER NOT NULL CHECK(position >= 0), value TEXT NOT NULL,
            PRIMARY KEY({owner}, param_id, position), UNIQUE({owner}, param_id, value),
            FOREIGN KEY({owner}, param_id) REFERENCES {table}({owner}, param_id) ON DELETE CASCADE)""")
    conn.execute("CREATE INDEX idx_project_type ON project(project_type_id)")
    converted = {}
    for project_id, raw in conn.execute("SELECT id, dynamic_attributes FROM project").fetchall():
        try:
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(f"Duplicate JSON key: {key}")
                    result[key] = value
                return result
            values = json.loads(raw, object_pairs_hook=unique_pairs) if raw and raw.strip() else {}
            if not isinstance(values, dict):
                raise ValueError("Custom properties must be a JSON object")
            converted[project_id] = resolve_keys(conn, values)
            for pid, value in converted[project_id].items():
                write_value(conn, project_id, pid, value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Project {project_id}: migration stopped; correct legacy custom properties and retry. {exc}") from exc
    loaded = read_values(conn)
    if any(loaded.get(pid, {}) != values for pid, values in converted.items()):
        raise ValueError("Project property migration verification failed")
    violations = set(conn.execute("PRAGMA foreign_key_check").fetchall()) - existing_violations
    if violations:
        raise ValueError(f"Migration introduced foreign-key violations: {sorted(violations)[:10]}")
    if existing_violations:
        logger.warning("Preserving %d pre-existing foreign-key violations during project-type migration: %s", len(existing_violations), sorted(existing_violations)[:10])
    conn.execute("ALTER TABLE project DROP COLUMN dynamic_attributes")
    conn.execute("INSERT INTO schema_migration(version) VALUES ('project-types-v1')")
