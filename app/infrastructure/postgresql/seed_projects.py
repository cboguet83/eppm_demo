"""Validated operator project insertion and the accepted curated demo schedules."""

from datetime import date
from decimal import Decimal
import random

import psycopg

from app.domain.projects.budgets import EuroInput, ZERO, euro_amount
from app.domain.projects.project import normalize_project_name, prepare_project_values
from app.domain.projects.project_types import PropertyValue
from app.infrastructure.postgresql.projects import PostgresProjectStore
from app.infrastructure.postgresql.property_store import write_values
from app.infrastructure.postgresql.seed_catalog import advance_seed_sequences, sample_values


def create_seed_project(connection: psycopg.Connection, *, name: str, status: str = 'Draft',
                        project_id: int | None = None, planned_budget: EuroInput = ZERO,
                        actual_budget: EuroInput = ZERO, dynamic_attributes: dict[str, PropertyValue] | None = None,
                        function_id: int | None = None, project_type_id: int | None = None) -> int:
    """Validate the effective template and exact euros in an operator transaction.

    Operator creation uses native identity SQL. The runtime store's allocator
    intentionally requires a signed browser actor, so it is not bypassed or
    weakened to support deployment commands.
    """
    store = PostgresProjectStore(connection)
    identity = project_type_id if project_type_id is not None else store.default_type_id()
    values = prepare_project_values(store.template(identity), store.choices(), dynamic_attributes or {}, creating=True)
    fields = (normalize_project_name(name), status, euro_amount(planned_budget), euro_amount(actual_budget), function_id, identity)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('eppm:project-identity',0))")
    if project_id is None:
        advance_seed_sequences(connection, (('project', 'id'),))
        result = connection.execute('INSERT INTO eppm.project(name,status,planned_budget,actual_budget,function_id,project_type_id) '
                                    'VALUES (%s,%s,%s,%s,%s,%s) RETURNING id', fields).fetchone()[0]
    else:
        if type(project_id) is not int or project_id <= 0:
            raise ValueError('A seed project identity must be a positive integer.')
        result = connection.execute('INSERT INTO eppm.project(id,name,status,planned_budget,actual_budget,function_id,project_type_id) '
                                    'VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id', (project_id, *fields)).fetchone()[0]
        advance_seed_sequences(connection, (('project', 'id'),))
    write_values(connection, result, values)
    return result


def seed_sample_projects(connection: psycopg.Connection) -> None:
    """Create five demo projects and their existing internal/external dependencies."""
    types = dict(connection.execute('SELECT name,id FROM eppm.project_type'))
    managers = [row[0] for row in connection.execute('SELECT function_id FROM eppm.function ORDER BY function_id')]
    options: dict[str, list[str]] = {}
    for identity, value in connection.execute('SELECT param_id,option_value FROM eppm.schema_param_options ORDER BY display_order,id'):
        options.setdefault(identity, []).append(value)
    store = PostgresProjectStore(connection)
    samples = (
        ('Digitalisation', 'NextGen ERP Modernization', '450000', '380000'),
        ('Infrastructure', 'Northern Rail Capacity Upgrade', '280000', '210000'),
        ('Compliance', 'Global Supply Chain Audit', '150000', '142000'),
        ('Renovation', 'Central Station Renovation', '320000', '100000'),
        ('General', 'Portfolio Governance Review', '50000', '10000'),
    )
    rng = random.Random(42)
    last_project = last_task = None
    for index, (type_name, name, planned, actual) in enumerate(samples, 1):
        type_id = types[type_name]
        project = create_seed_project(connection, name=name,
            status='Completed' if type_name == 'Compliance' else 'In Progress',
            planned_budget=Decimal(planned), actual_budget=Decimal(actual), project_type_id=type_id,
            function_id=managers[(index + 15) % len(managers)] if managers else None,
            dynamic_attributes=sample_values(store.template(type_id), options, index, rng))
        previous = None
        for task_name, phase, start, end, progress in (
            ('Architecture & Scoping', 'FAI', date(2026, 1, 10), date(2026, 2, 15), 100),
            ('Delivery', 'EXE', date(2026, 2, 16), date(2026, 6, 30), 60),
            ('Acceptance', 'DEF', date(2026, 7, 1), date(2026, 9, 15), 0),
        ):
            task = connection.execute('INSERT INTO eppm.project_task(project_id,task_name,phase,start_date,end_date,progress_pct) '
                'VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
                (project, task_name, phase, start, end, 100 if type_name == 'Compliance' else progress)).fetchone()[0]
            if previous:
                connection.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id,link_type,lag_days) VALUES (%s,%s,'FS',0)",
                                   (task, previous))
            elif last_task:
                connection.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id,predecessor_project_id,link_type,lag_days) "
                                   "VALUES (%s,%s,%s,'SS',0)", (task, last_task, last_project))
            previous = task
        last_project, last_task = project, previous
