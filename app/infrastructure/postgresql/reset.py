"""Project/reference cleanup inside an explicitly backed-up operator transaction."""

import psycopg
from psycopg import sql

from app.infrastructure.postgresql.seed_catalog import advance_seed_sequences, seed_event_types


def flush_projects(connection: psycopg.Connection, *, flush_all: bool = False) -> dict[str, int]:
    """Delete requested business data, retaining accounts, audits and finance history.

    The maintenance gateway owns backup and transaction boundaries. Native
    cascades and validation stay enabled. Project/task identities are never
    rewound, so an old explicit project grant cannot bind to a newly seeded row.
    """
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('eppm:project-identity',0))")
    projects, tasks, dependencies = connection.execute('''SELECT
        (SELECT count(*) FROM eppm.project), (SELECT count(*) FROM eppm.project_task),
        (SELECT count(*) FROM eppm.task_dependencies)''').fetchone()
    advance_seed_sequences(connection, (('project', 'id'), ('project_task', 'id')))
    connection.execute('DELETE FROM eppm.task_dependencies')
    connection.execute('UPDATE eppm.project_task SET predecessor_id=NULL WHERE predecessor_id IS NOT NULL')
    connection.execute('DELETE FROM eppm.project_task')
    connection.execute('DELETE FROM eppm.project')
    if flush_all:
        _flush_references(connection)
    return {'projects_deleted': projects, 'tasks_deleted': tasks, 'dependencies_deleted': dependencies}


def _flush_references(connection: psycopg.Connection) -> None:
    """Reset the existing demo references while retaining configurable hierarchy types."""
    for table in (
        'wbs', 'project_role', 'project_event_type',
        'project_type_property_default', 'project_type_property_rule', 'project_type_property',
    ):
        connection.execute(sql.SQL('DELETE FROM eppm.{}').format(sql.Identifier(table)))
    connection.execute('DELETE FROM eppm.project_type WHERE NOT is_general')
    connection.execute('UPDATE eppm.resource_pool SET parent_pool_id=NULL')
    for table in (
        'resource_pool', 'tag_dictionnary', 'tag_group', 'team', 'employee_function', 'employee',
    ):
        connection.execute(sql.SQL('DELETE FROM eppm.{}').format(sql.Identifier(table)))
    connection.execute('UPDATE eppm.function SET manager_function_id=NULL,dual_manager_function_id=NULL')
    for table in ('function', 'function_type', 'schema_param_options', 'schema_parameters', 'schema_groups'):
        connection.execute(sql.SQL('DELETE FROM eppm.{}').format(sql.Identifier(table)))
    connection.execute("DELETE FROM eppm.operator_seed_state WHERE catalog='demo'")
    if not connection.execute('SELECT 1 FROM eppm.project_type WHERE is_general').fetchone():
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
    seed_event_types(connection)
