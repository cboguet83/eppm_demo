"""Validated native bulk projects and schedules for operator/benchmark workloads."""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from itertools import batched
import random

import psycopg
from psycopg import sql

from app.application.ports.maintenance import SeedRequest
from app.application.services.maintenance import validate_seed_request
from app.domain.projects.project import Project, normalize_project_name, prepare_project_values
from app.domain.projects.seed_statuses import project_statuses
from app.domain.projects.project_types import TemplateProperty, resolve_template
from app.domain.projects.property_values import encode_property_value
from app.infrastructure.postgresql.pool_scenarios import apply_pool_scenarios, prepare_pool_scenarios
from app.infrastructure.postgresql.seed_budgets import assign_budget_shares
from app.infrastructure.postgresql.property_store import parameters, read_values
from app.infrastructure.postgresql.seed_catalog import DEMO_TYPES, advance_seed_sequences, sample_values
from app.infrastructure.postgresql.seeder import install_default_data
from app.infrastructure.postgresql.seed_schedules import generate_schedules


PROJECT_SUFFIXES = ('Phase 1', 'Phase 2', 'Phase 3', 'Mise à jour', 'Etude', 'Pilote')
# Rows are a dynamic driver boundary; values are validated before COPY and bound
# through Psycopg's native adapters, never interpolated into SQL text.
type NativeRow = tuple[object, ...]


def _copy(connection: psycopg.Connection, table: str, columns: tuple[str, ...], rows: Iterable[NativeRow]) -> None:
    """Send bounded native batches while retaining every constraint and trigger."""
    command = sql.SQL('COPY eppm.{} ({}) FROM STDIN').format(sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)))
    with connection.cursor() as cursor:
        for batch in batched(rows, 500):
            with cursor.copy(command) as copy:
                for row in batch:
                    copy.write_row(row)


def _identities(connection: psycopg.Connection, table: str, count: int) -> list[int]:
    """Reserve real identities, including when another transaction inserts tasks."""
    advance_seed_sequences(connection, ((table, 'id'),))
    sequence = connection.execute('SELECT pg_get_serial_sequence(%s,%s)', (f'eppm.{table}', 'id')).fetchone()[0]
    return [row[0] for row in connection.execute('SELECT nextval(%s::regclass) FROM generate_series(1,%s)', (sequence, count))]


def _templates(connection: psycopg.Connection, identities: list[int]) -> dict[int, list[TemplateProperty]]:
    """Read shared definitions, membership, rules and defaults once for all types."""
    definitions = parameters(connection)
    selected: dict[int, set[str]] = {}
    for identity, parameter in connection.execute('SELECT project_type_id,param_id FROM eppm.project_type_property'):
        selected.setdefault(identity, set()).add(parameter)
    rules: dict[int, dict[str, bool | None]] = {}
    for identity, parameter, mandatory in connection.execute('SELECT project_type_id,param_id,mandatory_override FROM eppm.project_type_property_rule'):
        rules.setdefault(identity, {})[parameter] = mandatory
    defaults = read_values(connection, defaults=True)
    return {identity: resolve_template(definitions, selected.get(identity, set()), rules.get(identity, {}), defaults.get(identity, {}))
            for identity in identities}


def _projects(connection: psycopg.Connection, identities: list[int], rng: random.Random) -> tuple[list[Project], list[NativeRow], list[NativeRow]]:
    """Generate exact budgets and validated typed values from the current catalog."""
    persisted = dict(connection.execute('SELECT name,id FROM eppm.project_type ORDER BY id'))
    types = [persisted[name] for name in DEMO_TYPES if name in persisted]
    types += [identity for identity in persisted.values() if identity not in types]
    if identities and not types:
        raise ValueError('Create a project type before generating projects.')
    labels = {identity: name for name, identity in persisted.items()}
    templates = _templates(connection, types)
    options: dict[str, list[str]] = {}
    for parameter, option in connection.execute('SELECT param_id,option_value FROM eppm.schema_param_options ORDER BY display_order,id'):
        options.setdefault(parameter, []).append(option)
    choices = {parameter: set(values) for parameter, values in options.items()}
    managers = [row[0] for row in connection.execute('SELECT function_id FROM eppm.function ORDER BY function_id')]
    projects, parents, selections = [], [], []
    statuses = project_statuses(len(identities), rng)
    for index, identity in enumerate(identities):
        type_id = types[index % len(types)]
        name = normalize_project_name(f'{labels[type_id]} — {rng.choice(PROJECT_SUFFIXES)} #{identity}')
        status = statuses[index]
        with localcontext(prec=38, rounding=ROUND_HALF_EVEN):
            planned = (Decimal(50_000) + Decimal(2_950_000) * Decimal(str(rng.random()))).quantize(Decimal('0.01'))
            actual = (planned * Decimal(str(rng.random()))).quantize(Decimal('0.01'))
        template = templates[type_id]
        submitted = sample_values(template, options, identity, rng)
        manager = rng.choice(managers) if managers else None
        values = prepare_project_values(template, choices, submitted, creating=True)
        projects.append(Project(identity, name, status, planned, actual, values, manager, type_id))
        for parameter in template:
            pid = parameter['param_id']
            if pid not in values:
                continue
            kind, text, number, day, items = encode_property_value(pid, parameter['param_type'], values[pid], choices.get(pid, set()))
            parents.append((identity, pid, kind, text, number, date.fromisoformat(day) if day else None))
            selections.extend((identity, pid, position, item) for position, item in enumerate(items))
    return projects, parents, selections


