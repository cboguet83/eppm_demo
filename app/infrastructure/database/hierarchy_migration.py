"""Add optional shared hierarchy types without changing existing assignments."""

import sqlite3


def migrate_hierarchy_types(connection: sqlite3.Connection) -> None:
    """Install and seed the catalog once in the caller's migration transaction."""
    version = "hierarchy-types-v1"
    if connection.execute("SELECT 1 FROM schema_migration WHERE version=?", (version,)).fetchone():
        return
    connection.execute("""CREATE TABLE hierarchy_type (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE CHECK(length(code) BETWEEN 1 AND 64
            AND code GLOB '[a-z]*' AND code NOT GLOB '*[^a-z0-9_]*'))""")
    connection.execute("""CREATE TABLE hierarchy_type_translation (
        hierarchy_type_id INTEGER NOT NULL REFERENCES hierarchy_type(id) ON DELETE CASCADE,
        locale TEXT NOT NULL CHECK(locale IN ('en','fr','de','lb','pt')),
        label TEXT NOT NULL CHECK(length(trim(label)) BETWEEN 1 AND 120),
        PRIMARY KEY(hierarchy_type_id,locale))""")
    connection.execute("""CREATE TRIGGER hierarchy_type_stable_code
        BEFORE UPDATE OF code ON hierarchy_type WHEN NEW.code != OLD.code
        BEGIN SELECT RAISE(ABORT,'Hierarchy type codes are immutable'); END""")
    for table in ("team", "resource_pool", "resource_pool_group"):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN hierarchy_type_id INTEGER "
                           "REFERENCES hierarchy_type(id) ON DELETE RESTRICT")
        connection.execute(f"CREATE INDEX {table}_hierarchy_type ON {table}(hierarchy_type_id)")
    codes = ("ressort", "service", "division", "equipe", "region", "brigade", "district")
    for code in codes:
        type_id = connection.execute("INSERT INTO hierarchy_type(code) VALUES(?)", (code,)).lastrowid
        connection.executemany(
            "INSERT INTO hierarchy_type_translation(hierarchy_type_id,locale,label) VALUES(?,?,?)",
            [(type_id, locale, code) for locale in ("en", "fr", "de", "lb", "pt")],
        )
    connection.execute("INSERT INTO schema_migration(version) VALUES(?)", (version,))
