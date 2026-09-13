"""Add project contacts and event logs without changing existing project data."""

import sqlite3


DEFAULT_EVENT_TYPES = ("General information", "Blocking Point", "Project update")


def migrate_project_collaboration(conn: sqlite3.Connection) -> None:
    """Install the versioned collaboration schema and initial event types.

    Args:
        conn: The caller's active schema migration transaction.
    """
    version = "project-collaboration-v1"
    if conn.execute("SELECT 1 FROM schema_migration WHERE version=?", (version,)).fetchone():
        return
    for table in ("project_role", "project_event_type"):
        conn.execute(f"""CREATE TABLE {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK(length(trim(name)) > 0)
        )""")
        conn.execute(f"""CREATE TABLE {table}_translation (
            catalog_id INTEGER NOT NULL REFERENCES {table}(id) ON DELETE CASCADE,
            locale TEXT NOT NULL,
            label TEXT NOT NULL CHECK(length(trim(label)) > 0),
            PRIMARY KEY(catalog_id, locale)
        )""")
    conn.execute("""CREATE TABLE project_contact (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        role_id INTEGER NOT NULL REFERENCES project_role(id) ON DELETE RESTRICT,
        function_id INTEGER NOT NULL REFERENCES function(function_id) ON DELETE RESTRICT,
        UNIQUE(project_id, role_id, function_id)
    )""")
    conn.execute("CREATE INDEX idx_project_contact_role ON project_contact(role_id)")
    conn.execute("CREATE INDEX idx_project_contact_function ON project_contact(function_id)")
    conn.execute("""CREATE TABLE project_log_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        title TEXT NOT NULL CHECK(length(trim(title)) > 0),
        description TEXT NOT NULL DEFAULT '',
        deadline TEXT,
        scope TEXT NOT NULL DEFAULT 'internal' CHECK(scope IN ('internal', 'global')),
        comment TEXT NOT NULL DEFAULT '',
        event_type_id INTEGER NOT NULL REFERENCES project_event_type(id) ON DELETE RESTRICT,
        status TEXT NOT NULL DEFAULT 'new'
            CHECK(status IN ('new', 'active', 'completed', 'cancelled', 'rejected', 'closed')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("CREATE INDEX idx_project_log_project ON project_log_event(project_id, id DESC)")
    conn.execute("CREATE INDEX idx_project_log_type ON project_log_event(event_type_id)")
    seed_project_event_types(conn)
    conn.execute("INSERT INTO schema_migration(version) VALUES (?)", (version,))


def seed_project_event_types(conn: sqlite3.Connection) -> None:
    """Populate defaults during migration or an explicit full database reset.

    Args:
        conn: The caller's active transaction.
    """
    for name in DEFAULT_EVENT_TYPES:
        cursor = conn.execute("INSERT INTO project_event_type(name) VALUES (?)", (name,))
        conn.execute("INSERT INTO project_event_type_translation VALUES (?, 'en', ?)",
                     (cursor.lastrowid, name))
