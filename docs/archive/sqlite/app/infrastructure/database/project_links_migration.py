"""Add unlimited named links without changing existing template properties."""

import sqlite3


def migrate_project_links(connection: sqlite3.Connection) -> None:
    """Create the link collection atomically in the caller's schema transaction."""
    version = "project-links-v1"
    if connection.execute(
        "SELECT 1 FROM schema_migration WHERE version=?", (version,)
    ).fetchone():
        return
    connection.execute("""CREATE TABLE project_link (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        url TEXT NOT NULL CHECK(length(trim(url)) > 0),
        alias TEXT NOT NULL CHECK(length(trim(alias)) > 0)
    )""")
    connection.execute("CREATE INDEX idx_project_link_project ON project_link(project_id, id)")
    connection.execute("INSERT INTO schema_migration(version) VALUES (?)", (version,))
