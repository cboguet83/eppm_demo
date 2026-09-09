"""Add pool hierarchy and capacity examples without replacing existing demo data.

Preview: python -m app.infrastructure.database.pool_scenarios --year 2026
Apply:   python -m app.infrastructure.database.pool_scenarios --year 2026 --apply
"""

import hashlib
import random
import sqlite3
import tempfile
from contextlib import closing
from datetime import date
from pathlib import Path
from app.application.ports.maintenance import PoolSeedReport

from app.shared.config import config
from app.infrastructure.database.backup import backup_before_seed

MARKER = "Pool hierarchy capacity scenarios v2"
BASE_GROUPS = ("Service A", "Service B", "Service C", "Service D", "Service E", "Ressort A")

type SqlValue = str | int | float | None
type SeedPlan = list[tuple[str, tuple[SqlValue, ...]]]


def fingerprint(conn: sqlite3.Connection) -> str:
    """Hash the logical snapshot to detect writes before applying a prepared plan."""
    digest = hashlib.sha256()
    for line in conn.iterdump():
        digest.update(line.encode())
    return digest.hexdigest()


def seed_snapshot(path: str | Path, year: int, seed: int) -> tuple[SeedPlan, PoolSeedReport]:
    """Build and verify an additive plan on an isolated database snapshot."""
    with closing(sqlite3.connect(path)) as conn:
        return _seed_snapshot(conn, path, year, seed)


def _seed_snapshot(
    conn: sqlite3.Connection, path: str | Path, year: int, seed: int
) -> tuple[SeedPlan, PoolSeedReport]:
    """Exactly five units per Service root, with four staffing scenarios each."""
    rng = random.Random(seed)
    conn.execute("PRAGMA foreign_keys=ON")
    baseline = set(conn.execute("PRAGMA foreign_key_check"))
    if conn.execute(
        "SELECT 1 FROM resource_pool_group WHERE description='Pool hierarchy capacity scenarios v1'"
    ).fetchone():
        raise ValueError(
            "Legacy generated pool groups exist. Run a full backed-up seed to replace them with the five-unit/four-pool layout."
        )
    plan, summary, scenarios = [], [], []

    def insert(sql: str, params: tuple[SqlValue, ...]) -> int:
        cursor = conn.execute(sql, params)
        plan.append((sql, params))
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    with conn:
        roots = conn.execute("SELECT id,name FROM resource_pool_group ORDER BY id").fetchall()
        if not roots:
            ids = {
                name: insert(
                    "INSERT INTO resource_pool_group(name,description) VALUES(?,?)",
                    (name, "Demo pool organization"),
                )
                for name in BASE_GROUPS
            }
            for name in BASE_GROUPS[:-1]:
                insert(
                    "INSERT INTO resource_pool_group_member(group_id,child_group_id) VALUES(?,?)",
                    (ids["Ressort A"], ids[name]),
                )
            roots = conn.execute("SELECT id,name FROM resource_pool_group ORDER BY id").fetchall()
        services = [
            (gid, name)
            for gid, name in roots
            if name.strip().casefold().startswith("service ") and "/" not in name
        ]
        employees = dict(
            conn.execute(
                "SELECT employee_id,occupation_percentage FROM employee WHERE occupation_percentage>0"
            )
        )
        eligible = sorted(employees)
        if len(eligible) < 3:
            raise ValueError("At least three employed resources are needed for pool scenarios.")
        tasks = conn.execute(
            "SELECT id,project_id,start_date,end_date FROM project_task ORDER BY id"
        ).fetchall()
        projects = [r[0] for r in conn.execute("SELECT id FROM project ORDER BY id")]
        mappings = project_assignments = task_assignments = 0
        roles = ("Unallocated", "Overassigned", "Underassigned", "Fully assigned")
        start, end = f"{year}-01-01", f"{year}-12-31"
        for service_id, service_name in services:
            for unit in range(1, 6):
                name = f"{service_name} / Unit {unit:02d}"
                gid = insert(
                    "INSERT INTO resource_pool_group(name,description) VALUES(?,?)", (name, MARKER)
                )
                insert(
                    "INSERT INTO resource_pool_group_member(group_id,child_group_id) VALUES(?,?)",
                    (service_id, gid),
                )
                for role in roles:
                    chosen = (
                        []
                        if role == "Unallocated"
                        else rng.sample(eligible, min(4, len(eligible)))
                    )
                    assigned = round(sum(float(employees[eid]) / 100 for eid in chosen), 3)
                    capacity = (
                        3.0
                        if not chosen
                        else (
                            round(assigned / 2, 3)
                            if role == "Overassigned"
                            else assigned + 2 if role == "Underassigned" else assigned
                        )
                    )
                    pid = insert(
                        "INSERT INTO resource_pool(name,description,capacity_fte) VALUES(?,?,?)",
                        (f"{name} / {role}", MARKER, capacity),
                    )
                    insert(
                        "INSERT INTO resource_pool_group_member(group_id,pool_id) VALUES(?,?)",
                        (gid, pid),
                    )
                    for eid in chosen:
                        insert(
                            "INSERT INTO resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES(?,'employee',?,100)",
                            (pid, eid),
                        )
                        mappings += 1
                    if projects:
                        index = len(scenarios)
                        # Both project-level and task-level demand, without changing task dates.
                        if tasks:
                            tid, project_id, ts, te = tasks[(index * 37) % len(tasks)]
                        else:
                            project_id, tid, ts, te = (
                                projects[index % len(projects)],
                                None,
                                start,
                                end,
                            )
                        demand = round((assigned or capacity) / 2, 3)
                        insert(
                            "INSERT INTO resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date,notes) VALUES(?,?,?,?,?,?)",
                            (pid, project_id, demand, ts, te, MARKER),
                        )
                        project_assignments += 1
                        if tid is not None:
                            insert(
                                "INSERT INTO resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,start_date,end_date,notes) VALUES(?,?,?,?,?,?,?)",
                                (pid, project_id, tid, demand, ts, te, MARKER),
                            )
                            task_assignments += 1
                    scenarios.append(
                        {
                            "role": role,
                            "pool_id": pid,
                            "theoretical_fte": capacity,
                            "normal_assigned_fte": assigned,
                        }
                    )
            summary.append({"parent": service_name, "new_groups": 5, "new_pools": 20})
        new_violations = set(conn.execute("PRAGMA foreign_key_check")) - baseline
        if new_violations:
            raise ValueError(f"New foreign-key violations: {new_violations}")
    return plan, {
        "parents": summary,
        "new_groups": 5 * len(services),
        "new_pools": len(scenarios),
        "new_employee_mappings": mappings,
        "new_project_assignments": project_assignments,
        "new_task_assignments": task_assignments,
        "scenarios": scenarios,
        "existing_foreign_key_violations": len(baseline),
    }


