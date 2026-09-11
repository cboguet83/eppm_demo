"""Migrate budget numbering while preserving snapshots and audited cancellation."""

import sqlite3


def migrate_finance_versions(connection: sqlite3.Connection) -> None:
    """Convert existing snapshots in the caller's atomic migration transaction."""
    version = "finance-budget-v2"
    if connection.execute("SELECT 1 FROM schema_migration WHERE version=?", (version,)).fetchone():
        return
    connection.execute("""CREATE TABLE finance_snapshot_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number INTEGER NOT NULL UNIQUE CHECK(typeof(number)='integer' AND number>0),
        name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
        status TEXT NOT NULL CHECK(status IN ('Draft','Proposed','Approved','Canceled')),
        author TEXT NOT NULL, created_at INTEGER NOT NULL,
        base_id INTEGER REFERENCES finance_snapshot_v2(id) ON DELETE RESTRICT,
        sealed INTEGER NOT NULL DEFAULT 0 CHECK(sealed IN (0,1)))""")
    connection.execute("""INSERT INTO finance_snapshot_v2
        SELECT id,row_number() OVER (ORDER BY created_at,id),name,status,author,created_at,base_id,sealed
        FROM finance_snapshot""")
    sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='finance_snapshot'").fetchone()
    for table in ("finance_row", "finance_amount"):
        sql = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
        for old in ("finance_snapshot", "finance_row", "finance_amount"):
            sql = sql.replace(old, old + "_v2")
        connection.execute(sql)
        connection.execute(f"INSERT INTO {table}_v2 SELECT * FROM {table}")
    triggers = connection.execute("""SELECT name,sql FROM sqlite_master WHERE type='trigger'
        AND tbl_name IN ('finance_snapshot','finance_row','finance_amount')""").fetchall()
    for name, _ in triggers:
        connection.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
    # Self references must be cleared only in the obsolete, fully copied table.
    connection.execute("UPDATE finance_snapshot SET base_id=NULL")
    for table in ("finance_amount", "finance_row", "finance_snapshot"):
        connection.execute(f"DROP TABLE {table}")
    for table in ("finance_snapshot", "finance_row", "finance_amount"):
        connection.execute(f"ALTER TABLE {table}_v2 RENAME TO {table}")
    if sequence:
        connection.execute("UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='finance_snapshot'", (sequence[0],))
    for name, sql in triggers:
        if name == "finance_snapshot_no_replace":
            sql = sql.replace("(major=NEW.major AND minor=NEW.minor)", "number=NEW.number")
        connection.execute(sql)
    connection.execute("""CREATE TABLE finance_cancellation (
        snapshot_id INTEGER PRIMARY KEY REFERENCES finance_snapshot(id) ON DELETE RESTRICT,
        previous_status TEXT NOT NULL CHECK(previous_status IN ('Draft','Proposed','Approved')),
        author TEXT NOT NULL, occurred_at INTEGER NOT NULL)""")
    connection.execute("""CREATE TRIGGER finance_cancellation_valid BEFORE INSERT ON finance_cancellation
        WHEN EXISTS(SELECT 1 FROM finance_cancellation WHERE snapshot_id=NEW.snapshot_id)
          OR NOT EXISTS(SELECT 1 FROM finance_snapshot WHERE id=NEW.snapshot_id AND sealed=1
                        AND status=NEW.previous_status AND status!='Canceled')
        BEGIN SELECT RAISE(ABORT,'Invalid budget cancellation'); END""")
    for operation in ("UPDATE", "DELETE"):
        connection.execute(f"""CREATE TRIGGER finance_cancellation_no_{operation.lower()}
            BEFORE {operation} ON finance_cancellation
            BEGIN SELECT RAISE(ABORT,'Budget cancellations are immutable'); END""")
    connection.execute("INSERT INTO schema_migration(version) VALUES(?)", (version,))
