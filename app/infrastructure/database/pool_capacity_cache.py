"""Revision-checked SQLite capacity cache; format and triggers are unchanged."""

from collections import OrderedDict
from collections.abc import Callable
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict, fields
from datetime import date
import json
from pathlib import Path
import sqlite3
from threading import RLock
from uuid import uuid4

from app.application.exceptions import ResourcePoolStorageError
from app.application.ports.pool_capacity import CapacityCalculation, CapacityResult
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.domain.resources.models import (
    DailyOverassignment,
    PoolCapacityDetail,
    PoolCapacitySummary,
    PoolResourceContribution,
)
from app.infrastructure.database.connection import get_db
from app.infrastructure.repositories.access import SqliteAccessStore
from app.infrastructure.repositories.portfolio import portfolio_revision
from app.shared.config import config
from app.shared.logging import get_logger

_VERSION = 2
logger = get_logger(__name__)


class CapacityCacheState:
    """Explicitly owned, bounded in-process cache shared by the composition root."""

    def __init__(self) -> None:
        """Create isolated cache state for injection into storage adapters."""
        self.lock = RLock()
        self.entries: OrderedDict[tuple, CapacityResult] = OrderedDict()


def install_capacity_cache(conn: sqlite3.Connection) -> None:
    """Install derived-data storage, lookup indexes and invalidation triggers."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pool_capacity_revision "
        "(id INTEGER PRIMARY KEY CHECK(id=1), epoch TEXT NOT NULL, revision INTEGER NOT NULL)"
    )
    conn.execute("INSERT OR IGNORE INTO pool_capacity_revision VALUES (1,?,0)", (uuid4().hex,))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pool_capacity_cache "
        "(pool_id INTEGER PRIMARY KEY, version INTEGER NOT NULL, day TEXT NOT NULL, "
        "summary TEXT NOT NULL, detail TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pool_capacity_employee "
        "(pool_id INTEGER NOT NULL, employee_id INTEGER NOT NULL, PRIMARY KEY(pool_id,employee_id))"
    )
    for name, table, columns in [
        ("idx_pool_assignment_pool", "resource_pool_assignment", "pool_id"),
        ("idx_pool_assignment_project", "resource_pool_assignment", "project_id"),
        ("idx_pool_assignment_task", "resource_pool_assignment", "task_id"),
        ("idx_pool_mapping_target", "resource_pool_mapping", "target_type,target_id"),
        ("idx_pool_capacity_employee", "pool_capacity_employee", "employee_id"),
        ("idx_task_project_dates", "project_task", "project_id,start_date,end_date"),
    ]:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({columns})")
    for table in [
        "resource_pool",
        "resource_pool_assignment",
        "resource_pool_mapping",
        "project_task",
        "project",
        "employee",
        "employee_calendar_exception",
        "function",
        "team",
        "team_function",
    ]:
        for event in ["INSERT", "UPDATE", "DELETE"]:
            refs = ["OLD", "NEW"] if event == "UPDATE" else ["OLD" if event == "DELETE" else "NEW"]
            if table == "resource_pool":
                where = "pool_id IN (" + ",".join(f"{r}.id" for r in refs) + ")"
            elif table in ("resource_pool_assignment", "resource_pool_mapping"):
                where = "pool_id IN (" + ",".join(f"{r}.pool_id" for r in refs) + ")"
            elif table in ("project", "project_task"):
                field = "id" if table == "project" else "project_id"
                where = (
                    "pool_id IN (SELECT pool_id FROM resource_pool_assignment WHERE project_id IN ("
                    + ",".join(f"{r}.{field}" for r in refs)
                    + "))"
                )
            elif table in ("employee", "employee_calendar_exception"):
                ids = ",".join(f"{r}.employee_id" for r in refs)
                where = f"pool_id IN (SELECT pool_id FROM pool_capacity_employee WHERE employee_id IN ({ids}))"
                if table == "employee":
                    # Occupancy changes can add a new employee to a mapped position/team.
                    where += " OR pool_id IN (SELECT pool_id FROM resource_pool_mapping WHERE target_type IN ('function','team'))"
                    where += f" OR pool_id IN (SELECT pool_id FROM resource_pool_mapping WHERE target_type='employee' AND target_id IN ({ids}))"
            else:
                # Structural organization changes can alter implicit team membership.
                where = "pool_id IN (SELECT pool_id FROM resource_pool_mapping WHERE target_type IN ('function','team'))"
                if table == "function":
                    ids = ",".join(f"{r}.function_id" for r in refs)
                    where += (
                        " OR pool_id IN (SELECT pe.pool_id FROM pool_capacity_employee pe "
                        "JOIN employee e ON e.employee_id=pe.employee_id "
                        f"WHERE e.function_id IN ({ids}))"
                    )
            update_columns = {
                "project": "name",
                "project_task": "project_id,start_date,end_date,task_name",
            }
            operation = event
            if event == "UPDATE" and table in update_columns:
                operation += " OF " + update_columns[table]
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS capacity_{table}_{event.lower()} "
                f"BEFORE {operation} ON {table} BEGIN "
                f"DELETE FROM pool_capacity_cache WHERE {where}; "
                "UPDATE pool_capacity_revision SET revision=revision+1 WHERE id=1; END"
            )


def _decode_detail(raw: str) -> PoolCapacityDetail:
    payload = json.loads(raw)
    payload["contributing_resources"] = [
        PoolResourceContribution(**v) for v in payload["contributing_resources"]
    ]
    payload["daily_overassignments"] = [
        DailyOverassignment(**v) for v in payload["daily_overassignments"]
    ]
    return PoolCapacityDetail(**payload)


class SqliteCapacityCache:
    """Persist derived data and reject publication after concurrent source edits."""

    def __init__(
        self,
        db_path: str | None,
        state: CapacityCacheState,
        today: Callable[[], date],
        *,
        access: BusinessAccess,
    ) -> None:
        """Inject the database path, shared process state, and clock."""
        self.db_path = db_path
        self.state = state
        self.today = today
        self.access = access

    def load(
        self,
        calculate: CapacityCalculation,
        *,
        details: bool = False,
        pool_ids: list[int] | None = None,
    ) -> CapacityResult:
        """Return current summaries/details, translating storage errors safely."""
        try:
            if isinstance(self.access.actor, Actor):
                return self._load_for_actor(calculate, details=details, pool_ids=pool_ids)
            return self._load(calculate, details=details, pool_ids=pool_ids)
        except sqlite3.DatabaseError as exc:
            logger.error("Resource-pool capacity storage failed (%s)", type(exc).__name__)
            raise ResourcePoolStorageError("Resource pool capacity could not be loaded.") from exc

    def _load_for_actor(self, calculate: CapacityCalculation, *, details: bool,
                        pool_ids: list[int] | None) -> CapacityResult:
        """Isolate derived results by current actor/scope and never reuse global JSON blobs."""
        path = str(Path(self.db_path or config.db_path).resolve())
        subset = tuple(sorted(set(pool_ids))) if pool_ids is not None else None
        day = self.today()
        with self.state.lock:
            for _ in range(3):
                with closing(get_db(path)) as conn, conn:
                    conn.execute("BEGIN")
                    allowed = self.access.projects(SqliteAccessStore(conn))
                    selected = [row[0] for row in conn.execute("SELECT id FROM resource_pool ORDER BY name,id")]
                    if subset is not None:
                        selected = [value for value in selected if value in subset]
                    revision = portfolio_revision(path)
                key = (path, revision, self.access.actor.user_id, self.access.actor.session_hash,
                       tuple(sorted(allowed)), day.isoformat(), details, subset)
                if key in self.state.entries:
                    self.state.entries.move_to_end(key)
                    return deepcopy(self.state.entries[key])
                calculated = calculate(selected, day)
                with closing(get_db(path)) as conn, conn:
                    conn.execute("BEGIN")
                    current = self.access.projects(SqliteAccessStore(conn))
                    if current != allowed or portfolio_revision(path) != revision:
                        continue
                if details:
                    result = calculated
                else:
                    columns = {field.name for field in fields(PoolCapacitySummary)}
                    result = [PoolCapacitySummary(**{key: value for key, value in asdict(item).items() if key in columns})
                              for item in calculated]
                self.state.entries[key] = deepcopy(result)
                while len(self.state.entries) > 8:
                    self.state.entries.popitem(last=False)
                return result
        raise ResourcePoolStorageError("Pool data changed while calculating capacity; please retry.")

    def _load(
        self,
        calculate: CapacityCalculation,
        *,
        details: bool,
        pool_ids: list[int] | None,
    ) -> CapacityResult:
        path = str(Path(self.db_path or config.db_path).resolve())
        subset = tuple(sorted(set(pool_ids))) if pool_ids is not None else None
        with self.state.lock:
            for _ in range(3):
                with closing(get_db(path)) as conn, conn:
                    conn.execute("BEGIN")
                    try:
                        revision = conn.execute(
                            "SELECT epoch,revision FROM pool_capacity_revision WHERE id=1"
                        ).fetchone()
                    except sqlite3.OperationalError as exc:
                        if "no such table" not in str(exc):
                            raise
                        conn.rollback()
                        install_capacity_cache(conn)
                        conn.commit()
                        conn.execute("BEGIN")
                        revision = conn.execute(
                            "SELECT epoch,revision FROM pool_capacity_revision WHERE id=1"
                        ).fetchone()
                    day = self.today().isoformat()
                    key = (path, revision, day, _VERSION, details, subset)
                    if key in self.state.entries:
                        self.state.entries.move_to_end(key)
                        return self.state.entries[key]
                    column = "detail" if details else "summary"
                    where = (
                        "WHERE p.id IN (SELECT value FROM json_each(?))"
                        if subset is not None
                        else ""
                    )
                    params = (
                        (_VERSION, day, json.dumps(subset))
                        if subset is not None
                        else (_VERSION, day)
                    )
                    rows = conn.execute(
                        f"SELECT p.id,c.{column} FROM resource_pool p LEFT JOIN pool_capacity_cache c "
                        f"ON c.pool_id=p.id AND c.version=? AND c.day=? {where} ORDER BY p.name,p.id",
                        params,
                    ).fetchall()
                missing = [pid for pid, payload in rows if payload is None]
                if missing:
                    calculated = calculate(missing, date.fromisoformat(day))
                    with closing(get_db(path)) as conn, conn:
                        conn.execute("BEGIN IMMEDIATE")
                        if (
                            revision
                            != conn.execute(
                                "SELECT epoch,revision FROM pool_capacity_revision WHERE id=1"
                            ).fetchone()
                        ):
                            continue
                        for detail in calculated:
                            payload = asdict(detail)
                            summary = {
                                f.name: payload[f.name] for f in fields(PoolCapacitySummary)
                            }
                            conn.execute(
                                "INSERT OR REPLACE INTO pool_capacity_cache VALUES(?,?,?,?,?)",
                                (
                                    detail.pool_id,
                                    _VERSION,
                                    day,
                                    json.dumps(summary),
                                    json.dumps(payload),
                                ),
                            )
                            conn.execute(
                                "DELETE FROM pool_capacity_employee WHERE pool_id=?",
                                (detail.pool_id,),
                            )
                            conn.executemany(
                                "INSERT OR IGNORE INTO pool_capacity_employee VALUES(?,?)",
                                [
                                    (detail.pool_id, c.employee_id)
                                    for c in detail.contributing_resources
                                    if c.employee_id is not None
                                ],
                            )
                    continue
                result = [
                    _decode_detail(raw) if details else PoolCapacitySummary(**json.loads(raw))
                    for _, raw in rows
                ]
                self.state.entries[key] = result
                while len(self.state.entries) > 8:
                    self.state.entries.popitem(last=False)
                return result
        raise ResourcePoolStorageError(
            "Pool data changed repeatedly while calculating capacity; please retry."
        )
