"""Typed native property values for project records and template defaults."""

from datetime import date
from decimal import Decimal
from typing import cast

from psycopg import Connection
from psycopg.rows import dict_row

from app.domain.projects.project_types import PropertyDefinition, PropertyValue
from app.domain.projects.property_values import encode_property_value


type ParentValue = tuple[int, str, str, str | None, Decimal | None, date | None]
type SelectionValue = tuple[int, str, int, str]


def _changed_parameters(connection: Connection, table: str, owner: str, owner_id: int,
                        parents: list[ParentValue], selections: list[SelectionValue]) -> set[str]:
    """Compare physical representations, including selection order and positions."""
    stored_parents: dict[str, ParentValue] = {}
    stored_items: dict[str, list[SelectionValue]] = {}
    requested_items: dict[str, list[SelectionValue]] = {}
    for item in selections:
        requested_items.setdefault(item[1], []).append(item)
    for row in connection.execute(
        f'SELECT v.{owner},v.param_id,v.kind,v.text_value,v.number_value,'
        f"to_char(v.date_value,'YYYY-MM-DD'),i.position,i.value "
        f'FROM eppm.{table} v LEFT JOIN eppm.{table}_item i USING({owner},param_id) '
        f'WHERE v.{owner}=%s AND v.param_id=ANY(%s::text[]) ORDER BY v.param_id COLLATE "C",i.position',
        (owner_id, [parent[1] for parent in parents]),
    ):
        stored_parents[row[1]] = (*row[:5], date.fromisoformat(row[5]) if row[5] is not None else None)
        if row[6] is not None:
            stored_items.setdefault(row[1], []).append((row[0], row[1], row[6], row[7]))
    return {parent[1] for parent in parents
            if stored_parents.get(parent[1]) != parent
            or stored_items.get(parent[1], []) != requested_items.get(parent[1], [])}


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
                 *, defaults: bool = False, skip_unchanged: bool = False) -> None:
    """Batch metadata, validation and replacement for a complete property edit.

    The two table/owner pairs are fixed infrastructure identifiers. User input
    appears only in bound parameters. Native NUMERIC keeps Decimal inputs exact;
    numeric form inputs are converted once, before persistence. Unsubmitted
    properties and their selection items remain untouched.

    A caller that has already authorized the owner mutation may request
    ``skip_unchanged``. Every submitted value is still validated; only identical
    physical rows are omitted from persistence. The default retains per-row
    write guards for direct callers without an earlier owner mutation.
    """
    table, owner = ('project_type_property_default', 'project_type_id') if defaults else ('project_property_value', 'project_id')
    if not values:
        return
    param_ids = list(values)
    definitions = dict(connection.execute('SELECT param_id,param_type FROM eppm.schema_parameters WHERE param_id=ANY(%s::text[])', (param_ids,)))
    choices: dict[str, set[str]] = {}
    for param_id, option in connection.execute('SELECT param_id,option_value FROM eppm.schema_param_options WHERE param_id=ANY(%s::text[])', (param_ids,)):
        choices.setdefault(param_id, set()).add(option)
    parents: list[ParentValue] = []
    selections: list[SelectionValue] = []
    for param_id, value in values.items():
        if param_id not in definitions:
            raise ValueError(f'Unknown property: {param_id}')
        kind, text, number, iso_date, items = encode_property_value(param_id, definitions[param_id], value, choices.get(param_id, set()))
        if number is not None and not isinstance(number, Decimal):
            number = Decimal(str(number)) if isinstance(number, float) else Decimal(number)
        native_date = date.fromisoformat(iso_date) if iso_date is not None else None
        parents.append((owner_id, param_id, kind, text, number, native_date))
        selections.extend((owner_id, param_id, position, item) for position, item in enumerate(items))
    if skip_unchanged:
        changed = _changed_parameters(connection, table, owner, owner_id, parents, selections)
        parents = [parent for parent in parents if parent[1] in changed]
        selections = [item for item in selections if item[1] in changed]
        param_ids = [parent[1] for parent in parents]
        if not parents:
            return
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
