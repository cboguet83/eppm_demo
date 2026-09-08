"""Add pool hierarchy and capacity examples without replacing existing demo data.

Preview: python -m scripts.seed_pool_scenarios --year 2026
Apply:   python -m scripts.seed_pool_scenarios --year 2026 --apply
"""

import argparse
import hashlib
import json
import os
import random
import sqlite3
import tempfile
from contextlib import closing
from datetime import date
from pathlib import Path

from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.services.resource_pool_service import ResourcePoolService
from src.config import config
from src.database.backup import backup_before_seed


MARKER = "Pool hierarchy capacity scenarios v1"
BASE_GROUPS = ("Service A", "Service B", "Service C", "Service D", "Service E", "Ressort A")


def fingerprint(conn):
    digest = hashlib.sha256()
    for line in conn.iterdump():
        digest.update(line.encode())
    return digest.hexdigest()


def seed_snapshot(path, year, seed):
    """Build and verify an additive plan on an isolated database snapshot."""
    with closing(sqlite3.connect(path)) as conn:
        return _seed_snapshot(conn, path, year, seed)


def _seed_snapshot(conn, path, year, seed):
    rng = random.Random(seed)
    conn.execute("PRAGMA foreign_keys=ON")
    baseline_violations = set(conn.execute("PRAGMA foreign_key_check"))
    if conn.execute("SELECT 1 FROM resource_pool_group WHERE description=?", (MARKER,)).fetchone():
        conn.close()
        raise ValueError("This scenario seed already exists; refusing to duplicate it.")
    plan, new_pools, group_summary = [], [], []

    def insert(sql, params):
        cursor = conn.execute(sql, params)
        plan.append((sql, params))
        return cursor.lastrowid

    groups = conn.execute("SELECT id, name FROM resource_pool_group ORDER BY id").fetchall()
    reserved_group_id = conn.execute(
        "SELECT COALESCE(MAX(id),0) FROM (SELECT id FROM resource_pool_group UNION ALL "
        "SELECT group_id FROM resource_pool_group_member UNION ALL SELECT child_group_id FROM resource_pool_group_member)"
    ).fetchone()[0]
    # Recreate the original root hierarchy after a full reseed. Never import
    # orphan memberships from an old backup or attach new groups in a cycle.
    with conn:
        if not groups:
            ids = {name: insert("INSERT INTO resource_pool_group(id,name,description) VALUES(?,?,?)",
                                (reserved_group_id + index, name, "Demo pool organization"))
                   for index, name in enumerate(BASE_GROUPS, 1)}
            for name in BASE_GROUPS[:-1]:
                insert("INSERT INTO resource_pool_group_member(group_id,child_group_id) VALUES(?,?)",
                       (ids["Ressort A"], ids[name]))
            for group_name, pool_name in (("Service A", "BIM Specialist Pool"),
                                          ("Service B", "Core Engineering Pool")):
                pool = conn.execute("SELECT id FROM resource_pool WHERE name=?", (pool_name,)).fetchone()
                if pool:
                    insert("INSERT INTO resource_pool_group_member(group_id,pool_id) VALUES(?,?)",
                           (ids[group_name], pool[0]))
        elif not any(name.strip().casefold() == "service c" for _, name in groups):
            insert("INSERT INTO resource_pool_group(id,name,description) VALUES(?,?,?)",
                   (reserved_group_id + 1, "Service C", "Demo pool organization"))
    groups = conn.execute("SELECT id, name FROM resource_pool_group ORDER BY id").fetchall()
    service_c = [gid for gid, name in groups if name.strip().casefold() == "service c"]
    if len(service_c) != 1:
        raise ValueError("Exactly one existing Service C group is required.")
    employees = dict(conn.execute("SELECT employee_id, occupation_percentage FROM employee"))
    start, end = f"{year}-01-01", f"{year}-12-31"
    eligible = [eid for eid, pct in employees.items() if pct > 0 and not conn.execute(
        "SELECT 1 FROM employee_calendar_exception WHERE employee_id=? "
        "AND start_date<=? AND end_date>=?", (eid, end, start)
    ).fetchone()]
    pools_repo = ResourcePoolRepository(str(path))
    org_repo = OrganizationRepository(str(path))
    milestone_repo = MilestoneRepository(str(path))
    existing_pool_ids = [r[0] for r in conn.execute("SELECT id FROM resource_pool")]
    used_employees = set()
    for pid in existing_pool_ids:
        detail = ResourcePoolService.calculate_pool_capacity(pid, org_repo, pools_repo)
        used_employees.update(c.employee_id for c in detail.contributing_functions)
    exception_employee = next((eid for eid in reversed(eligible) if eid not in used_employees), None)
    if exception_employee is None or len(eligible) < 6:
        raise ValueError("Need six available employees, including one outside existing pools.")
    normal_employees = [eid for eid in eligible if eid != exception_employee]
    today = date.today().isoformat()
    tasks = conn.execute(
        "SELECT t.id, t.project_id, t.start_date, t.end_date FROM project_task t "
        "JOIN project p ON p.id=t.project_id WHERE t.start_date<=? AND t.end_date>=? "
        "AND t.start_date<t.end_date AND t.progress_pct<100 "
        "ORDER BY (t.start_date<=? AND t.end_date>=?) DESC, t.id",
        (end, start, today, today),
    ).fetchall()
    # Small/demo or task-free seeds must still build the hierarchy. Use any
    # overlapping task if all are completed, without altering its schedule.
    if not tasks:
        tasks = conn.execute(
            "SELECT t.id,t.project_id,t.start_date,t.end_date FROM project_task t "
            "JOIN project p ON p.id=t.project_id WHERE t.start_date<=? AND t.end_date>=? ORDER BY t.id",
            (end, start),
        ).fetchall()
    project_ids = [row[0] for row in conn.execute("SELECT id FROM project ORDER BY id")]
    # Reserve IDs referenced by old orphan records as well as real records.
    pool_id = conn.execute(
        "SELECT max(id) FROM (SELECT id FROM resource_pool UNION ALL "
        "SELECT pool_id FROM resource_pool_group_member UNION ALL "
        "SELECT pool_id FROM resource_pool_mapping UNION ALL "
        "SELECT pool_id FROM resource_pool_assignment UNION ALL SELECT pool_id FROM resource_pool_tag)"
    ).fetchone()[0] or 0
    group_id = max([gid for gid, _ in groups] + [r[0] or 0 for r in conn.execute(
        "SELECT child_group_id FROM resource_pool_group_member UNION SELECT group_id FROM resource_pool_group_member"
    )])
    with conn:
        for parent_id, parent_name in groups:
            count = rng.randint(3, 10)
            pool_count = 0
            for group_index in range(1, count + 1):
                group_id += 1
                name = f"{parent_name} / Unit {group_index:02d}"
                insert("INSERT INTO resource_pool_group(id,name,description) VALUES(?,?,?)",
                       (group_id, name, MARKER))
                insert("INSERT INTO resource_pool_group_member(group_id,child_group_id) VALUES(?,?)",
                       (parent_id, group_id))
                for pool_index in range(1, rng.randint(1, 5) + 1):
                    pool_id += 1
                    pool_count += 1
                    pool_name = f"{name} / Pool {pool_index:02d}"
                    capacity = float(rng.randint(2, 5))
                    insert("INSERT INTO resource_pool(id,name,description,capacity_fte) VALUES(?,?,?,?)",
                           (pool_id, pool_name, MARKER, capacity))
                    insert("INSERT INTO resource_pool_group_member(group_id,pool_id) VALUES(?,?)",
                           (group_id, pool_id))
                    new_pools.append(pool_id)
            group_summary.append({"parent": parent_name, "new_groups": count, "new_pools": pool_count})

        c_pools = [r[0] for r in conn.execute(
            "WITH RECURSIVE descendants(id) AS (SELECT ? UNION SELECT gm.child_group_id "
            "FROM resource_pool_group_member gm JOIN descendants d ON gm.group_id=d.id "
            "WHERE gm.child_group_id IS NOT NULL) SELECT DISTINCT gm.pool_id "
            "FROM resource_pool_group_member gm JOIN descendants d ON gm.group_id=d.id "
            "JOIN resource_pool p ON p.id=gm.pool_id ORDER BY gm.pool_id", (service_c[0],)
        )]
        scenario_ids = [pid for pid in c_pools if pid in new_pools][:3]
        roles = dict(zip(scenario_ids, ["Overallocated", "Underassigned", "Calendar exception"]))
        capacities, demands, mapping_count = {}, {}, 0
        for pid in c_pools:
            existing = {r[0] for r in conn.execute(
                "SELECT target_id FROM resource_pool_mapping WHERE pool_id=? AND target_type='employee'", (pid,)
            )}
            if len(existing) > 5:
                raise ValueError(f"Service C pool {pid} already has more than five direct employees.")
            chosen = set(existing)
            if roles.get(pid) == "Calendar exception":
                chosen.add(exception_employee)
            target = max(len(chosen), rng.randint(3, 5))
            chosen.update(rng.sample([eid for eid in normal_employees if eid not in chosen], target-len(chosen)))
            for eid in sorted(chosen-existing):
                insert("INSERT INTO resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) "
                       "VALUES(?,'employee',?,100)", (pid, eid))
                mapping_count += 1
            nominal = round(sum(employees[eid] / 100 for eid in chosen), 3)
            if pid in new_pools:
                role = roles.get(pid)
                capacity = nominal - 1 if role == "Overallocated" else nominal + 2 if role == "Underassigned" else nominal
                demand = nominal + 1 if role == "Overallocated" else nominal / 2
                if role == "Calendar exception":
                    demand = nominal - employees[exception_employee] / 200
                insert("UPDATE resource_pool SET capacity_fte=?,name=name||? WHERE id=?",
                       (max(0.0, capacity), f" - {role}" if role else "", pid))
                capacities[pid], demands[pid] = nominal, round(demand, 3)
        insert("INSERT INTO employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage,reason) "
               "VALUES(?,?,?,0,?)", (exception_employee, start, end, MARKER + ": one year unavailable"))

        assigned_pools = sorted(set(new_pools) | set(c_pools))
        project_assignment_count = task_assignment_count = 0
        for index, pid in enumerate(assigned_pools):
            if not project_ids:
                break
            if tasks:
                task_id, project_id, task_start, task_end = tasks[index % len(tasks)]
            else:
                project_id = project_ids[index % len(project_ids)]
            defined = conn.execute("SELECT capacity_fte FROM resource_pool WHERE id=?", (pid,)).fetchone()[0]
            demand = demands.get(pid, round(float(defined or 2) / 2, 3))
            assignments = [(None, start, end)]
            project_assignment_count += 1
            if tasks:
                assignments.append((task_id, max(start, task_start), min(end, task_end)))
                task_assignment_count += 1
            for tid, s, e in assignments:
                insert("INSERT INTO resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,start_date,end_date,notes) "
                       "VALUES(?,?,?,?,?,?,?)", (pid, project_id, tid, demand, s, e, MARKER))
        new_violations = set(conn.execute("PRAGMA foreign_key_check")) - baseline_violations
        if new_violations:
            raise ValueError(f"New foreign-key violations: {new_violations}")
    conn.close()

    scenarios = []
    for pid, role in roles.items():
        detail = ResourcePoolService.calculate_pool_capacity(pid, org_repo, pools_repo, milestone_repo)
        if role == "Overallocated":
            if project_ids:
                assert detail.is_overassigned and detail.peak_assigned_fte > detail.defined_capacity_fte
            assert detail.assigned_capacity_fte > detail.defined_capacity_fte
        elif role == "Underassigned":
            assert not detail.is_overassigned and detail.assigned_capacity_fte < detail.defined_capacity_fte
            assert detail.peak_assigned_fte < detail.assigned_capacity_fte
        else:
            expected = round(capacities[pid] - employees[exception_employee] / 100, 3)
            if project_ids:
                assert len(detail.daily_assigned_capacity) == (date(year+1, 1, 1)-date(year, 1, 1)).days
                assert all(abs(value-expected) < 0.001 for value in detail.daily_assigned_capacity.values())
                assert detail.is_overassigned
        scenarios.append({"role": role, "pool_id": pid, "pool": detail.pool_name,
                          "theoretical_fte": detail.defined_capacity_fte,
                          "normal_assigned_fte": detail.assigned_capacity_fte,
                          "year_assigned_fte": detail.daily_assigned_capacity.get(start, detail.assigned_capacity_fte),
                          "peak_demand_fte": detail.peak_assigned_fte,
                          "overallocated": detail.is_overassigned})
    return plan, {"parents": group_summary, "new_groups": sum(g["new_groups"] for g in group_summary),
                  "new_pools": len(new_pools), "service_c_pools": len(c_pools),
                  "new_employee_mappings": mapping_count, "new_project_assignments": project_assignment_count,
                  "new_task_assignments": task_assignment_count, "exception_employee_id": exception_employee,
                  "exception_start": start, "exception_end": end, "scenarios": scenarios,
                  "existing_foreign_key_violations": len(baseline_violations)}