def _annotations(connection: psycopg.Connection, projects: list[int], tasks: list[int]) -> None:
    """Assign only newly generated projects/tasks their cyclic tags."""
    for table, owner, group, identities in (
        ('project_tag', 'project_id', 'project_tag', projects), ('task_tag', 'task_id', 'Task_Tag', tasks),
    ):
        tags = [row[0] for row in connection.execute('SELECT d.id FROM eppm.tag_dictionnary d '
            'JOIN eppm.tag_group g ON g.id=d.tag_group_id WHERE g.tag_group_name=%s ORDER BY d.id', (group,))]
        if tags:
            _copy(connection, table, (owner, 'tag_id'), ((identity, tags[index % len(tags)]) for index, identity in enumerate(identities)))


def generate_projects(connection: psycopg.Connection, request: SeedRequest, *, year: int,
                      today: date | None = None) -> dict[str, int]:
    """Run the validated frozen generator inside one backed-up operator callback."""
    validate_seed_request(request)
    if request.random_seed is None:
        raise ValueError('Freeze the project random seed before entering a replayable transaction.')
    installed = install_default_data(connection, force=request.clean_first, include_projects=False, year=year,
                                     build_pools=not request.clean_first)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('eppm:project-identity',0))")
    identities = _identities(connection, 'project', request.projects)
    rng = random.Random(request.random_seed)
    projects, parents, selections = _projects(connection, identities, rng)
    tasks, dependencies = generate_schedules([(identity, project.status) for identity, project in zip(identities, projects)],
                                            request.min_tasks, request.max_tasks, rng, today=today)
    task_ids = _identities(connection, 'project_task', len(tasks))
    _copy(connection, 'project', ('id', 'name', 'status', 'planned_budget', 'actual_budget', 'function_id', 'project_type_id'),
          ((row.id, row.name, row.status, row.planned_budget, row.actual_budget, row.function_id, row.project_type_id) for row in projects))
    _copy(connection, 'project_property_value', ('project_id', 'param_id', 'kind', 'text_value', 'number_value', 'date_value'), parents)
    _copy(connection, 'project_property_value_item', ('project_id', 'param_id', 'position', 'value'), selections)
    _copy(connection, 'project_task', ('id', 'project_id', 'task_name', 'phase', 'start_date', 'end_date', 'progress_pct', 'description'),
          ((identity, *row) for identity, row in zip(task_ids, tasks)))
    _copy(connection, 'task_dependencies', ('task_id', 'predecessor_task_id', 'predecessor_project_id', 'link_type', 'lag_days'),
          ((task_ids[task - 1], task_ids[predecessor - 1] if predecessor is not None else None, project, kind, lag)
           for task, predecessor, project, kind, lag in dependencies))
    _annotations(connection, identities, task_ids)
    if installed:
        assign_budget_shares(connection, identities, seed=request.random_seed)
    if installed and request.clean_first:
        pools = apply_pool_scenarios(connection, prepare_pool_scenarios(connection, year=year, seed=request.random_seed))
    else:
        pools = {'new_pools': 0, 'new_containers': 0}
    return {'projects_created': len(projects), 'tasks_created': len(tasks), 'dependencies_created': len(dependencies),
            'project_types': connection.execute('SELECT count(*) FROM eppm.project_type').fetchone()[0],
            'property_values_created': len(parents), 'pools_created': pools['new_pools'], 'container_pools_created': pools['new_containers']}
