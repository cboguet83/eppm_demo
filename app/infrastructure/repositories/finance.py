"""SQLite finance transactions with active-user reads and global write checks."""

from collections.abc import Iterator
from contextlib import closing, contextmanager
import sqlite3

from app.application.services.business_access import BusinessAccess
from app.application.exceptions import FinanceStorageError
from app.domain.access.models import Actor, Permission
from app.domain.finance import BudgetRow, BudgetSnapshot, BudgetVersion, FinanceError
from app.infrastructure.database.connection import get_db
from app.infrastructure.repositories.access import SqliteAccessStore


class SqliteFinanceStore:
    """Read and append finance snapshots on a single authorized connection."""

    def __init__(self, connection: sqlite3.Connection, access: BusinessAccess, *, writable: bool) -> None:
        self.connection, self.access, self.writable = connection, access, writable
        self.security = SqliteAccessStore(connection)

    def versions(self) -> tuple[BudgetVersion, ...]:
        """List snapshot metadata newest major and minor first."""
        return tuple(BudgetVersion(*row) for row in self.connection.execute(
            "SELECT id,major,minor,name,status,author,created_at,base_id FROM finance_snapshot WHERE sealed=1 ORDER BY major DESC,minor DESC"))

    def snapshot(self, snapshot_id: int) -> BudgetSnapshot:
        """Load one complete snapshot, with constant query count for all amounts."""
        if type(snapshot_id) is not int or not 0 < snapshot_id <= 9223372036854775807:
            raise FinanceError("missing")
        record = self.connection.execute("""SELECT id,major,minor,name,status,author,created_at,base_id
            FROM finance_snapshot WHERE id=? AND sealed=1""", (snapshot_id,)).fetchone()
        if record is None:
            raise FinanceError("missing")
        rows: dict[str, dict[int, int]] = {}
        for code, year, cents in self.connection.execute("""SELECT r.code,a.year,a.cents FROM finance_row r
            LEFT JOIN finance_amount a ON a.snapshot_id=r.snapshot_id AND a.code=r.code
            WHERE r.snapshot_id=? ORDER BY r.position,a.year""", (snapshot_id,)):
            values = rows.setdefault(code, {})
            if year is not None:
                values[year] = cents
        return BudgetSnapshot(BudgetVersion(*record), tuple(BudgetRow(code, values) for code, values in rows.items()))

    def catalog(self) -> dict[str, str]:
        """Expose only WBS code/description references, independently of project scope."""
        return dict(self.connection.execute("SELECT code,description FROM wbs ORDER BY code"))

    def can_edit(self) -> bool:
        """Read the current global finance capability, including session validity."""
        return self.access.global_permission(self.security, Permission.FINANCE)

    def latest(self, major: int | None = None) -> BudgetVersion | None:
        """Find the current head under the caller's read or writer transaction."""
        row = self.connection.execute("""SELECT id,major,minor,name,status,author,created_at,base_id
            FROM finance_snapshot WHERE sealed=1 AND (? IS NULL OR major=?)
            ORDER BY major DESC,minor DESC LIMIT 1""", (major, major)).fetchone()
        return BudgetVersion(*row) if row else None

    def insert(self, rows: tuple[BudgetRow, ...], *, major: int, minor: int,
               name: str, status: str, base_id: int | None) -> int:
        """Append and seal a snapshot atomically; existing snapshots are never updated."""
        if not self.writable:
            raise FinanceStorageError("A finance writer transaction is required.")
        self.access.require(self.security, Permission.FINANCE)
        cursor = self.connection.execute("""INSERT INTO finance_snapshot(major,minor,name,status,author,created_at,base_id)
            VALUES(?,?,?,?,?,?,?)""", (major, minor, name, status, self.access.audit_actor,
                                       self.access.policy.clock(), base_id))
        snapshot_id = cursor.lastrowid
        assert snapshot_id is not None
        self.connection.executemany("INSERT INTO finance_row VALUES(?,?,?)",
                                    [(snapshot_id, row.code, index) for index, row in enumerate(rows)])
        self.connection.executemany("INSERT INTO finance_amount VALUES(?,?,?,?)",
                                    [(snapshot_id, row.code, year, cents) for row in rows for year, cents in row.amounts.items()])
        self.connection.execute("UPDATE finance_snapshot SET sealed=1 WHERE id=?", (snapshot_id,))
        return snapshot_id


class SqliteFinanceGateway:
    """Serialize writers and reauthorize every read, import, save and download."""

    def __init__(self, db_path: str, access: BusinessAccess) -> None:
        self.db_path, self.access = db_path, access

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[SqliteFinanceStore]:
        """Roll back all partial snapshots on validation, authorization or storage errors."""
        try:
            with closing(get_db(self.db_path)) as connection, connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                security = SqliteAccessStore(connection)
                if isinstance(self.access.actor, Actor):
                    self.access.policy.session(security, self.access.actor)
                if write:
                    self.access.require(security, Permission.FINANCE)
                yield SqliteFinanceStore(connection, self.access, writable=write)
        except sqlite3.Error as error:
            raise FinanceStorageError("Finance storage is unavailable. Your changes have not been saved.") from error
