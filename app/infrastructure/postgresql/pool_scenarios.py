"""Prepare additive pool scenarios without modifying live rows or sequences."""

from dataclasses import dataclass
from datetime import date
import json
import random
from typing import cast

import psycopg

from app.application.ports.maintenance import PoolSeedReport, PoolScenario
from app.infrastructure.postgresql.seed_catalog import advance_seed_sequences
from app.infrastructure.postgresql.seed_plan import SeedInsert, SeedValue, next_seed_identity, source_fingerprint


MARKER = 'Pool hierarchy capacity scenarios v2'
BASE_GROUPS = ('Service A', 'Service B', 'Service C', 'Service D', 'Service E', 'Ressort A')


@dataclass(frozen=True)
class PoolScenarioPlan:
    """Frozen inputs and preview for a single backed-up operator application."""

    fingerprint: str
    inserts: tuple[SeedInsert, ...]
    report_json: str

    def report(self, *, applied: bool = False) -> PoolSeedReport:
        """Return an independent report without exposing mutable command inputs."""
        report = cast(PoolSeedReport, json.loads(self.report_json))
        report['applied'] = applied
        return report


class _Builder:
    """Build native insert rows and validate generated catalog name uniqueness."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self.inserts: list[SeedInsert] = []
        self.next_ids = {table: next_seed_identity(connection, table) for table in ('resource_pool_group', 'resource_pool')}
        self.names = {table: {row[0] for row in connection.execute(f'SELECT name FROM eppm.{table}')}
                      for table in self.next_ids}

    def insert(self, table: str, columns: tuple[str, ...], values: tuple[SeedValue, ...]) -> None:
        self.inserts.append(SeedInsert(table, columns, values))

    def named(self, table: str, name: str, *, capacity: float | None = None, description: str = MARKER) -> int:
        if name in self.names[table]:
            raise ValueError('A generated pool or group name already exists. Review the existing hierarchy before seeding.')
        identity = self.next_ids[table]
        self.next_ids[table] += 1
        self.names[table].add(name)
        columns = ('id', 'name', 'description')
        values: tuple[SeedValue, ...] = (identity, name, description)
        if table == 'resource_pool':
            columns += ('capacity_fte',)
            values += (capacity,)
        self.insert(table, columns, values)
        return identity


def _add_pool(builder: _Builder, name: str, group: int, role: str,
              employees: dict[int, float], rng: random.Random) -> tuple[PoolScenario, int]:
    """Describe one staffing scenario and its explicit employee memberships."""
    chosen = [] if role == 'Unallocated' else rng.sample(sorted(employees), min(4, len(employees)))
    assigned = round(sum(employees[employee] / 100 for employee in chosen), 3)
    capacity = (3.0 if not chosen else round(assigned / 2, 3) if role == 'Overassigned'
                else assigned + 2 if role == 'Underassigned' else assigned)
    pool = builder.named('resource_pool', f'{name} / {role}', capacity=capacity)
    builder.insert('resource_pool_group_member', ('group_id', 'pool_id'), (group, pool))
    for employee in chosen:
        builder.insert('resource_pool_mapping', ('pool_id', 'target_type', 'target_id', 'allocation_pct'),
                       (pool, 'employee', employee, 100.0))
    return PoolScenario(role=role, pool_id=pool, theoretical_fte=capacity, normal_assigned_fte=assigned), len(chosen)


def _add_demand(builder: _Builder, scenario: PoolScenario, target: tuple[int | None, int, date, date]) -> int:
    """Add project demand and, when present, matching demand for the selected task."""
    task, project, start, end = target
    demand = round((scenario['normal_assigned_fte'] or scenario['theoretical_fte']) / 2, 3)
    columns = ('pool_id', 'project_id', 'fte_assigned', 'start_date', 'end_date', 'notes')
    values: tuple[SeedValue, ...] = (scenario['pool_id'], project, demand, start, end, MARKER)
    builder.insert('resource_pool_assignment', columns, values)
    if task is not None:
        builder.insert('resource_pool_assignment', (*columns, 'task_id'), (*values, task))
    return int(task is not None)


def prepare_pool_scenarios(connection: psycopg.Connection, *, year: int, seed: int) -> PoolScenarioPlan:
    """Prepare the accepted five-unit, four-pool layout on a read-only snapshot."""
    if type(year) is not int or not 1 <= year <= 9999 or type(seed) is not int:
        raise ValueError('Pool scenarios require an integer year from 1 to 9999 and an integer seed.')
    fingerprint = source_fingerprint(connection)
    roots = connection.execute('SELECT id,name,description FROM eppm.resource_pool_group ORDER BY id').fetchall()
    if any(row[2] == MARKER for row in roots):
        return PoolScenarioPlan(fingerprint, (), json.dumps({'already_seeded': True, 'new_groups': 0, 'new_pools': 0}))
    if any(row[2] == 'Pool hierarchy capacity scenarios v1' for row in roots):
        raise ValueError('Legacy generated pool groups exist. Run a full backed-up seed to replace them.')
    employees = dict(connection.execute('SELECT employee_id,occupation_percentage FROM eppm.employee WHERE occupation_percentage>0'))
    if len(employees) < 3:
        raise ValueError('At least three employed resources are needed for pool scenarios.')
    tasks = connection.execute('SELECT id,project_id,start_date,end_date FROM eppm.project_task ORDER BY id').fetchall()
    projects = [row[0] for row in connection.execute('SELECT id FROM eppm.project ORDER BY id')]
    builder = _Builder(connection)
    if not roots:
        ids = {name: builder.named('resource_pool_group', name, description='Demo pool organization') for name in BASE_GROUPS}
        for name in BASE_GROUPS[:-1]:
            builder.insert('resource_pool_group_member', ('group_id', 'child_group_id'), (ids['Ressort A'], ids[name]))
        roots = [(identity, name, 'Demo pool organization') for name, identity in ids.items()]
    services = [(identity, name) for identity, name, _ in roots if name.strip().casefold().startswith('service ') and '/' not in name]
    rng = random.Random(seed)
    scenarios: list[PoolScenario] = []
    mappings = project_assignments = task_assignments = 0
    for service_id, service_name in services:
        for unit in range(1, 6):
            name = f'{service_name} / Unit {unit:02d}'
            group = builder.named('resource_pool_group', name)
            builder.insert('resource_pool_group_member', ('group_id', 'child_group_id'), (service_id, group))
            for role in ('Unallocated', 'Overassigned', 'Underassigned', 'Fully assigned'):
                scenario, count = _add_pool(builder, name, group, role, employees, rng)
                mappings += count
                if projects:
                    index = len(scenarios)
                    target = (tasks[(index * 37) % len(tasks)] if tasks else
                        (None, projects[index % len(projects)], date(year, 1, 1), date(year, 12, 31)))
                    task_assignments += _add_demand(builder, scenario, target)
                    project_assignments += 1
                scenarios.append(scenario)
    report = PoolSeedReport(new_groups=5 * len(services), new_pools=len(scenarios),
        parents=[{'parent': name, 'new_groups': 5, 'new_pools': 20} for _, name in services],
        new_employee_mappings=mappings, new_project_assignments=project_assignments,
        new_task_assignments=task_assignments, scenarios=scenarios, existing_foreign_key_violations=0)
    return PoolScenarioPlan(fingerprint, tuple(builder.inserts), json.dumps(report))


def apply_pool_scenarios(connection: psycopg.Connection, plan: PoolScenarioPlan) -> PoolSeedReport:
    """Verify frozen sources and apply within the gateway's backed-up transaction."""
    if source_fingerprint(connection) != plan.fingerprint:
        raise ValueError('Database changed during preparation; rerun to prepare a fresh plan.')
    for command in plan.inserts:
        command.apply(connection)
    if plan.inserts:
        advance_seed_sequences(connection, (('resource_pool_group', 'id'), ('resource_pool', 'id')))
    return plan.report(applied=bool(plan.inserts))
