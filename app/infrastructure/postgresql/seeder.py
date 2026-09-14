"""Complete accepted default demo installation within an operator transaction."""

import psycopg
from psycopg import sql

from app.infrastructure.postgresql.pool_scenarios import apply_pool_scenarios, prepare_pool_scenarios
from app.infrastructure.postgresql.reset import flush_projects
from app.infrastructure.postgresql.seed_catalog import (
    can_install_demo, ensure_reference_catalog, install_organization_catalog,
    install_schema_catalog, install_tag_catalog, install_wbs_catalog, install_project_roles,
)
from app.infrastructure.postgresql.seed_projects import seed_sample_projects
from app.infrastructure.postgresql.seed_budgets import install_budget_definition, assign_budget_shares


def install_default_data(connection: psycopg.Connection, *, force: bool, include_projects: bool, year: int,
                         build_pools: bool = True) -> bool:
    """Install once; bulk full seeds defer pool planning until projects exist."""
    ensure_reference_catalog(connection)
    if force:
        flush_projects(connection, flush_all=True)
    elif not can_install_demo(connection):
        return False
    install_schema_catalog(connection)
    install_organization_catalog(connection)
    install_tag_catalog(connection)
    install_wbs_catalog(connection)
    install_project_roles(connection)
    install_budget_definition(connection, seed=20260908)
    if include_projects:
        seed_sample_projects(connection)
        _sample_tags(connection)
        assign_budget_shares(connection, [row[0] for row in connection.execute('SELECT id FROM eppm.project ORDER BY id')], seed=20260908)
    connection.execute("INSERT INTO eppm.operator_seed_state(catalog) VALUES ('demo')")
    if build_pools and not connection.execute(
        'SELECT EXISTS(SELECT 1 FROM eppm.resource_pool) OR EXISTS(SELECT 1 FROM eppm.resource_pool_group)'
    ).fetchone()[0]:
        apply_pool_scenarios(connection, prepare_pool_scenarios(connection, year=year, seed=20260908))
    return True


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
