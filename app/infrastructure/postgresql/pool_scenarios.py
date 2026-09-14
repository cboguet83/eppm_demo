"""Prepare and atomically install the Ressort A hierarchy and Python demand plan."""

from dataclasses import dataclass
from datetime import date
import json
from typing import cast

import psycopg
from psycopg import sql

from app.application.ports.maintenance import PoolSeedReport
from app.domain.resources.pool_seed import GROUPS, POOLS, ProjectPeriod, TaskPeriod, plan_demand
from app.infrastructure.postgresql.seed_catalog import advance_seed_sequences
from app.infrastructure.postgresql.seed_plan import SeedInsert, SeedValue, next_seed_identity, source_fingerprint


MARKER = 'Ressort A pool seed v4'
REPLACED_TABLES = ('resource_pool_assignment', 'resource_pool_mapping', 'resource_pool_group_member',
                   'resource_pool_tag', 'resource_pool', 'resource_pool_group')


@dataclass(frozen=True)
class PoolScenarioPlan:
    """Frozen commands and preview for one backed-up operator transaction."""

    fingerprint: str
    inserts: tuple[SeedInsert, ...]
    report_json: str
    replace: bool = False

    def report(self, *, applied: bool = False) -> PoolSeedReport:
        """Return an independent report without exposing mutable commands."""
        report = cast(PoolSeedReport, json.loads(self.report_json))
        report['applied'] = applied
        return report


