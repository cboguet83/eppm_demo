"""Bounded portfolio SQL with server-owned expressions and bound filter values."""

from decimal import Decimal, InvalidOperation

from psycopg import sql

from app.application.ports.portfolio import PortfolioColumn


def fold(expression: sql.Composable) -> sql.Composed:
    """Preserve the legacy ASCII case-insensitive search and ordering behavior."""
    return sql.SQL("translate({},'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')").format(expression)


_PROPERTY = sql.SQL("""(SELECT CASE v.kind
    WHEN 'number' THEN to_jsonb(v.number_value)
    WHEN 'date' THEN to_jsonb(to_char(v.date_value,'YYYY-MM-DD'))
    WHEN 'text' THEN to_jsonb(v.text_value)
    WHEN 'list' THEN to_jsonb((SELECT string_agg(i.value,', ' ORDER BY i.position)
        FROM eppm.project_property_value_item i WHERE i.project_id=p.id AND i.param_id=v.param_id))
    ELSE NULL END
    FROM eppm.project_property_value v JOIN eppm.schema_parameters s USING(param_id)
    WHERE v.project_id=p.id AND v.param_id=%s AND (s.applies_to_all OR EXISTS
        (SELECT 1 FROM eppm.project_type_property m
         WHERE m.project_type_id=p.project_type_id AND m.param_id=v.param_id)))""")

DIRECTORY = sql.SQL("""occupants AS MATERIALIZED (
    SELECT DISTINCT ON(function_id) function_id,
        btrim(coalesce(firstname,'') || ' ' || coalesce(lastname,'')) AS grid_label,
        btrim(btrim(coalesce(firstname,'')) || ' ' || btrim(coalesce(lastname,''))) AS choice_label
    FROM eppm.employee_name_directory
    WHERE btrim(coalesce(firstname,'') || coalesce(lastname,''))<>''
    ORDER BY function_id,lastname COLLATE "C" NULLS FIRST,firstname COLLATE "C" NULLS FIRST
)""")


def source(columns: list[PortfolioColumn]) -> tuple[sql.Composed, list[object], dict[str, str]]:
    """Compile native fields and only requested active properties for SQL paging.

    JSONB permits each dynamic property's actual stored kind to remain numeric
    or textual. The reader decodes numbers as Decimal within its cursor only.
    """
    expressions = {
        'project_id': sql.SQL('p.id'), 'name': sql.SQL('p.name'),
        'project_template': sql.SQL('t.name'), 'status': sql.SQL('p.status'),
        'planned_budget': sql.SQL('p.planned_budget'), 'actual_budget': sql.SQL('p.actual_budget'),
        'project_manager': sql.SQL("coalesce(occupants.grid_label,f.name,'')"),
    }
    formats = {key: 'text' for key in expressions}
    formats.update(project_id='number', planned_budget='currency', actual_budget='currency')
    arguments: list[object] = []
    for column in columns:
        if column['key'] in expressions or not column.get('param_id'):
            continue
        expressions[column['key']] = _PROPERTY
        formats[column['key']] = column.get('format', 'text')
        arguments.append(column['param_id'])
    projection = sql.SQL(',').join(sql.SQL('{} AS {}').format(value, sql.Identifier(key))
                                   for key, value in expressions.items())
    query = sql.SQL("""WITH {}, portfolio AS NOT MATERIALIZED (SELECT {} FROM eppm.project p JOIN eppm.project_type t ON t.id=p.project_type_id
        LEFT JOIN eppm.active_function f ON f.function_id=p.function_id
        LEFT JOIN occupants ON occupants.function_id=p.function_id) """).format(DIRECTORY, projection)
    return query, arguments, formats


def _filter_values(values: list[object], numeric: bool) -> tuple[list[Decimal], list[str]]:
    """Accept JSON primitives and exact decimal strings returned by the component."""
    numbers, strings = [], []
    for value in values:
        if isinstance(value, str) and (not numeric or value == ''):
            strings.append(value)
        elif isinstance(value, (int, float, Decimal)) or numeric and isinstance(value, str):
            try:
                number = Decimal(int(value)) if isinstance(value, bool) else Decimal(str(value))
            except InvalidOperation:
                continue
            if number.is_finite():
                numbers.append(number)
    return numbers, strings