@backup_before_seed
def _apply_pool_plan(db_path: str, plan: SeedPlan, original_hash: str) -> None:
    with closing(sqlite3.connect(db_path)) as live, live:
        live.execute("PRAGMA foreign_keys=ON")
        live.execute("BEGIN IMMEDIATE")
        if fingerprint(live) != original_hash:
            raise RuntimeError(
                "Database changed during preparation; rerun to prepare a fresh plan."
            )
        for sql, params in plan:
            live.execute(sql, params)


def seed_pool_scenarios(
    db_path: str | Path | None = None,
    *,
    year: int | None = None,
    seed: int = 20260908,
    apply: bool = True,
) -> PoolSeedReport:
    """Idempotent additive seed, shared by full seeding and standalone repair.

    Validate on a snapshot, back up before applying, and replay only scenario
    writes. Existing projects, tasks, dependencies and their IDs stay unchanged.
    Nested calls under a full seed share its single pre-seed backup.
    """
    target = Path(db_path or config.db_path).resolve(strict=True)
    with closing(sqlite3.connect(target)) as conn:
        if conn.execute(
            "SELECT 1 FROM resource_pool_group WHERE description=?", (MARKER,)
        ).fetchone():
            return {"applied": False, "already_seeded": True, "new_groups": 0, "new_pools": 0}
    with tempfile.TemporaryDirectory(prefix="pool-scenarios-") as temp:
        original_path, staged_path = Path(temp) / "original.db", Path(temp) / "staged.db"
        with (
            closing(sqlite3.connect(target)) as live,
            closing(sqlite3.connect(original_path)) as original,
        ):
            live.backup(original)
            original_hash = fingerprint(original)
            with closing(sqlite3.connect(staged_path)) as staged:
                original.backup(staged)
        plan, report = seed_snapshot(staged_path, year or date.today().year, seed)
        report["applied"] = False
        if apply:
            _apply_pool_plan(str(target), plan, original_hash)
            report["applied"] = True
        return report
