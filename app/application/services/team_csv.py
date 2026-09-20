"""Atomic team catalog imports with generated identities and hierarchy validation."""

import csv
from dataclasses import dataclass, replace
from io import StringIO

from app.application.ports.organization import OrganizationStore
from app.domain.organization.models import Team
from app.domain.organization.rules import normalize_team, validate_team_parent

TEAM_CSV_COLUMNS = ('team_name', 'team_id', 'manager_function_id', 'hierarchy_type_id', 'parent_team_id', 'deleted_flag')


@dataclass(frozen=True)
class TeamImportResult:
    """Committed team catalog import counts."""

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
    if identity <= 0:
        raise ValueError(f'{column} must be a positive integer.')
    return identity


def parse_teams(content: bytes) -> list[Team]:
    """Parse UTF-8 CSV, accepting comma or semicolon separators."""
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
        if 'team_name' not in columns or len(set(columns)) != len(columns):
            raise ValueError('The CSV requires unique headers including team_name.')
        unknown = set(columns) - set(TEAM_CSV_COLUMNS)
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
                    ('team_id', 'manager_function_id', 'hierarchy_type_id', 'parent_team_id')}
                team = normalize_team(Team(row['team_name'], **identifiers, deleted_flag=deleted in {'true', '1'}))
                if team.team_id is not None:
                    if team.team_id in seen:
                        raise ValueError(f'Duplicate team_id {team.team_id}.')
                    seen.add(team.team_id)
                result.append(team)
            except ValueError as error:
                raise ValueError(f'Row {number}: {error}') from error
    except csv.Error as error:
        raise ValueError(f'Invalid CSV near line {reader.line_num}.') from error
    if not result:
        raise ValueError('The CSV contains no team records.')
    return result


def import_teams(store: OrganizationStore, teams: list[Team], *, delete_missing: bool = False) -> TeamImportResult:
    """Upsert a validated final forest without changing function memberships."""
    existing = {team.team_id: team for team in store.get_all_teams(include_deleted=True)}
    source_ids = set(existing) | {team.team_id for team in teams if team.team_id is not None}
    if any(team.parent_team_id is not None and team.parent_team_id not in source_ids for team in teams):
        raise ValueError('A parent_team_id is unknown. Include it in the file or use an existing team ID.')
    aliases: dict[int, int] = {}
    resolved = []
    created = 0
    for team in teams:
        identity = team.team_id
        if identity not in existing:
            identity = store.create_team(replace(team, team_id=None, parent_team_id=None))
            created += 1
        if team.team_id is not None:
            aliases[team.team_id] = identity
        resolved.append(replace(team, team_id=identity))
    included = {team.team_id for team in resolved}
    omitted = {identity for identity, team in existing.items()
               if delete_missing and identity not in included and not team.deleted_flag}
    final = {identity: replace(team, deleted_flag=True) if identity in omitted else team
             for identity, team in existing.items()}
    for team in resolved:
        final[team.team_id] = replace(team, parent_team_id=aliases.get(team.parent_team_id, team.parent_team_id))
    active = [team for team in final.values() if not team.deleted_flag]
    for team in final.values():
        validate_team_parent(team, list(final.values()))
        if not team.deleted_flag:
            validate_team_parent(team, active)
    for identity, team in final.items():
        if team != existing.get(identity):
            store.write_imported_team(team)
    return TeamImportResult(created, len(teams) - created, len(omitted))
