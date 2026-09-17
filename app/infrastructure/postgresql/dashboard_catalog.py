"""Batched dashboard fields and minimal labels after current project filtering."""

from collections import Counter

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.application.ports.dashboard import DashboardCatalog
from app.domain.dashboard import DashboardProject, ancestor
from app.domain.organization.project_filters import FilterTeam, manager_team_facets
from app.infrastructure.postgresql.portfolio_query import DIRECTORY
from app.infrastructure.postgresql.property_store import parameters


def read_catalog(connection: psycopg.Connection, project_ids: list[int]) -> DashboardCatalog:
    """Read permitted projects of every status without unrelated reference labels."""
    if not project_ids:
        return DashboardCatalog([], {}, [])
    with connection.cursor(row_factory=dict_row) as cursor:
        functions = {row['function_id']: row for row in cursor.execute(sql.SQL('WITH ') + DIRECTORY + sql.SQL(
            ' SELECT f.function_id,f.name,f.hierarchy_level,f.manager_function_id,coalesce(o.grid_label,f.name) AS label '
            'FROM eppm.function f LEFT JOIN occupants o ON o.function_id=f.function_id'))}
        projects: dict[int, DashboardProject] = {}
        names = {identity: row['label'] for identity, row in functions.items()}
        levels = {level: {identity: ancestor(identity, level, functions) for identity in functions} for level in (3, 4)}
        teams: dict[int, list[str]] = {}
        memberships = connection.execute('SELECT team_id,function_id FROM eppm.team_function ORDER BY team_id,function_id').fetchall()
        organization = {row[0]: FilterTeam(*row) for row in connection.execute('''
            SELECT t.team_id,t.team_name,h.code,t.parent_team_id
            FROM eppm.team t LEFT JOIN eppm.hierarchy_type h ON h.id=t.hierarchy_type_id''')}
        organization_facets = manager_team_facets(organization, memberships)
        for team, function in memberships:
            teams.setdefault(function, []).append(str(team))
        for row in cursor.execute("""SELECT p.id,p.name,p.status,p.function_id,t.name AS template
            FROM eppm.project p JOIN eppm.project_type t ON t.id=p.project_type_id
            WHERE p.id=ANY(%s::bigint[]) ORDER BY p.id""", (project_ids,)):
            identity = row['function_id']
            third, fourth = levels[3].get(identity), levels[4].get(identity)
            fields = {'name': [row['name']], 'project_template': [row['template'] or ''], 'status': [row['status'] or ''],
                      'manager': [str(identity) if identity in functions else ''], 'level3': [str(third) if third else ''],
                      'level4': [str(fourth) if fourth else ''], 'team': teams.get(identity, ['']),
                      'project_manager': [names.get(identity, '')], 'level_3_manager_name': [names.get(third, '')]}
            fields.update(organization_facets.get(identity, {key: [''] for key in ('service', 'division', 'org_team')}))
            fields['org_manager'] = [str(identity) if identity in functions else '']
            projects[row['id']] = DashboardProject(id=row['id'], name=row['name'], fields=fields)
    ids = list(projects)
    pool_names = {}
    for project_id, pool_id, name in connection.execute('''SELECT DISTINCT a.project_id,p.id,p.name
        FROM eppm.current_resource_pool_assignment a JOIN eppm.resource_pool p ON p.id=a.pool_id
        WHERE a.fte_assigned>0 AND a.project_id=ANY(%s::bigint[]) ORDER BY a.project_id,p.id''', (ids,)):
        pool_names[str(pool_id)] = name
        projects[project_id]['fields'].setdefault('pool', []).append(str(pool_id))
    for project in projects.values():
        project['fields'].setdefault('pool', [''])
    _properties(connection, projects, ids)
    for project_id, tag in connection.execute('''SELECT pt.project_id,t.tag FROM eppm.project_tag pt
        JOIN eppm.tag_dictionnary t ON t.id=pt.tag_id WHERE pt.project_id=ANY(%s::bigint[]) ORDER BY pt.project_id,pt.tag_id''', (ids,)):
        projects[project_id]['fields'].setdefault('_project_tags', []).append(tag)
    definitions = [dict(row) for row in parameters(connection)]
    aliases: dict[str, dict[str, str]] = {}
    for identity, locale, alias in connection.execute('SELECT param_id,locale,alias FROM eppm.schema_parameter_translation'):
        aliases.setdefault(identity, {})[locale] = alias
    for definition in definitions:
        definition['translations'] = aliases.get(definition['param_id'], {})
    counts = Counter(names.values())
    labels = {str(identity): name + (f' ({functions[identity]["name"]}, #{identity})' if counts[name] > 1 else '')
              for identity, name in names.items()}
    labels[''] = ''
    team_names = {str(identity): name for identity, name in connection.execute('SELECT team_id,team_name FROM eppm.team')}
    safe_labels = {}
    for key in ('manager', 'org_manager', 'level3', 'level4', 'team', 'service', 'division', 'org_team', 'pool'):
        visible = {value for project in projects.values() for value in project['fields'].get(key, [])}
        source = pool_names if key == 'pool' else team_names if key in {'team', 'service', 'division', 'org_team'} else labels
        safe_labels[key] = {value: source.get(value, '') for value in visible}
    return DashboardCatalog(list(projects.values()), safe_labels, definitions)


def _properties(connection: psycopg.Connection, projects: dict[int, DashboardProject], project_ids: list[int]) -> None:
    """Collect current applicable scalars and ordered lists in one bounded query."""
    previous = None
    for identity, parameter, kind, value, position, item in connection.execute("""SELECT v.project_id,v.param_id,v.kind,
        CASE v.kind WHEN 'number' THEN v.number_value::text WHEN 'date' THEN to_char(v.date_value,'YYYY-MM-DD')
             ELSE v.text_value END,i.position,i.value
        FROM eppm.project_property_value v JOIN eppm.project p ON p.id=v.project_id
        JOIN eppm.schema_parameters s ON s.param_id=v.param_id
        LEFT JOIN eppm.project_property_value_item i ON i.project_id=v.project_id AND i.param_id=v.param_id
        WHERE v.project_id=ANY(%s::bigint[]) AND (s.applies_to_all OR EXISTS
            (SELECT 1 FROM eppm.project_type_property m WHERE m.project_type_id=p.project_type_id AND m.param_id=v.param_id))
        ORDER BY v.project_id,v.param_id COLLATE "C",i.position""", (project_ids,)):
        fields = projects[identity]['fields']
        if kind == 'list':
            if previous != (identity, parameter):
                fields[parameter] = []
            if position is not None:
                fields[parameter].append(item)
        else:
            fields[parameter] = [value] if value is not None else []
        previous = identity, parameter
