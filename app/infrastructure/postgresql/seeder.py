"""Complete accepted default demo installation within an operator transaction."""

from datetime import date

import psycopg
from psycopg import sql

from app.infrastructure.postgresql.pool_scenarios import apply_pool_scenarios, prepare_pool_scenarios
from app.infrastructure.postgresql.reset import flush_projects
from app.infrastructure.postgresql.seed_catalog import (
    can_install_demo, ensure_reference_catalog, install_organization_catalog,
    install_schema_catalog, install_tag_catalog,
)
from app.infrastructure.postgresql.seed_projects import seed_sample_projects


def install_default_data(connection: psycopg.Connection, *, force: bool, include_projects: bool, year: int) -> bool:
    """Install once or explicitly reset, preserving the caller's backup boundary."""
    ensure_reference_catalog(connection)
    if force:
        flush_projects(connection, flush_all=True)
    elif not can_install_demo(connection):
        return False
    new_pools = not connection.execute('SELECT 1 FROM eppm.resource_pool LIMIT 1').fetchone()
    install_schema_catalog(connection)
    install_organization_catalog(connection)
    install_tag_catalog(connection)
    if include_projects:
        seed_sample_projects(connection)
        if new_pools:
            _sample_assignments(connection)
        _sample_tags(connection)
    connection.execute("INSERT INTO eppm.operator_seed_state(catalog) VALUES ('demo')")
    if include_projects:
        apply_pool_scenarios(connection, prepare_pool_scenarios(connection, year=year, seed=20260908))
    return True


def _sample_assignments(connection: psycopg.Connection) -> None:
    """Retain the four established scoping, delivery, BIM and advisory examples."""
    tasks = connection.execute('SELECT id,project_id FROM eppm.project_task ORDER BY id LIMIT 3').fetchall()
    rows = [
        (pool, project, task, demand, date.fromisoformat(start), date.fromisoformat(end), notes)
        for (task, project), (pool, demand, start, end, notes) in zip(tasks, (
            (1, 3.0, '2026-01-10', '2026-02-15', 'Core system scoping & discovery'),
            (1, 4.0, '2026-02-16', '2026-06-30', 'Backend development squad'),
            (2, 1.5, '2026-03-01', '2026-05-30', 'BIM 3D telemetry ingestion'),
        ))
    ]
    project = connection.execute('SELECT id FROM eppm.project ORDER BY id LIMIT 1').fetchone()
    if project:
        rows.append((3, project[0], None, 1.0, None, None, 'Portfolio advisory & oversight'))
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,start_date,end_date,notes) '
                           'VALUES (%s,%s,%s,%s,%s,%s,%s)', rows)


def _sample_tags(connection: psycopg.Connection) -> None:
    """Cycle the accepted dictionary tags over projects and tasks in ID order."""
    for target, table, owner, group in (
        ('project', 'project_tag', 'project_id', 'project_tag'),
        ('project_task', 'task_tag', 'task_id', 'Task_Tag'),
    ):
        tags = [row[0] for row in connection.execute('SELECT d.id FROM eppm.tag_dictionnary d '
            'JOIN eppm.tag_group g ON d.tag_group_id=g.id WHERE g.tag_group_name=%s ORDER BY d.id', (group,))]
        if not tags:
            continue
        identities = connection.execute(sql.SQL('SELECT id FROM eppm.{} ORDER BY id').format(sql.Identifier(target))).fetchall()
        with connection.cursor() as cursor:
            cursor.executemany(sql.SQL('INSERT INTO eppm.{} ({},tag_id) VALUES (%s,%s)').format(
                sql.Identifier(table), sql.Identifier(owner)),
                [(identity, tags[index % len(tags)]) for index, (identity,) in enumerate(identities)])
