"""Read-only allocation simulations and frozen native operator application plans."""

from dataclasses import dataclass, replace
from datetime import date, timedelta
import json
import random
from typing import cast

import psycopg

from app.application.ports.maintenance import (
    AllocationPreviewRow, AllocationSeedReport,
)
from app.domain.resources.allocation_generation import (
    AllocationGenerationRequest, allocation_fte, allocation_rates, percentage_count,
)
from app.domain.resources.capacity import calculate_capacity
from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.models import AssignmentRow, PoolCapacityDetail, PoolMapping
from app.infrastructure.postgresql.operator_capacity import (
    read_operator_capacity_inputs,
)
from app.infrastructure.postgresql.seed_plan import SeedInsert, source_fingerprint


@dataclass(frozen=True)
class AllocationPlan:
    """Immutable mutations and report derived from one consistent source snapshot."""

    fingerprint: str
    clear_mappings: tuple[int, ...]
    capacities: tuple[tuple[int, float], ...]
    update_mappings: tuple[int, ...]
    new_mappings: tuple[tuple[int, int], ...]
    assignments: tuple[SeedInsert, ...]
    report_json: str

    def report(self, *, applied: bool = False) -> AllocationSeedReport:
        """Return an independent report while retaining frozen operation inputs."""
        result = cast(AllocationSeedReport, json.loads(self.report_json))
        result['applied'] = applied
        return result


