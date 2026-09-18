"""Atomic function imports with generated identities and primary reporting ancestry."""

import csv
from dataclasses import dataclass, fields, replace
from io import StringIO

from app.application.ports.organization import OrganizationStore
from app.domain.organization.function_hierarchy import FunctionHierarchyError, validate_function_hierarchy
from app.domain.organization.models import OrgFunction
from app.domain.organization.rules import normalize_function, validate_function


@dataclass(frozen=True)
class FunctionImportResult:
    """Counts of committed inserts, updates and optional missing-row deletions."""

    created: int
    updated: int
    deleted: int


def _identity(value: str, column: str) -> int | None:
    if not value:
        return None
    try:
        identity = int(value)
    except ValueError as error:
        raise ValueError(f'{column} must be a positive integer.') from error
    if not 0 < identity <= 9223372036854775807:
        raise ValueError(f'{column} must be a positive integer.')
    return identity


def _row_source(number: int, function: OrgFunction) -> str:
    """Describe the CSV record using its supplied identity, never a generated ID."""
    identity = f', function_id={function.function_id}' if function.function_id is not None else ''
    return f'Row {number}, function "{function.name}"{identity}'


def parse_functions(content: bytes) -> list[OrgFunction]:
    """Parse UTF-8 comma/semicolon CSV with row-specific validation errors."""
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise ValueError('The CSV must use UTF-8 encoding.') from error
    reader = csv.DictReader(StringIO(text, newline=''),
        delimiter=';' if ';' in text.partition('\n')[0] else ',', strict=True)
    result = []
    seen: set[int] = set()
    try:
        columns = reader.fieldnames or []
        if 'name' not in columns or len(set(columns)) != len(columns):
            raise ValueError('The CSV requires unique headers including name.')
        unknown = set(columns) - {field.name for field in fields(OrgFunction)}
        if unknown:
            raise ValueError('Unsupported CSV columns: ' + ', '.join(sorted(unknown)) + '. Use the current template.')
        for number, row in enumerate(reader, 2):
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('The number of values does not match the header.')
                row = {key: value.strip() for key, value in row.items()}
                deleted = row.get('deleted_flag', '').lower() or 'false'
                if deleted not in {'true', 'false', '0', '1'}:
                    raise ValueError('deleted_flag must be true or false.')
                identifiers = {key: _identity(row.get(key, ''), key) for key in
                    ('function_id', 'function_type_id', 'manager_function_id', 'dual_manager_function_id')}
                try:
                    percentage = int(row.get('fte_percentage') or '100')
                except ValueError as error:
                    raise ValueError('fte_percentage must be a whole number between 0 and 100.') from error
                validate_function(row['name'], percentage)
                function = normalize_function(OrgFunction(row['name'],
                    **identifiers, fte_percentage=percentage,
                    deleted_flag=deleted in {'true', '1'}))
                if function.function_id is not None:
                    if function.function_id in seen:
                        raise ValueError(f'Duplicate function_id {function.function_id}.')
                    seen.add(function.function_id)
                result.append(function)
            except ValueError as error:
                label = row.get('name', '')
                raise ValueError(f'Row {number}, function "{label}": {error}') from error
    except csv.Error as error:
        raise ValueError(f'Invalid CSV near line {reader.line_num}: {error}. Check quotes and separators.') from error
    if not result:
        raise ValueError('The CSV contains no function records.')
    return result


def import_functions(store: OrganizationStore, functions: list[OrgFunction], *,
                     delete_missing: bool = False) -> FunctionImportResult:
    """Resolve file identities and validate the complete final catalog atomically."""
    existing = {item.function_id: item for item in store.get_all_functions(include_deleted=True)}
    source_ids = set(existing) | {item.function_id for item in functions if item.function_id is not None}
    type_ids = {item.function_type_id for item in store.get_all_function_types()}
    for number, item in enumerate(functions, 2):
        for field in ('manager_function_id', 'dual_manager_function_id'):
            identity = getattr(item, field)
            if identity is not None and identity not in source_ids:
                raise ValueError(f'{_row_source(number, item)}: {field}={identity} is unknown. '
                                 'Include the manager row in the CSV or use an existing function ID.')
        if not item.deleted_flag and item.function_type_id is not None and item.function_type_id not in type_ids:
            raise ValueError(f'{_row_source(number, item)}: function_type_id={item.function_type_id} '
                             'does not identify an active function type.')
    aliases: dict[int, int] = {}
    resolved = []
    created = 0
    for item in functions:
        identity = item.function_id
        if identity not in existing:
            identity = store.create_function(replace(item, function_id=None, manager_function_id=None,
                dual_manager_function_id=None, function_type_id=None))
            created += 1
        if item.function_id is not None:
            aliases[item.function_id] = identity
        resolved.append(replace(item, function_id=identity))
    included = {item.function_id for item in resolved}
    omitted = {identity for identity, item in existing.items()
               if delete_missing and identity not in included and not item.deleted_flag}
    final = {identity: replace(item, deleted_flag=True) if identity in omitted else item
             for identity, item in existing.items()}
    for item in resolved:
        final[item.function_id] = replace(item,
            manager_function_id=aliases.get(item.manager_function_id, item.manager_function_id),
            dual_manager_function_id=aliases.get(item.dual_manager_function_id, item.dual_manager_function_id))
    sources = {item.function_id: _row_source(number, original)
               for number, (item, original) in enumerate(zip(resolved, functions), 2)}
    try:
        validate_function_hierarchy(list(final.values()))
    except FunctionHierarchyError as error:
        source = sources.get(error.function_id, 'Existing function outside the CSV')
        deletion_hint = ' Check the delete-missing option and retained child functions.' if omitted else ''
        raise ValueError(f'{source}: hierarchy validation failed. {error}{deletion_hint}') from error
    for identity, item in final.items():
        if item != existing.get(identity):
            try:
                store.write_imported_function(item)
            except ValueError as error:
                source = sources.get(identity, f'Existing function "{item.name}" (ID {identity}), marked deleted')
                raise ValueError(f'{source}: could not save the function. {error}') from error
    return FunctionImportResult(created, len(functions) - created, len(omitted))
