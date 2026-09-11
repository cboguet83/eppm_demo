"""Batched dashboard reads with explicit project scope and aggregate-only shared demand."""

from collections import Counter
from contextlib import closing, contextmanager
from collections.abc import Iterator
from datetime import date
import json
from pathlib import Path
import sqlite3

from app.application.exceptions import ProjectStorageError
from app.application.ports.dashboard import DashboardCatalog, DashboardData
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor, AccessDenied, ProjectScope
from app.domain.dashboard import WbsShare, ancestor, quarterly_shortfall, quarterly_capacity, quarter_bounds, responsible_pools
from app.domain.resources.models import PoolCapacityDetail
from app.domain.resources.capacity import calculate_capacity
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.display_revision import read_display_revision
from app.infrastructure.repositories.access import SqliteAccessStore
from app.infrastructure.repositories.finance import SqliteFinanceStore
from app.infrastructure.repositories.pool_capacity import read_capacity_inputs
from app.infrastructure.repositories.resource_pools import SqliteResourcePoolStore


_LATEST = """SELECT id FROM finance_snapshot s WHERE sealed=1 AND status=?
    AND NOT EXISTS(SELECT 1 FROM finance_cancellation c WHERE c.snapshot_id=s.id)
    ORDER BY number DESC LIMIT 1"""
_BLOCKERS = """FROM project_log_event e JOIN project p ON p.id=e.project_id
    JOIN project_event_type t ON t.id=e.event_type_id
    WHERE t.system_code='blocking_point' AND e.status='active'
    AND e.project_id IN (SELECT value FROM json_each(?))"""