def capacity_periods(
    detail: PoolCapacityDetail, start: str, end: str,
) -> list[tuple[str, str, float]]:
    """Split demand at calendar changes, merging equal capacity across adjacent days."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first or last == date.max:
        raise ValueError('An allocation target has an invalid schedule period.')
    stop = last + timedelta(days=1)
    points = {first, stop}
    for value in detail.capacity_calendar:
        day = date.fromisoformat(value)
        if first <= day <= last:
            points.update((day, day + timedelta(days=1)))
    result: list[tuple[str, str, float]] = []
    boundaries = sorted(points)
    for lower, upper in zip(boundaries, boundaries[1:]):
        capacity = detail.capacity_calendar.get(
            lower.isoformat(), detail.effective_capacity_fte,
        )
        if capacity <= 0:
            continue
        finish = (upper - timedelta(days=1)).isoformat()
        if (result and result[-1][2] == capacity
                and date.fromisoformat(result[-1][1]) + timedelta(days=1) == lower):
            result[-1] = (result[-1][0], finish, capacity)
        else:
            result.append((lower.isoformat(), finish, capacity))
    return result


def _staffing(
    inputs: dict[int, CapacityInputs], previous: dict[int, PoolCapacityDetail],
    unstaffed: set[int], eligible: list[int], rng: random.Random,
) -> tuple[list[tuple[int, float]], list[int], list[tuple[int, int]], int]:
    """Simulate staffing repairs in memory while preserving existing mapping IDs."""
    capacities, updates, inserts = [], [], []
    removed = 0
    for identity, values in inputs.items():
        pool = values.pool
        assert pool is not None
        if identity in unstaffed:
            removed += len(values.mappings)
            values.mappings = []
            if not pool.capacity_fte or pool.capacity_fte <= 0:
                capacity = previous[identity].effective_capacity_fte or 1.0
                values.pool = replace(pool, capacity_fte=capacity)
                capacities.append((identity, capacity))
            continue
        explicit = any(
            mapping.target_type in ('employee', 'team') and mapping.allocation_pct > 0
            for mapping in values.mappings
        )
        if (explicit and previous[identity].has_assigned_resources
                and previous[identity].assigned_capacity_fte > 0):
            continue
        if not eligible:
            raise ValueError(
                'At least one employee with positive occupation is needed for staffed pools.',
            )
        employee = rng.choice(eligible)
        existing = next((mapping for mapping in values.mappings
                         if mapping.target_type == 'employee'
                         and mapping.target_id == employee), None)
        if existing is not None:
            assert existing.id is not None
            updates.append(existing.id)
            existing.allocation_pct = 100.0
        else:
            inserts.append((identity, employee))
            values.mappings.append(PoolMapping(identity, 'employee', employee))
    return capacities, updates, inserts, removed


def _assignment(
    values: CapacityInputs, *, identity: int, project: int, project_name: str,
    task: int | None, task_name: str | None, start: str, end: str,
    demand: float, notes: str,
) -> SeedInsert:
    """Describe a native insert and the corresponding simulated capacity input."""
    assert values.pool is not None
    values.assignments.append(AssignmentRow(
        id=identity, pool_id=values.pool_id, pool_name=values.pool.name,
        project_id=project, project_name=project_name, task_id=task, task_name=task_name,
        task_start_date=None, task_end_date=None, fte_assigned=demand,
        custom_start_date=start, custom_end_date=end,
        effective_start_date=start, effective_end_date=end, notes=notes,
    ))
    return SeedInsert(
        'resource_pool_assignment',
        ('pool_id', 'project_id', 'task_id', 'fte_assigned', 'start_date', 'end_date', 'notes'),
        (values.pool_id, project, task, demand,
         date.fromisoformat(start), date.fromisoformat(end), notes),
    )


def _preview_rows(
    inputs: dict[int, CapacityInputs], rates: dict[int, float],
    unstaffed: set[int], today: date,
) -> list[AllocationPreviewRow]:
    """Measure the realized daily usage with the existing pure capacity rules."""
    rows = []
    for identity, values in inputs.items():
        detail = calculate_capacity(values, today)
        percentages = [
            100 * demand / detail.capacity_calendar.get(day, detail.effective_capacity_fte)
            for day, demand in detail.daily_usage.items() if demand > 0
        ]
        rows.append(AllocationPreviewRow(
            pool_id=identity, pool_name=detail.pool_name,
            target_allocation_pct=rates.get(identity, 0.0),
            allocation_pct=sum(percentages) / len(percentages) if percentages else 0.0,
            maximum_allocation_pct=max(percentages, default=0.0),
            unstaffed=identity in unstaffed, capacity_fte=detail.effective_capacity_fte,
        ))
    return rows


def prepare_allocation_plan(
    connection: psycopg.Connection, request: AllocationGenerationRequest, *,
    today: date, expected_fingerprint: str | None = None,
) -> AllocationPlan:
    """Validate and simulate an allocation mix without writing rows or sequences."""
    fingerprint = source_fingerprint(connection)
    if expected_fingerprint is not None and expected_fingerprint != fingerprint:
        raise ValueError(
            'The database changed. Preview the allocation plan again before applying it.',
        )
    from app.domain.resources.hierarchy import PoolHierarchy
    from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore
    tree = PoolHierarchy(PostgresResourcePoolStore(connection).get_all_pools())
    pool_ids = sorted(identity for identity in tree.pools if not tree.children.get(identity))
    rates = allocation_rates(pool_ids, request)
    rng = random.Random(request.random_seed)
    unstaffed = set(rng.sample(
        pool_ids, percentage_count(len(pool_ids), request.unstaffed_pools_pct),
    ))
    projects = dict(connection.execute('SELECT id,name FROM eppm.project ORDER BY id'))
    if rates and not projects:
        raise ValueError('Create projects before generating pool allocations.')
    inputs = read_operator_capacity_inputs(connection, pool_ids)
    previous = {identity: calculate_capacity(values, today)
                for identity, values in inputs.items()}
    eligible = [row[0] for row in connection.execute(
        'SELECT employee_id FROM eppm.employee '
        'WHERE occupation_percentage>0 ORDER BY employee_id',
    )]
    removed = sum(len(values.assignments) for values in inputs.values())
    for values in inputs.values():
        values.assignments = []
    capacities, updates, mappings, mappings_removed = _staffing(
        inputs, previous, unstaffed, eligible, rng,
    )
    details = {identity: calculate_capacity(values, today)
               for identity, values in inputs.items()}
    tasks = connection.execute(
        'SELECT id,project_id,start_date,end_date,task_name '
        'FROM eppm.project_task ORDER BY id',
    ).fetchall()
    project_ids = list(projects)
    assignments = []
    for index, (identity, rate) in enumerate(rates.items()):
        if tasks and index % 2 == 0:
            task, project, start_day, end_day, task_name = rng.choice(tasks)
            start, end = start_day.isoformat(), end_day.isoformat()
        else:
            project, task, task_name = rng.choice(project_ids), None, None
            start, end = inputs[identity].project_bounds.get(project, (None, None))
            start, end = start or f'{today.year}-01-01', end or f'{today.year}-12-31'
        periods = capacity_periods(details[identity], start, end)
        if not periods:
            raise ValueError(
                f'Pool #{identity} has no available capacity during the target period.',
            )
        for first, last, capacity in periods:
            assignments.append(_assignment(
                inputs[identity], identity=len(assignments) + 1,
                project=project, project_name=projects[project],
                task=task, task_name=task_name, start=first, end=last,
                demand=allocation_fte(capacity, rate),
                notes=f'Generated pool allocation ({rate:.2f}% of available capacity)',
            ))
    rows = _preview_rows(inputs, rates, unstaffed, today)
    report = AllocationSeedReport(
        fingerprint=fingerprint, applied=False, total_pools=len(pool_ids),
        allocated_pools=len(rates), unstaffed_pools=len(unstaffed),
        overallocated_pools=sum(rate > 100.000001 for rate in rates.values()),
        underallocated_pools=sum(rate < 99.999999 for rate in rates.values()),
        fully_allocated_pools=sum(abs(rate - 100) <= 0.000001 for rate in rates.values()),
        average_allocation_pct=sum(row['allocation_pct'] for row in rows) / len(rates) if rates else 0.0,
        assignments_removed=removed, assignments_created=len(assignments),
        mappings_removed=mappings_removed, mappings_created=len(mappings),
        capacity_limits_initialized=len(capacities), rows=rows,
    )
    return AllocationPlan(
        fingerprint, tuple(sorted(unstaffed)), tuple(capacities), tuple(updates),
        tuple(mappings), tuple(assignments), json.dumps(report),
    )


def apply_allocation_plan(
    connection: psycopg.Connection, plan: AllocationPlan,
) -> AllocationSeedReport:
    """Apply frozen changes atomically inside the caller's backed-up transaction."""
    if source_fingerprint(connection) != plan.fingerprint:
        raise ValueError(
            'The database changed. Preview the allocation plan again before applying it.',
        )
    connection.execute('DELETE FROM eppm.resource_pool_assignment')
    connection.execute(
        'DELETE FROM eppm.resource_pool_mapping WHERE pool_id=ANY(%s::bigint[])',
        (list(plan.clear_mappings),),
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            'UPDATE eppm.resource_pool SET capacity_fte=%s WHERE id=%s',
            [(capacity, identity) for identity, capacity in plan.capacities],
        )
        cursor.executemany(
            'UPDATE eppm.resource_pool_mapping SET allocation_pct=100 WHERE id=%s',
            [(identity,) for identity in plan.update_mappings],
        )
        cursor.executemany(
            'INSERT INTO eppm.resource_pool_mapping'
            "(pool_id,target_type,target_id,allocation_pct) VALUES (%s,'employee',%s,100)",
            plan.new_mappings,
        )
    for assignment in plan.assignments:
        assignment.apply(connection)
    return plan.report(applied=True)