@backup_before_seed
def _apply_pool_plan(db_path, plan, original_hash):
    with closing(sqlite3.connect(db_path)) as live, live:
        live.execute("PRAGMA foreign_keys=ON")
        live.execute("BEGIN IMMEDIATE")
        if fingerprint(live) != original_hash:
            raise RuntimeError("Database changed during preparation; rerun to prepare a fresh plan.")
        for sql, params in plan:
            live.execute(sql, params)


def seed_pool_scenarios(db_path=None, *, year=None, seed=20260908, apply=True):
    """Idempotent additive seed, shared by full seeding and standalone repair.

    Validate on a snapshot, back up before applying, and replay only scenario
    writes. Existing projects, tasks, dependencies and their IDs stay unchanged.
    Nested calls under a full seed share its single pre-seed backup.
    """
    target = Path(db_path or config.db_path).resolve(strict=True)
    with closing(sqlite3.connect(target)) as conn:
        if conn.execute("SELECT 1 FROM resource_pool_group WHERE description=?", (MARKER,)).fetchone():
            return {"applied": False, "already_seeded": True, "new_groups": 0, "new_pools": 0}
    with tempfile.TemporaryDirectory(prefix="pool-scenarios-") as temp:
        original_path, staged_path = Path(temp)/"original.db", Path(temp)/"staged.db"
        with closing(sqlite3.connect(target)) as live, closing(sqlite3.connect(original_path)) as original:
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("DB_NAME", "data/ppm_mock.db"))
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(seed_pool_scenarios(args.db, year=args.year, seed=args.seed, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
