"""Typed native property values for project records and template defaults."""

from datetime import date
from decimal import Decimal
from typing import cast

from psycopg import Connection
from psycopg.rows import dict_row

from app.domain.projects.project_types import PropertyDefinition, PropertyValue
from app.domain.projects.property_values import encode_property_value


def parameters(connection: Connection) -> list[PropertyDefinition]:
    """Read explicit template fields in the established stable-ID order."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute('SELECT param_id,group_id,param_name,param_type,mandatory,alias,applies_to_all '
                              'FROM eppm.schema_parameters ORDER BY param_id COLLATE "C"').fetchall()
        return cast(list[PropertyDefinition], rows)


def write_value(connection: Connection, owner_id: int, param_id: str,
                value: PropertyValue, *, defaults: bool = False) -> None:
    """Validate and replace one value without owning its transaction."""
    write_values(connection, owner_id, {param_id: value}, defaults=defaults)


def write_values(connection: Connection, owner_id: int, values: dict[str, PropertyValue],
                 *, defaults: bool = False) -> None:
    """Batch metadata, validation and replacement for a complete property edit.

    The two table/owner pairs are fixed infrastructure identifiers. User input
    appears only in bound parameters. Native NUMERIC keeps Decimal inputs exact;
    numeric form inputs are converted once, before persistence. Unsubmitted
    properties and their selection items remain untouched.
    """
    table, owner = ('project_type_property_default', 'project_type_id') if defaults else ('project_property_value', 'project_id')
    if not values:
        return
    param_ids = list(values)
    definitions = dict(connection.execute('SELECT param_id,param_type FROM eppm.schema_parameters WHERE param_id=ANY(%s::text[])', (param_ids,)))
    choices: dict[str, set[str]] = {}
    for param_id, option in connection.execute('SELECT param_id,option_value FROM eppm.schema_param_options WHERE param_id=ANY(%s::text[])', (param_ids,)):
        choices.setdefault(param_id, set()).add(option)
    parents, selections = [], []
    for param_id, value in values.items():
        if param_id not in definitions:
            raise ValueError(f'Unknown property: {param_id}')
        kind, text, number, iso_date, items = encode_property_value(param_id, definitions[param_id], value, choices.get(param_id, set()))
        if number is not None and not isinstance(number, Decimal):
            number = Decimal(str(number)) if isinstance(number, float) else Decimal(number)
        native_date = date.fromisoformat(iso_date) if iso_date is not None else None
        parents.append((owner_id, param_id, kind, text, number, native_date))
        selections.extend((owner_id, param_id, position, item) for position, item in enumerate(items))
    connection.execute(f'DELETE FROM eppm.{table}_item WHERE {owner}=%s AND param_id=ANY(%s::text[])', (owner_id, param_ids))
    with connection.cursor() as cursor:
        cursor.executemany(
            f'INSERT INTO eppm.{table}({owner},param_id,kind,text_value,number_value,date_value) VALUES (%s,%s,%s,%s,%s,%s) '
            f'ON CONFLICT({owner},param_id) DO UPDATE SET kind=excluded.kind,text_value=excluded.text_value,'
            'number_value=excluded.number_value,date_value=excluded.date_value', parents,
        )
        cursor.executemany(f'INSERT INTO eppm.{table}_item({owner},param_id,position,value) VALUES (%s,%s,%s,%s)',
                           selections)


def read_values(connection: Connection, *, defaults: bool = False, owner_id: int | None = None,
                param_ids: list[str] | None = None) -> dict[int, dict[str, PropertyValue]]:
    """Read values and ordered selections together under the caller's snapshot.

    Scalar nulls, empty strings, empty lists and absent rows remain distinct.
    Dates retain the external ISO-string contract; numbers remain Decimal.
    Native row policies filter the parent and items before the join is returned.
    """
    if param_ids is not None and not param_ids:
        return {}
    table, owner = ('project_type_property_default', 'project_type_id') if defaults else ('project_property_value', 'project_id')
    rows = connection.execute(
        f'SELECT v.{owner},v.param_id,v.kind,v.text_value,v.number_value,'
        f"to_char(v.date_value,'YYYY-MM-DD'),i.position,i.value FROM eppm.{table} v "
        f'LEFT JOIN eppm.{table}_item i USING({owner},param_id) '
        f'WHERE (%s::bigint IS NULL OR v.{owner}=%s) AND (%s::text[] IS NULL OR v.param_id=ANY(%s::text[])) '
        f'ORDER BY v.{owner},v.param_id COLLATE "C",i.position',
        (owner_id, owner_id, param_ids, param_ids),
    )
    result: dict[int, dict[str, PropertyValue]] = {}
    for owner_key, param_id, kind, text, number, iso_date, position, item in rows:
        values = result.setdefault(owner_key, {})
        if param_id not in values:
            values[param_id] = {'null': None, 'empty': '', 'list': [], 'text': text, 'number': number, 'date': iso_date}[kind]
        if position is not None:
            selections = values[param_id]
            if not isinstance(selections, list):
                raise ValueError('Stored property selections do not match their value kind.')
            selections.append(item)
    return result
