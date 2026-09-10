"""Add immutable budget snapshots and the application-wide finance editor role."""

import sqlite3


def _finance_role(connection: sqlite3.Connection) -> None:
    """Expand the role check while preserving assignments, indexes and all triggers."""
    # Scope-invalidation triggers on other tables also reference this table.
    objects = connection.execute("""SELECT type,name,sql FROM sqlite_master
        WHERE type IN ('trigger','index') AND sql IS NOT NULL
        AND (tbl_name='app_role_assignment' OR instr(sql,'app_role_assignment')>0)""").fetchall()
    sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='app_role_assignment'").fetchone()
    for kind, name, _ in objects:
        connection.execute(f'DROP {kind.upper()} "{name.replace(chr(34), chr(34) * 2)}"')
    connection.execute("""CREATE TABLE app_role_assignment_finance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE RESTRICT,
        role TEXT NOT NULL CHECK(role IN ('project_viewer','project_editor','project_approver',
            'access_admin','business_admin','finance_editor')),
        scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),
        invalid_reason TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, created_by TEXT NOT NULL,
        UNIQUE(user_id,role,scope_json))""")
    connection.execute("INSERT INTO app_role_assignment_finance SELECT * FROM app_role_assignment")
    connection.execute("DROP TABLE app_role_assignment")
    connection.execute("ALTER TABLE app_role_assignment_finance RENAME TO app_role_assignment")
    if sequence:
        connection.execute("UPDATE sqlite_sequence SET seq=? WHERE name='app_role_assignment'", (sequence[0],))
    for _, _, sql in objects:
        connection.execute(sql)


def migrate_finance(connection: sqlite3.Connection) -> None:
    """Install finance in the caller's migration transaction without rewriting history."""
    version = "finance-budget-v1"
    if connection.execute("SELECT 1 FROM schema_migration WHERE version=?", (version,)).fetchone():
        return
    _finance_role(connection)
    connection.execute("""CREATE TABLE finance_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        major INTEGER NOT NULL CHECK(typeof(major)='integer' AND major>0),
        minor INTEGER NOT NULL CHECK(typeof(minor)='integer' AND minor>=0),
        name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
        status TEXT NOT NULL CHECK(status IN ('Draft','Proposed','Approved')),
        author TEXT NOT NULL, created_at INTEGER NOT NULL,
        base_id INTEGER REFERENCES finance_snapshot(id) ON DELETE RESTRICT,
        sealed INTEGER NOT NULL DEFAULT 0 CHECK(sealed IN (0,1)), UNIQUE(major,minor))""")
    connection.execute("""CREATE TABLE finance_row (
        snapshot_id INTEGER NOT NULL REFERENCES finance_snapshot(id) ON DELETE RESTRICT,
        code TEXT NOT NULL CHECK(
            length(CASE WHEN substr(code,1,1)='#' THEN substr(code,2) ELSE code END) BETWEEN 1 AND 128
            AND (CASE WHEN substr(code,1,1)='#' THEN substr(code,2) ELSE code END) NOT GLOB '*[^A-Za-z0-9._-]*'),
        position INTEGER NOT NULL CHECK(position>=0), PRIMARY KEY(snapshot_id,code),
        UNIQUE(snapshot_id,position))""")
    connection.execute("""CREATE TABLE finance_amount (
        snapshot_id INTEGER NOT NULL, code TEXT NOT NULL, year INTEGER NOT NULL CHECK(typeof(year)='integer' AND year BETWEEN 1 AND 9999),
        cents INTEGER NOT NULL CHECK(typeof(cents)='integer' AND cents>=0),
        PRIMARY KEY(snapshot_id,code,year),
        FOREIGN KEY(snapshot_id,code) REFERENCES finance_row(snapshot_id,code) ON DELETE RESTRICT)""")
    connection.execute("""CREATE TRIGGER finance_snapshot_no_replace BEFORE INSERT ON finance_snapshot
        WHEN EXISTS(SELECT 1 FROM finance_snapshot WHERE id=NEW.id OR (major=NEW.major AND minor=NEW.minor))
        BEGIN SELECT RAISE(ABORT,'Budget snapshots are immutable'); END""")
    for table in ("finance_snapshot", "finance_row", "finance_amount"):
        connection.execute(f"""CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT,'Budget snapshots are immutable'); END""")
        condition = "WHEN OLD.sealed=1" if table == "finance_snapshot" else ""
        connection.execute(f"""CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} {condition}
            BEGIN SELECT RAISE(ABORT,'Budget snapshots are immutable'); END""")
        if table != "finance_snapshot":
            connection.execute(f"""CREATE TRIGGER {table}_sealed BEFORE INSERT ON {table}
                WHEN (SELECT sealed FROM finance_snapshot WHERE id=NEW.snapshot_id)=1
                BEGIN SELECT RAISE(ABORT,'Budget snapshots are immutable'); END""")
    connection.execute("INSERT INTO schema_migration(version) VALUES(?)", (version,))
