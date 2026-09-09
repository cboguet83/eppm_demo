"""Preview pool allocation mixes on a snapshot, then apply a backed-up SQL plan."""

from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
import random
import sqlite3
import tempfile

from app.application.ports.maintenance import AllocationPreviewRow, AllocationSeedReport
from app.domain.resources.allocation_generation import (
    AllocationGenerationRequest, allocation_fte, allocation_rates, percentage_count,
)
from app.domain.resources.capacity import calculate_capacity
from app.domain.resources.models import PoolCapacityDetail
from app.infrastructure.database.backup import backup_before_seed
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.pool_scenarios import SeedPlan, SqlValue, fingerprint
from app.infrastructure.repositories.pool_capacity import SqliteCapacityReader
from app.shared.config import config


@backup_before_seed
def clear_pool_allocations(db_path: str | None = None) -> int:
    """Delete all project/task allocations atomically, retaining pools and staffing."""
    with closing(get_db(db_path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        return connection.execute("DELETE FROM resource_pool_assignment").rowcount


def _capacity_periods(
    detail: PoolCapacityDetail, start: str, end: str,
) -> list[tuple[str, str, float]]:
    """Split allocation periods where employee calendar capacity changes."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first or last == date.max:
        raise ValueError("An allocation target has an invalid schedule period.")
    stop = last + timedelta(days=1)
    points = {first, stop}
    for value in detail.daily_assigned_capacity:
        day = date.fromisoformat(value)
        if first <= day <= last:
            points.update((day, day + timedelta(days=1)))
    boundaries = sorted(points)
    result: list[tuple[str, str, float]] = []
    for lower, upper in zip(boundaries, boundaries[1:]):
        capacity = detail.daily_assigned_capacity.get(lower.isoformat(), detail.effective_capacity_fte)
        if capacity <= 0:
            continue
        finish = (upper - timedelta(days=1)).isoformat()
        if result and result[-1][2] == capacity and date.fromisoformat(result[-1][1]) + timedelta(days=1) == lower:
            result[-1] = (result[-1][0], finish, capacity)
        else:
            result.append((lower.isoformat(), finish, capacity))
    return result


def _prepare_plan(
    path: Path, request: AllocationGenerationRequest, original_hash: str,
) -> tuple[SeedPlan, AllocationSeedReport]:
    """Generate staffing and demand on the isolated copy; retain replayable writes."""
    rng = random.Random(request.random_seed)
    today = date.today()
    with closing(get_db(str(path))) as connection:
        pools = connection.execute("SELECT id,name,capacity_fte FROM resource_pool ORDER BY id").fetchall()
        pool_ids = [row[0] for row in pools]
        rates = allocation_rates(pool_ids, request)
        unstaffed = set(rng.sample(pool_ids, percentage_count(len(pools), request.unstaffed_pools_pct)))
        projects = [row[0] for row in connection.execute("SELECT id FROM project ORDER BY id")]
        if rates and not projects:
            raise ValueError("Create projects before generating pool allocations.")
        from app.infrastructure.database.operator_context import deployment_access

        before = SqliteCapacityReader(str(path), access=deployment_access()).read(pool_ids)
        previous = {pid: calculate_capacity(value, today) for pid, value in before.items()}
        eligible = [row[0] for row in connection.execute(
            "SELECT employee_id FROM employee WHERE occupation_percentage>0 ORDER BY employee_id"
        )]
        plan: SeedPlan = []

        def execute(sql: str, values: tuple[SqlValue, ...] = ()) -> int:
            cursor = connection.execute(sql, values)
            plan.append((sql, values))
            return cursor.rowcount

        removed = mappings_removed = mappings_created = initialized = 0
        baseline = {tuple(row) for row in connection.execute("PRAGMA foreign_key_check")}
        with connection:
            removed = execute("DELETE FROM resource_pool_assignment")
            for pool in pools:
                pid = pool[0]
                if pid in unstaffed:
                    mappings_removed += execute("DELETE FROM resource_pool_mapping WHERE pool_id=?", (pid,))
                    if not pool[2] or pool[2] <= 0:
                        capacity = previous[pid].effective_capacity_fte or 1.0
                        execute("UPDATE resource_pool SET capacity_fte=? WHERE id=?", (capacity, pid))
                        initialized += 1
                else:
                    explicit = connection.execute(
                        "SELECT 1 FROM resource_pool_mapping WHERE pool_id=? "
                        "AND target_type IN ('employee','team') AND allocation_pct>0 LIMIT 1", (pid,),
                    ).fetchone()
                    if not explicit or not previous[pid].has_assigned_resources or previous[pid].assigned_capacity_fte <= 0:
                        if not eligible:
                            raise ValueError("At least one employee with positive occupation is needed for staffed pools.")
                        employee_id = rng.choice(eligible)
                        existing = connection.execute(
                            "SELECT id FROM resource_pool_mapping WHERE pool_id=? AND target_type='employee' AND target_id=?",
                            (pid, employee_id),
                        ).fetchone()
                        if existing:
                            execute("UPDATE resource_pool_mapping SET allocation_pct=100 WHERE id=?", (existing[0],))
                        else:
                            execute("INSERT INTO resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) "
                                    "VALUES (?,'employee',?,100)", (pid, employee_id))
                            mappings_created += 1
        inputs = SqliteCapacityReader(str(path), access=deployment_access()).read(pool_ids)
        details = {pid: calculate_capacity(value, today) for pid, value in inputs.items()}
        tasks = connection.execute(
            "SELECT id,project_id,start_date,end_date FROM project_task "
            "WHERE start_date IS NOT NULL AND end_date IS NOT NULL ORDER BY id"
        ).fetchall()
        bounds = {row[0]: (row[1], row[2]) for row in connection.execute(
            "SELECT project_id,MIN(start_date),MAX(end_date) FROM project_task GROUP BY project_id"
        )}
        created = 0
        with connection:
            for index, (pid, rate) in enumerate(rates.items()):
                task_id = None
                if tasks and index % 2 == 0:
                    task_id, project_id, start, end = rng.choice(tasks)
                else:
                    project_id = rng.choice(projects)
                    start, end = bounds.get(project_id, (None, None))
                    start = start or f"{today.year}-01-01"
                    end = end or f"{today.year}-12-31"
                periods = _capacity_periods(details[pid], start, end)
                if not periods:
                    raise ValueError(f"Pool #{pid} has no available capacity during the target period.")
                for first, last, capacity in periods:
                    execute(
                        "INSERT INTO resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,start_date,end_date,notes) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (pid, project_id, task_id, allocation_fte(capacity, rate), first, last,
                         f"Generated pool allocation ({rate:.2f}% of available capacity)"),
                    )
                    created += 1
            if {tuple(row) for row in connection.execute("PRAGMA foreign_key_check")} - baseline:
                raise ValueError("Generated allocations would violate database references.")
        realized = SqliteCapacityReader(str(path), access=deployment_access()).read(pool_ids)
        rows = []
        for pool in pools:
            detail = calculate_capacity(realized[pool[0]], today)
            percentages = [
                100 * demand / detail.daily_assigned_capacity.get(day, detail.effective_capacity_fte)
                for day, demand in detail.daily_usage.items() if demand > 0
            ]
            rows.append(AllocationPreviewRow(
                pool_id=pool[0], pool_name=pool[1],
                target_allocation_pct=rates.get(pool[0], 0.0),
                allocation_pct=sum(percentages) / len(percentages) if percentages else 0.0,
                maximum_allocation_pct=max(percentages, default=0.0),
                unstaffed=pool[0] in unstaffed, capacity_fte=detail.effective_capacity_fte,
            ))
        achieved_average = sum(row["allocation_pct"] for row in rows) / len(rates) if rates else 0.0
        return plan, AllocationSeedReport(
            fingerprint=original_hash, applied=False, total_pools=len(pools), allocated_pools=len(rates),
            overallocated_pools=sum(rate > 100.000001 for rate in rates.values()),
            underallocated_pools=sum(rate < 99.999999 for rate in rates.values()),
            fully_allocated_pools=sum(abs(rate - 100) <= 0.000001 for rate in rates.values()),
            unstaffed_pools=len(unstaffed), average_allocation_pct=achieved_average,
            assignments_removed=removed, assignments_created=created, mappings_removed=mappings_removed,
            mappings_created=mappings_created, capacity_limits_initialized=initialized, rows=rows,
        )


@backup_before_seed
def _apply_plan(db_path: str, plan: SeedPlan, original_hash: str) -> None:
    """Reject concurrent changes under a write lock and replay atomically."""
    with closing(get_db(db_path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        if fingerprint(connection) != original_hash:
            raise ValueError("The database changed. Preview the allocation plan again before applying it.")
        for sql, values in plan:
            connection.execute(sql, values)


def generate_pool_allocations(
    db_path: str | None, request: AllocationGenerationRequest, *, apply: bool = False,
    expected_fingerprint: str | None = None,
) -> AllocationSeedReport:
    """Preview without touching live data; apply only a validated, backed-up plan."""
    target = Path(db_path or config.db_path).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="eppm-allocation-preview-") as temporary:
        staged_path = Path(temporary) / "preview.db"
        with closing(get_db(str(target))) as live, closing(sqlite3.connect(staged_path)) as staged:
            live.backup(staged)
            original_hash = fingerprint(staged)
        if expected_fingerprint is not None and expected_fingerprint != original_hash:
            raise ValueError("The database changed. Preview the allocation plan again before applying it.")
        plan, report = _prepare_plan(staged_path, request, original_hash)
        if apply:
            _apply_plan(str(target), plan, original_hash)
            report["applied"] = True
        return report
