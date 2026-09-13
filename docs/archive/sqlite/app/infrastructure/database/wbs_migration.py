"""Add the shared WBS catalog and globally bounded project allocations."""

import sqlite3


def migrate_wbs(connection: sqlite3.Connection) -> None:
    """Apply the additive migration in the caller's schema transaction."""
    version = "project-wbs-v1"
    if connection.execute("SELECT 1 FROM schema_migration WHERE version=?", (version,)).fetchone():
        return
    connection.execute("""CREATE TABLE wbs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        CHECK(length(CASE WHEN substr(code,1,1)='#' THEN substr(code,2) ELSE code END) BETWEEN 1 AND 128),
        CHECK((CASE WHEN substr(code,1,1)='#' THEN substr(code,2) ELSE code END) NOT GLOB '*[^A-Za-z0-9._-]*')
    )""")
    connection.execute("""CREATE TABLE project_wbs (
        project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        wbs_id INTEGER NOT NULL REFERENCES wbs(id) ON DELETE RESTRICT,
        percentage INTEGER NOT NULL CHECK(typeof(percentage)='integer' AND percentage BETWEEN 0 AND 100),
        PRIMARY KEY(project_id,wbs_id)
    )""")
    connection.execute("CREATE INDEX idx_project_wbs_wbs ON project_wbs(wbs_id)")
    for operation in ("INSERT", "UPDATE"):
        excluded = "AND NOT (project_id=OLD.project_id AND wbs_id=OLD.wbs_id)" if operation == "UPDATE" else ""
        connection.execute(f"""CREATE TRIGGER project_wbs_limit_{operation.lower()}
            BEFORE {operation} ON project_wbs
            WHEN NEW.percentage + (SELECT COALESCE(SUM(percentage),0) FROM project_wbs
                WHERE wbs_id=NEW.wbs_id {excluded}) > 100
            BEGIN SELECT RAISE(ABORT,'WBS total allocation cannot exceed 100%'); END""")
    connection.execute("INSERT INTO schema_migration(version) VALUES(?)", (version,))