class SqliteDashboardReader:
    """Apply current project scope before every projection or aggregate."""

    def __init__(self, db_path: str, access: BusinessAccess) -> None:
        self.db_path, self.access = str(Path(db_path).resolve()), access

    @contextmanager
    def _read(self, requested: list[int] | None = None) -> Iterator[tuple[sqlite3.Connection, list[int]]]:
        try:
            with closing(get_db(self.db_path)) as connection, connection:
                connection.row_factory = sqlite3.Row
                connection.execute('BEGIN')
                store = SqliteAccessStore(connection)
                if isinstance(self.access.actor, Actor):
                    self.access.policy.session(store, self.access.actor)
                    allowed = self.access.policy.projects(store, self.access.actor)
                else:
                    allowed = store.scope_projects(ProjectScope('all'))
                if requested is not None and (any(type(value) is not int for value in requested) or not set(requested) <= allowed):
                    raise AccessDenied()
                yield connection, sorted(allowed if requested is None else set(requested))
        except sqlite3.Error as error:
            raise ProjectStorageError('Dashboard data is unavailable. Please try again.') from error

    def revision(self) -> tuple:
        """Check the session and read compact data and Finance status revisions."""
        with self._read() as (connection, _):
            plans = tuple(connection.execute(_LATEST, (status,)).fetchone() for status in ('Approved', 'Proposed', 'Draft'))
            actor = self.access.actor
            identity = (actor.user_id, actor.session_hash) if isinstance(actor, Actor) else ('deployment',)
            return self.db_path, *read_display_revision(connection), identity, tuple(row[0] if row else None for row in plans)

    def catalog(self) -> DashboardCatalog:
        """Read minimal project/filter attributes and organization references in batches."""
        with self._read() as (connection, ids):
            if not ids:
                return DashboardCatalog([], {}, [])
            functions = {row['function_id']: dict(row) for row in connection.execute('SELECT * FROM function')}
            names = {key: value['name'] for key, value in functions.items()}
            occupied = set()
            for row in connection.execute('SELECT function_id,firstname,lastname FROM employee ORDER BY lastname,firstname,employee_id'):
                name = f"{row['firstname']} {row['lastname']}".strip()
                if row['function_id'] in names and row['function_id'] not in occupied and name:
                    names[row['function_id']] = name
                    occupied.add(row['function_id'])
            counts = Counter(names.values())
            labels = {str(key): name + (f' ({functions[key]["name"]}, #{key})' if counts[name] > 1 else '') for key, name in names.items()}
            labels[''] = ''  # Presentation translates Unassigned.
            team_names = {str(row[0]): row[1] for row in connection.execute('SELECT team_id,team_name FROM team')}
            teams: dict[int, list[str]] = {}
            for team, function in connection.execute('SELECT team_id,function_id FROM team_function'):
                teams.setdefault(function, []).append(str(team))
            projects = {}
            for row in connection.execute("""SELECT p.id,p.name,p.status,p.function_id,t.name AS template
                    FROM project p LEFT JOIN project_type t ON t.id=p.project_type_id
                    WHERE p.id IN (SELECT value FROM json_each(?))
                    AND lower(trim(COALESCE(p.status,''))) NOT IN ('completed','cancelled','canceled')
                    ORDER BY p.id""", (json.dumps(ids),)):
                fid = row['function_id']
                l3, l4 = ancestor(fid, 3, functions), ancestor(fid, 4, functions)
                fields = {'name': [row['name']], 'project_template': [row['template'] or ''], 'status': [row['status'] or ''],
                          'manager': [str(fid) if fid in functions else ''], 'level3': [str(l3) if l3 else ''],
                          'level4': [str(l4) if l4 else ''], 'team': teams.get(fid, ['']),
                          'project_manager': [names.get(fid, '')], 'level_3_manager_name': [names.get(l3, '')]}
                projects[row['id']] = {'id': row['id'], 'name': row['name'], 'fields': fields}
            ids = list(projects)
            pool_names = {}
            for pid, pool_id, name in connection.execute('''SELECT DISTINCT a.project_id,p.id,p.name
                    FROM resource_pool_assignment a JOIN resource_pool p ON p.id=a.pool_id
                    WHERE a.fte_assigned>0 AND a.project_id IN (SELECT value FROM json_each(?))''', (json.dumps(ids),)):
                pool_names[str(pool_id)] = name
                projects[pid]['fields'].setdefault('pool', []).append(str(pool_id))
            for project in projects.values():
                project['fields'].setdefault('pool', [''])
            self._properties(connection, projects, ids)
            for pid, tag in connection.execute("""SELECT pt.project_id,t.tag FROM project_tag pt
                    JOIN tag_dictionnary t ON t.id=pt.tag_id WHERE pt.project_id IN (SELECT value FROM json_each(?))""", (json.dumps(ids),)):
                projects[pid]['fields'].setdefault('_project_tags', []).append(tag)
            parameters = [dict(row) for row in connection.execute('SELECT * FROM schema_parameters ORDER BY param_id')]
            aliases: dict[str, dict[str, str]] = {}
            for pid, locale, alias in connection.execute('SELECT param_id,locale,alias FROM schema_parameter_translation'):
                aliases.setdefault(pid, {})[locale] = alias
            for parameter in parameters:
                parameter['translations'] = aliases.get(parameter['param_id'], {})
            result = list(projects.values())
            safe_labels = {}
            for key in ('manager', 'level3', 'level4', 'team', 'pool'):
                visible = {value for project in result for value in project['fields'].get(key, [])}
                source = pool_names if key == 'pool' else team_names if key == 'team' else labels
                safe_labels[key] = {value: source.get(value, '') for value in visible}
            return DashboardCatalog(result, safe_labels, parameters)

    @staticmethod
    def _properties(connection: sqlite3.Connection, projects: dict, ids: list[int]) -> None:
        items: dict[tuple[int, str], list[str]] = {}
        for row in connection.execute("""SELECT project_id,param_id,value FROM project_property_value_item
                WHERE project_id IN (SELECT value FROM json_each(?)) ORDER BY position""", (json.dumps(ids),)):
            items.setdefault((row[0], row[1]), []).append(str(row[2]))
        for row in connection.execute("""SELECT v.* FROM project_property_value v
                JOIN project p ON p.id=v.project_id JOIN schema_parameters s ON s.param_id=v.param_id
                WHERE p.id IN (SELECT value FROM json_each(?)) AND (s.applies_to_all=1 OR EXISTS
                (SELECT 1 FROM project_type_property m WHERE m.project_type_id=p.project_type_id AND m.param_id=v.param_id))""", (json.dumps(ids),)):
            value = row['number_value'] if row['kind'] == 'number' else row['date_value'] if row['kind'] == 'date' else row['text_value']
            projects[row['project_id']]['fields'][row['param_id']] = items.get((row['project_id'], row['param_id']), []) if row['kind'] == 'list' else [str(value)] if value is not None else []

    def data(self, project_ids: list[int], status: str = 'Approved') -> DashboardData:
        """Read the requested Finance status, authorized WBS shares, and issue count."""
        if status not in {'Approved', 'Proposed', 'Draft'}:
            raise ValueError('Select Approved, Proposed, or Draft.')
        with self._read(project_ids) as (connection, ids):
            shares = [WbsShare(*row) for row in connection.execute("""SELECT pw.project_id,w.code,pw.percentage
                FROM project_wbs pw JOIN wbs w ON w.id=pw.wbs_id
                WHERE pw.project_id IN (SELECT value FROM json_each(?)) ORDER BY pw.project_id,w.code""", (json.dumps(ids),))]
            approved_id = connection.execute(_LATEST, (status,)).fetchone() if ids else None
            approved = SqliteFinanceStore(connection, self.access, writable=False).snapshot(approved_id[0]) if approved_id else None
            count = connection.execute('SELECT count(*) ' + _BLOCKERS, (json.dumps(ids),)).fetchone()[0]
            return DashboardData(shares, approved, count)

    def shortages(self, project_ids: list[int], today: date) -> dict[str, float]:
        """Allow global competing demand only inside this authorized aggregate boundary."""
        return self.resources(project_ids, today)['overallocation']

    @staticmethod
    def _details(connection: sqlite3.Connection, ids: list[int], today: date) -> list[PoolCapacityDetail]:
        pools = [row[0] for row in connection.execute('''SELECT DISTINCT pool_id FROM resource_pool_assignment
            WHERE fte_assigned>0 AND project_id IN (SELECT value FROM json_each(?))''', (json.dumps(ids),))]
        if not pools:
            return []
        inputs = read_capacity_inputs(SqliteResourcePoolStore(connection), pools)
        return [calculate_capacity(value, today) for value in inputs.values()]

    def resources(self, project_ids: list[int], today: date) -> dict[str, dict[str, float]]:
        """Return only aggregated capacity and shortfall, without competing identities."""
        with self._read(project_ids) as (connection, ids):
            details = self._details(connection, ids, today)
            return {'overallocation': quarterly_shortfall(details, set(ids), today.year),
                    'capacity': quarterly_capacity(details, today.year)}

    def consuming_projects(self, project_ids: list[int], quarter: str, today: date) -> list[int]:
        """Resolve currently authorized consumers of the responsible pools in a quarter."""
        start, end = quarter_bounds(quarter, today.year)
        with self._read(project_ids) as (connection, ids):
            details = self._details(connection, ids, today)
            responsible = responsible_pools(details, set(ids), start, end)
            store = SqliteAccessStore(connection)
            allowed = (self.access.policy.projects(store, self.access.actor) if isinstance(self.access.actor, Actor)
                       else store.scope_projects(ProjectScope('all')))
            return sorted({row['project_id'] for pool in details if pool.pool_id in responsible
                           for row in pool.assignments if row['project_id'] in allowed and row['fte_assigned'] > 0
                           and row['start_date'] <= end.isoformat() and row['end_date'] >= start.isoformat()})

    def issues(self, project_ids: list[int], locale: str) -> list[dict]:
        """Return only matching project blockers, translated without changing identities."""
        with self._read(project_ids) as (connection, ids):
            rows = connection.execute("""SELECT e.*,p.name AS project_name,
                COALESCE((SELECT label FROM project_event_type_translation WHERE catalog_id=t.id AND locale=?),t.name) AS event_type """
                + _BLOCKERS + ' ORDER BY e.project_id,e.id DESC', (locale, json.dumps(ids)))
            return [dict(row) for row in rows]
