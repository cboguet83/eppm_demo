"""Native reference/demo catalog installation on an explicit operator transaction."""

from decimal import Decimal
import random

import psycopg
from psycopg import sql

from app.domain.projects.project_types import PropertyValue, TemplateProperty
from app.infrastructure.postgresql.property_store import write_value
from app.infrastructure.postgresql.seed_data import (
    DEFAULT_PARAM_OPTIONS, DEFAULT_SCHEMA_GROUPS, DEFAULT_SCHEMA_PARAMETERS,
    EMPLOYEES, FUNCTIONS, FUNCTION_TYPES, TEAMS, TEAM_FUNCTIONS,
)


DEMO_TYPES = ('General', 'Infrastructure', 'Digitalisation', 'Compliance', 'Renovation')
SCOPE_DEFAULTS = {
    'Infrastructure': 'Design and delivery of railway infrastructure improvements',
    'Digitalisation': 'Digitise workflows and integrate enterprise information systems',
    'Compliance': 'Assess regulatory obligations and implement corrective actions',
}
HIERARCHY_TYPES = ('ressort', 'service', 'division', 'equipe', 'region', 'brigade', 'district')
EVENT_TYPES = ('General information', 'Blocking Point', 'Project update')
WBS_CODES = tuple(f'p.{number}.10' for number in range(1, 11))
PROJECT_ROLES = ('maintenance', 'bim', 'amo', 'etudes', 'secutite')


def install_wbs_catalog(connection: psycopg.Connection) -> None:
    """Add the ten demo WBS codes without replacing existing catalog entries."""
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO eppm.wbs(code,description) VALUES (%s,%s) ON CONFLICT(code) DO NOTHING',
                           [(code, f'descripttion projet {number}') for number, code in enumerate(WBS_CODES, 1)]
                           + [('#xx.xx.xx', 'otp fictif pour plannification')])


def install_project_roles(connection: psycopg.Connection) -> None:
    """Install the requested project-contact roles without replacing edited rows."""
    for name in PROJECT_ROLES:
        identity = connection.execute('INSERT INTO eppm.project_role(name) VALUES (%s) '
            'ON CONFLICT(lower(name)) DO UPDATE SET name=eppm.project_role.name RETURNING id', (name,)).fetchone()[0]
        connection.execute("INSERT INTO eppm.project_role_translation(catalog_id,locale,label) VALUES (%s,'en',%s) "
                           'ON CONFLICT(catalog_id,locale) DO NOTHING', (identity, name))


def ensure_reference_catalog(connection: psycopg.Connection) -> None:
    """Install initial editable reference choices once, preserving later removals."""
    if connection.execute("SELECT 1 FROM eppm.operator_seed_state WHERE catalog='reference'").fetchone():
        return
    if not connection.execute('SELECT 1 FROM eppm.hierarchy_type LIMIT 1').fetchone():
        for code in HIERARCHY_TYPES:
            identity = connection.execute('INSERT INTO eppm.hierarchy_type(code) VALUES (%s) RETURNING id', (code,)).fetchone()[0]
            with connection.cursor() as cursor:
                cursor.executemany('INSERT INTO eppm.hierarchy_type_translation(hierarchy_type_id,locale,label) VALUES (%s,%s,%s)',
                                   [(identity, locale, code) for locale in ('en', 'fr', 'de', 'lb', 'pt')])
    if not connection.execute('SELECT 1 FROM eppm.project_event_type LIMIT 1').fetchone():
        seed_event_types(connection)
    if not connection.execute('SELECT 1 FROM eppm.project_type WHERE is_general').fetchone():
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
    connection.execute("INSERT INTO eppm.operator_seed_state(catalog) VALUES ('reference')")


def seed_event_types(connection: psycopg.Connection) -> None:
    """Install the established event choices on initial setup or a full reset."""
    for name in EVENT_TYPES:
        code = 'blocking_point' if name == 'Blocking Point' else None
        identity = connection.execute('INSERT INTO eppm.project_event_type(name,system_code) VALUES (%s,%s) RETURNING id',
                                      (name, code)).fetchone()[0]
        connection.execute("INSERT INTO eppm.project_event_type_translation(catalog_id,locale,label) VALUES (%s,'en',%s)",
                           (identity, name))


def can_install_demo(connection: psycopg.Connection) -> bool:
    """Preserve populated catalogs and explicit prior demo installation markers."""
    return not connection.execute('''SELECT
        EXISTS(SELECT 1 FROM eppm.operator_seed_state WHERE catalog='demo')
        OR EXISTS(SELECT 1 FROM eppm.schema_parameters) OR EXISTS(SELECT 1 FROM eppm.schema_groups)
        OR EXISTS(SELECT 1 FROM eppm.project) OR EXISTS(SELECT 1 FROM eppm.function)
        OR EXISTS(SELECT 1 FROM eppm.project_type WHERE NOT is_general)''').fetchone()[0]