class _Builder:
    """Reserve provisional identities without advancing database sequences."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self.inserts: list[SeedInsert] = []
        self.next_ids = {table: next_seed_identity(connection, table)
                         for table in ('resource_pool_group', 'resource_pool', 'hierarchy_type')}

    def insert(self, table: str, columns: tuple[str, ...], values: tuple[SeedValue, ...]) -> None:
        self.inserts.append(SeedInsert(table, columns, values))

    def identity(self, table: str) -> int:
        identity = self.next_ids[table]
        self.next_ids[table] += 1
        return identity


def _hierarchy_types(connection: psycopg.Connection, builder: _Builder) -> dict[str, int]:
    """Stage missing required codes and translations, retaining existing labels."""
    identities = dict(connection.execute('SELECT code,id FROM eppm.hierarchy_type'))
    translations = set(connection.execute('SELECT hierarchy_type_id,locale FROM eppm.hierarchy_type_translation'))
    for code in ('ressort', 'service', 'division', 'equipe'):
        if code not in identities:
            identities[code] = builder.identity('hierarchy_type')
            builder.insert('hierarchy_type', ('id', 'code'), (identities[code], code))
        for locale in ('en', 'fr', 'de', 'lb', 'pt'):
            if (identities[code], locale) not in translations:
                builder.insert('hierarchy_type_translation', ('hierarchy_type_id', 'locale', 'label'),
                               (identities[code], locale, code))
    return identities


def prepare_pool_scenarios(connection: psycopg.Connection, *, year: int, seed: int,
                           replace: bool = False) -> PoolScenarioPlan:
    """Prepare the fixed layout; replacing any existing pools requires opt-in."""
    if type(year) is not int or not 1 <= year <= 9999 or type(seed) is not int:
        raise ValueError('Pool scenarios require an integer year from 1 to 9999 and an integer seed.')
    fingerprint = source_fingerprint(connection)
    counts = {table: connection.execute(sql.SQL('SELECT count(*) FROM eppm.{}').format(sql.Identifier(table))).fetchone()[0]
              for table in REPLACED_TABLES}
    installed = connection.execute('SELECT 1 FROM eppm.resource_pool_group WHERE description IN (%s,%s)',
                                   (MARKER, 'Ressort A pool seed v3')).fetchone()
    if installed and not replace:
        return PoolScenarioPlan(fingerprint, (), json.dumps({'already_seeded': True, 'new_groups': 0, 'new_pools': 0}))
    if (counts['resource_pool'] or counts['resource_pool_group']) and not replace:
        raise ValueError('An existing pool layout requires explicit --replace; preview it before applying.')
    builder = _Builder(connection)
    types = _hierarchy_types(connection, builder)
    groups: dict[str, int] = {}
    hierarchy = []
    for name, parent, code in GROUPS:
        identity = builder.identity('resource_pool_group')
        groups[name] = identity
        builder.insert('resource_pool_group', ('id', 'name', 'description', 'hierarchy_type_id'),
                       (identity, name, MARKER, types[code]))
        if parent:
            builder.insert('resource_pool_group_member', ('group_id', 'child_group_id'), (groups[parent], identity))
        hierarchy.append({'name': name, 'parent': parent, 'hierarchy_type': code, 'kind': 'group'})
    pool_ids = {}
    for pool in POOLS:
        identity = builder.identity('resource_pool')
        pool_ids[pool.name] = identity
        builder.insert('resource_pool', ('id', 'name', 'description', 'hierarchy_type_id', 'capacity_fte'),
                       (identity, pool.name, MARKER, types[pool.hierarchy_type], pool.capacity))
        builder.insert('resource_pool_group_member', ('group_id', 'pool_id'), (groups[pool.parent], identity))
        hierarchy.append({'name': pool.name, 'parent': pool.parent, 'hierarchy_type': pool.hierarchy_type,
                          'kind': 'pool', 'capacity_fte': pool.capacity})
    periods = [ProjectPeriod(identity, start or date(year, 1, 1), end or date(year, 12, 31))
               for identity, start, end in connection.execute(
                   'SELECT p.id,min(t.start_date),max(t.end_date) FROM eppm.project p '
                   'LEFT JOIN eppm.project_task t ON t.project_id=p.id '
                   'AND t.start_date IS NOT NULL AND t.end_date IS NOT NULL GROUP BY p.id ORDER BY p.id')]
    tasks = [TaskPeriod(identity, project_id, start, end) for identity, project_id, start, end in connection.execute(
        'SELECT id,project_id,start_date,end_date FROM eppm.project_task '
        'WHERE start_date IS NOT NULL AND end_date IS NOT NULL AND end_date>=start_date ORDER BY id')]
    demand, rates, omitted = plan_demand(periods, seed, tasks=tasks)
    for row in demand:
        builder.insert('resource_pool_assignment', ('pool_id', 'project_id', 'task_id', 'fte_assigned', 'notes'),
                       (pool_ids[row.pool_name], row.project_id, row.task_id, row.milli_fte / 1000, MARKER))
    report = dict(new_groups=7, new_pools=33, replacement=replace,
                  removed=counts if replace else {table: 0 for table in REPLACED_TABLES},
                  hierarchy=hierarchy, fingerprint=fingerprint, seed=seed, year=year,
                  total_projects=len(periods), allocated_projects=len(periods) - omitted,
                  unallocated_projects=omitted, pools_used=len(rates),
                  overallocated_pools=sum(rate == 150 for rate in rates.values()),
                  underallocated_pools=sum(rate < 100 for rate in rates.values()),
                  fully_allocated_pools=sum(rate == 100 for rate in rates.values()),
                  peak_utilization_pct=180 if any(rate > 100 for rate in rates.values()) else max(rates.values(), default=0),
                  new_employee_mappings=0, new_project_assignments=sum(row.task_id is None for row in demand),
                  new_task_assignments=sum(row.task_id is not None for row in demand),
                  scenarios=[dict(pool_id=pool_ids[pool.name], pool_name=pool.name,
                                  theoretical_fte=pool.capacity, normal_assigned_fte=pool.capacity,
                                  role='Overallocated' if rates.get(pool.name, 0) > 100 else 'Underallocated' if rates.get(pool.name, 0) < 100 else 'Within capacity',
                                  exceptional_utilization_pct=rates.get(pool.name, 0)) for pool in POOLS])
    return PoolScenarioPlan(fingerprint, tuple(builder.inserts), json.dumps(report), replace)


def apply_pool_scenarios(connection: psycopg.Connection, plan: PoolScenarioPlan) -> PoolSeedReport:
    """Verify sources and replace pools inside the caller's protected transaction.

    Deleting pool owners also cascades derived capacity calendars and revisions.
    Employee calendars, projects, finance and accounts are never deleted here.
    Identities continue from their current sequence high-water marks.
    """
    if source_fingerprint(connection) != plan.fingerprint:
        raise ValueError('Database changed during preparation; rerun to prepare a fresh plan.')
    if plan.replace:
        for table in REPLACED_TABLES:
            connection.execute(sql.SQL('DELETE FROM eppm.{}').format(sql.Identifier(table)))
    for command in plan.inserts:
        command.apply(connection)
    if plan.inserts:
        advance_seed_sequences(connection, (('resource_pool_group', 'id'), ('resource_pool', 'id'), ('hierarchy_type', 'id')))
    return plan.report(applied=bool(plan.inserts))