def where(query: dict, formats: dict[str, str], *, exclude: str | None = None) -> tuple[sql.Composable, list[object]]:
    """Bind filters after scope policies, ignoring unknown client column names."""
    clauses, arguments = [], []
    search = str(query.get('search') or '').strip()
    if search:
        clauses.append(sql.SQL('(strpos({}, {})>0 OR strpos(project_id::text,%s)>0)').format(
            fold(sql.Identifier('name')), fold(sql.Placeholder())))
        arguments.extend((search, search))
    if query.get('templates'):
        clauses.append(sql.SQL('project_template=ANY(%s::text[])'))
        arguments.append(query['templates'])
    for key, rule in (query.get('filters') or {}).items():
        if key not in formats or key == exclude or not isinstance(rule, dict):
            continue
        values = rule.get('values', [])
        if not isinstance(values, list):
            continue
        numbers, strings = _filter_values(values, formats[key] in ('currency', 'number'))
        operator = sql.SQL('NOT IN' if rule.get('mode') == 'exclude' else 'IN')
        clauses.append(sql.SQL("coalesce(to_jsonb({}),'\"\"'::jsonb) {} "
                               '(SELECT to_jsonb(v) FROM unnest(%s::numeric[]) v UNION ALL '
                               'SELECT to_jsonb(v) FROM unnest(%s::text[]) v)').format(sql.Identifier(key), operator))
        arguments.extend((numbers, strings))
    return (sql.SQL(' WHERE ') + sql.SQL(' AND ').join(clauses) if clauses else sql.SQL('')), arguments


def order(value: sql.Composable, *, descending: bool = False, insensitive: bool = True) -> sql.Composed:
    """Sort nulls, then numbers numerically, then text as the existing grid does."""
    direction = sql.SQL('DESC' if descending else 'ASC')
    text_value = sql.SQL("({} #>> '{{}}')").format(value)
    text_value = fold(text_value) if insensitive else text_value
    return sql.SQL("CASE WHEN {v} IS NULL THEN 0 WHEN jsonb_typeof({v})='number' THEN 1 ELSE 2 END {d},"
                   "CASE WHEN jsonb_typeof({v})='number' THEN ({v} #>> '{{}}')::numeric END {d},"
                   '{text} COLLATE "C" {d}').format(v=value, d=direction, text=text_value)


def facet_projection() -> sql.Composed:
    """Reuse grouped values for exact statistics, the top value and bounded choices."""
    return sql.SQL(""", grouped AS MATERIALIZED (SELECT value,count(*) n FROM facet GROUP BY value),
        totals AS (SELECT coalesce(sum(n),0)::bigint AS total,
            coalesce(sum(n) FILTER (WHERE value<>'\"\"'),0)::bigint AS filled,
            count(*) FILTER (WHERE value<>'\"\"') AS unique_values FROM grouped),
        numbers AS (SELECT min(amount) AS low,sum(amount*n) AS total,max(amount) AS high,
            coalesce(sum(n),0)::bigint AS count FROM (SELECT (value #>> '{{}}')::numeric amount,n
                FROM grouped WHERE jsonb_typeof(value)='number') values),
        common AS (SELECT value,n FROM grouped WHERE value<>'\"\"' ORDER BY n DESC,{} LIMIT 1),
        choices AS MATERIALIZED (SELECT value,n FROM grouped WHERE strpos({}, {})>0 ORDER BY {} LIMIT %s)
        SELECT totals.total,totals.filled,totals.unique_values,numbers.low,numbers.total,numbers.high,numbers.count,
            (SELECT value FROM common),(SELECT n FROM common),
            coalesce((SELECT jsonb_agg(jsonb_build_array(value,n) ORDER BY {}) FROM choices),'[]'::jsonb)
        FROM totals CROSS JOIN numbers""").format(
            order(sql.Identifier('value'), insensitive=False), fold(sql.SQL("value #>> '{}'")),
            fold(sql.Placeholder()), order(sql.Identifier('value')), order(sql.Identifier('value')))
