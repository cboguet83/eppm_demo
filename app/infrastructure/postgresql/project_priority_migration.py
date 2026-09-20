"""Preserve legacy strategic priorities before removing their parameter schema."""

import psycopg


def migrate_project_priority(connection: psycopg.Connection) -> None:
    """Map legacy values, reject unknowns, then retire PRM_027 and stored money."""
    priorities = dict(connection.execute('SELECT code,id FROM eppm.strategic_priority'))
    values = connection.execute("SELECT project_id,text_value FROM eppm.project_property_value WHERE param_id='PRM_027'").fetchall()
    updates = []
    for project, value in values:
        code = (value or '').strip().casefold()
        code = 'strategic' if code == 'critical' else code
        if code and code not in priorities:
            raise ValueError('Unknown PRM_027 priority; migration stopped without discarding values.')
        updates.append((priorities.get(code), project))
    with connection.cursor() as cursor:
        cursor.executemany('UPDATE eppm.project SET strategic_priority_id=%s WHERE id=%s', updates)
    connection.execute("DELETE FROM eppm.project_property_value WHERE param_id='PRM_027'")
    connection.execute("DELETE FROM eppm.project_type_property_default WHERE param_id='PRM_027'")
    connection.execute("DELETE FROM eppm.schema_param_options WHERE param_id='PRM_027'")
    connection.execute("DELETE FROM eppm.schema_parameters WHERE param_id='PRM_027'")
    connection.execute('ALTER TABLE eppm.project DROP COLUMN planned_budget, DROP COLUMN actual_budget')