def install_schema_catalog(connection: psycopg.Connection) -> None:
    """Install accepted property groups, options, type applicability and defaults."""
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO eppm.schema_groups(id,group_name,display_order) VALUES (%s,%s,%s)', DEFAULT_SCHEMA_GROUPS)
        cursor.executemany('INSERT INTO eppm.schema_parameters(param_id,group_id,param_name,param_type,mandatory,alias) '
                           'VALUES (%s,%s,%s,%s,%s,%s)', DEFAULT_SCHEMA_PARAMETERS)
        cursor.executemany('INSERT INTO eppm.schema_param_options(param_id,option_value,display_order) VALUES (%s,%s,%s)',
                           [(parameter, option, index) for parameter, options in DEFAULT_PARAM_OPTIONS.items()
                            for index, option in enumerate(options, 1)])
        cursor.executemany('INSERT INTO eppm.project_type(name,description) VALUES (%s,%s)',
                           [(name, f'{name} projects') for name in DEMO_TYPES[1:]])
    ids = dict(connection.execute('SELECT name,id FROM eppm.project_type'))
    connection.execute("UPDATE eppm.schema_parameters SET mandatory=true WHERE param_id='PRM_011'")
    for parameter, group in connection.execute('SELECT param_id,group_id FROM eppm.schema_parameters').fetchall():
        applicable = (('Infrastructure', 'Renovation') if group == 3 else
                      ('Infrastructure', 'Digitalisation', 'Renovation') if parameter == 'PRM_015' else ())
        if applicable:
            connection.execute('UPDATE eppm.schema_parameters SET applies_to_all=false WHERE param_id=%s', (parameter,))
            with connection.cursor() as cursor:
                cursor.executemany('INSERT INTO eppm.project_type_property(project_type_id,param_id) VALUES (%s,%s)',
                                   [(ids[name], parameter) for name in applicable])
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO eppm.project_type_property_rule(project_type_id,param_id,mandatory_override) VALUES (%s,%s,%s)',
                           [(ids[name], parameter, required) for name, parameter, required in
                            [('General', 'PRM_011', False), ('Infrastructure', 'PRM_017', True), ('Compliance', 'PRM_010', True)]])
    for name, value in SCOPE_DEFAULTS.items():
        write_value(connection, ids[name], 'PRM_011', value, defaults=True)
    advance_seed_sequences(connection, (('schema_groups', 'id'),))


