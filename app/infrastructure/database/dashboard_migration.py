"""Stable issue classification and one-time activation of idle-only sessions."""

import sqlite3


def migrate_dashboard(connection: sqlite3.Connection) -> None:
    """Preserve project events while identifying blockers and retiring old sessions."""
    version = "dashboard-idle-sessions-v1"
    if connection.execute("SELECT 1 FROM schema_migration WHERE version=?", (version,)).fetchone():
        return
    connection.execute("ALTER TABLE project_event_type ADD COLUMN system_code TEXT")
    connection.execute("CREATE UNIQUE INDEX project_event_type_system_code ON project_event_type(system_code)")
    connection.execute("UPDATE project_event_type SET system_code='blocking_point' WHERE name='Blocking Point'")
    connection.execute("""CREATE TRIGGER project_event_type_classify AFTER INSERT ON project_event_type
        WHEN NEW.name='Blocking Point' AND NEW.system_code IS NULL
          AND NOT EXISTS(SELECT 1 FROM project_event_type WHERE system_code='blocking_point')
        BEGIN UPDATE project_event_type SET system_code='blocking_point' WHERE id=NEW.id; END""")
    connection.execute("UPDATE app_session SET revoked=1 WHERE revoked=0")
    connection.execute("INSERT INTO schema_migration(version) VALUES(?)", (version,))