def install_organization_catalog(connection: psycopg.Connection) -> None:
    """Install fixed organization, people and team membership definitions."""
    tables = ('function_type', 'function', 'team', 'employee', 'team_function')
    query = sql.SQL('SELECT ') + sql.SQL(',').join(sql.SQL('EXISTS(SELECT 1 FROM eppm.{})').format(sql.Identifier(table)) for table in tables)
    present = dict(zip(tables, connection.execute(query).fetchone()))
    with connection.cursor() as cursor:
        if not present['function_type']:
            cursor.executemany('INSERT INTO eppm.function_type(function_type_id,function_type) VALUES (%s,%s)', FUNCTION_TYPES)
        if not present['function']:
            cursor.executemany('INSERT INTO eppm.function(function_id,name,hierarchy_level,function_type_id,manager_function_id,'
                               'dual_manager_function_id,fte_percentage,has_reports) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)', FUNCTIONS)
        if not present['team']:
            cursor.executemany('INSERT INTO eppm.team(team_id,team_name,manager_function_id) VALUES (%s,%s,%s)', TEAMS)
        if not present['employee']:
            cursor.executemany('INSERT INTO eppm.employee(employee_id,firstname,lastname,email,mobile,sigle,employee_code,function_id,landline) '
                               'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                               [(*row, f'+352 27 000 {row[0]:03d}') for row in EMPLOYEES])
            connection.execute('INSERT INTO eppm.employee_function(employee_id,function_id) '
                               'SELECT employee_id,function_id FROM eppm.employee WHERE function_id IS NOT NULL '
                               'ON CONFLICT DO NOTHING')
        functions = {row[0] for row in connection.execute('SELECT function_id FROM eppm.function')}
        teams = {row[0] for row in connection.execute('SELECT team_id FROM eppm.team')}
        if not present['team_function']:
            cursor.executemany('INSERT INTO eppm.team_function(team_id,function_id) VALUES (%s,%s)',
                               [(team, function) for team, function in TEAM_FUNCTIONS if team in teams and function in functions])
    advance_seed_sequences(connection, (('function_type', 'function_type_id'), ('function', 'function_id'),
        ('employee', 'employee_id'), ('team', 'team_id')))


def install_tag_catalog(connection: psycopg.Connection) -> None:
    """Preserve existing tag groups while installing missing demo tag choices."""
    groups = {name.lower().replace('_', '').replace(' ', '') for name, in connection.execute('SELECT tag_group_name FROM eppm.tag_group')}
    for name, key, tags in (
        ('project_tag', 'projecttag', ('Mission Critical', 'Regulatory Compliance', 'Strategic Initiative', 'Pilot Project')),
        ('Task_Tag', 'tasktag', ('Milestone Event', 'Critical Path', 'Security Review', 'High Complexity', 'External Dependency')),
    ):
        if key in groups or key + 's' in groups:
            continue
        identity = connection.execute('INSERT INTO eppm.tag_group(tag_group_name) VALUES (%s) RETURNING id', (name,)).fetchone()[0]
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.tag_dictionnary(tag,tag_group_id) VALUES (%s,%s)', [(tag, identity) for tag in tags])


def advance_seed_sequences(connection: psycopg.Connection, columns: tuple[tuple[str, str], ...]) -> None:
    """Advance explicit seed identities without rewinding existing sequence state."""
    for table, column in columns:
        maximum = connection.execute(sql.SQL('SELECT max({}) FROM eppm.{}').format(sql.Identifier(column), sql.Identifier(table))).fetchone()[0]
        if maximum is not None:
            sequence = connection.execute('SELECT pg_get_serial_sequence(%s,%s)', (f'eppm.{table}', column)).fetchone()[0]
            schema, name = sequence.split('.', 1)
            last, called = connection.execute(sql.SQL('SELECT last_value,is_called FROM {}.{}').format(
                sql.Identifier(schema), sql.Identifier(name))).fetchone()
            if last > maximum or last == maximum and called:
                continue
            # Repair only an explicit operator ID beyond the sequence. Blocking
            # table inserts during this repair prevents setval from overwriting
            # a normal insert's concurrent nextval. Healthy sequences need no lock.
            connection.execute(sql.SQL('LOCK TABLE eppm.{} IN SHARE ROW EXCLUSIVE MODE').format(sql.Identifier(table)))
            connection.execute(sql.SQL('SELECT setval(%s::regclass,greatest(last_value,%s),true) FROM {}.{}').format(
                sql.Identifier(schema), sql.Identifier(name)), (sequence, maximum))


def sample_values(template: list[TemplateProperty], options: dict[str, list[str]], index: int,
                  rng: random.Random) -> dict[str, PropertyValue]:
    """Generate values from current definitions without database access or mutation."""
    texts = {
        'PRM_001': f'CR-2026-{index:04d}', 'PRM_002': 'Modernise services and improve operational reliability',
        'PRM_003': 'Steering committee review scheduled', 'PRM_006': 'Lot 1',
        'PRM_009': 'Reduce delays and improve service quality',
        'PRM_010': 'Acceptance tests passed and sponsor sign-off recorded',
        'PRM_011': 'Delivery, verification, and operational handover', 'PRM_012': 'Unrelated legacy systems',
        'PRM_013': 'Supplier lead times', 'PRM_014': 'Sponsor, operations, engineering',
        'PRM_015': 'ERP, reporting, and operational systems', 'PRM_020': 'Northern section', 'PRM_021': 'Luxembourg',
        'PRM_022': 'PK 0+000', 'PRM_023': 'PK 14+500',
    }
    result: dict[str, PropertyValue] = {}
    for parameter in template:
        identity, kind = parameter['param_id'], parameter['param_type']
        if parameter['has_default'] and index % 2:
            continue
        choices = options.get(identity, [])
        if kind in ('ENUM', 'MULTI_ENUM', 'TAGS'):
            if not choices:
                if parameter['mandatory']:
                    raise ValueError(f'Cannot seed required property {identity}: no configured options')
                continue
            result[identity] = rng.choice(choices) if kind == 'ENUM' else rng.sample(choices, min(2, len(choices)))
        elif kind == 'NUMBER':
            result[identity] = Decimal(str(round(rng.uniform(49.44, 50.18) if identity == 'PRM_018' else rng.uniform(5.73, 6.53), 4)))
        elif kind == 'DATE':
            result[identity] = '2026-12-31' if identity == 'PRM_005' else '2026-01-10'
        elif kind in ('URL', 'HYPERLINK'):
            result[identity] = f'https://example.org/projects/{index}/{identity}'
        else:
            result[identity] = texts.get(identity, f"{parameter['param_name']} — example {index}")
    return result
