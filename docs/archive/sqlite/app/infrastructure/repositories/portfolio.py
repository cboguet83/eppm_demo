"""Bounded portfolio reads: rows, global filters, and on-demand column statistics.

The storage model retains the legacy project_type names. The public grid calls
them project templates. No portfolio query loads all project property records.
"""

from app.application.services.business_access import BusinessAccess
from app.application.exceptions import ProjectStorageError
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from typing import Any

from app.shared.config import config
from app.infrastructure.database.project_transactions import project_connection
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.display_revision import read_display_revision
from app.infrastructure.repositories.access import SqliteAccessStore
from app.domain.access.models import Actor
from app.infrastructure.database.property_store import parameters
from app.infrastructure.repositories.budgets import read_budget_totals
from app.domain.projects.budgets import euro_amount, monetary_statistics
from app.application.ports.portfolio import (
    PortfolioMetrics, PortfolioColumn, PortfolioPage, PortfolioFacet, PortfolioRow,
    ProjectCatalog, PropertyGroup, PropertyOption,
)
from typing import cast


def portfolio_revision(db_path: str | None, *, access: BusinessAccess | None = None) -> tuple:
    """Track display inputs without invalidating on session activity or cache writes.

    Protected callers recheck the current session and scope in the same snapshot
    as the business/security revision. This metadata read needs no temporary
    business views or write triggers; actual business queries retain those guards.
    """
    path = Path(db_path or config.db_path).resolve()
    try:
        with closing(get_db(str(path))) as connection, connection:
            connection.execute("BEGIN")
            scope = ()
            if access is not None:
                projects = access.projects(SqliteAccessStore(connection))
                actor = access.actor
                identity = (actor.user_id, actor.session_hash) if isinstance(actor, Actor) else ("deployment",)
                scope = (identity, tuple(sorted(projects)))
            return (str(path), *read_display_revision(connection), *scope)
    except sqlite3.DatabaseError as exc:
        raise ProjectStorageError("Project display data could not be accessed. Please try again.") from exc


class SqlitePortfolioReader:
    """SQLite read model preserving bounded pages and global facets."""
    PAGE_SIZE = 100
    FACET_SIZE = 200

    def __init__(self, db_path: str | None = None, *, access: BusinessAccess) -> None:
        """Retain the database path without opening a connection."""
        self.db_path = db_path
        self.access = access

    def get_metrics(self) -> PortfolioMetrics:
        """Read decimal totals with constant-memory streaming of amount columns."""
        return read_budget_totals(self.db_path, access=self.access)

    @staticmethod
    def _source(columns: list[PortfolioColumn]) -> tuple[str, list, set[str]]:
        expressions = {
            'project_id': 'p.id', 'name': 'p.name', 'project_template': 't.name',
            'status': 'p.status', 'planned_budget': 'p.planned_budget',
            'actual_budget': 'p.actual_budget',
            'project_manager': "COALESCE((SELECT NULLIF(TRIM(COALESCE(e.firstname,'') || ' ' || COALESCE(e.lastname,'')), '') "
                "FROM employee e WHERE e.function_id=p.function_id AND TRIM(COALESCE(e.firstname,'') || COALESCE(e.lastname,''))<>'' "
                "ORDER BY e.lastname, e.firstname, e.employee_id LIMIT 1), f.name, '')",
            'level_3_manager_name': "COALESCE((SELECT name FROM lineage WHERE origin=p.function_id "
                "AND hierarchy_level=3 ORDER BY depth LIMIT 1), '')",
        }
        args: list[Any] = []
        for col in columns:
            # Only server-supplied schema metadata may add SQL expressions.
            if col['key'] in expressions or not col.get('param_id'):
                continue
            expressions[col['key']] = """(SELECT CASE v.kind
                WHEN 'number' THEN v.number_value WHEN 'date' THEN v.date_value
                WHEN 'text' THEN v.text_value WHEN 'list' THEN
                    (SELECT GROUP_CONCAT(value, ', ') FROM
                        (SELECT value FROM project_property_value_item i
                         WHERE i.project_id=p.id AND i.param_id=v.param_id ORDER BY position))
                ELSE NULL END
                FROM project_property_value v JOIN schema_parameters s USING(param_id)
                WHERE v.project_id=p.id AND v.param_id=? AND (s.applies_to_all=1 OR EXISTS
                    (SELECT 1 FROM project_type_property m WHERE m.project_type_id=p.project_type_id
                     AND m.param_id=v.param_id)))"""
            args.append(col['param_id'])
        projection = ', '.join(expr + ' AS "' + key.replace('"', '""') + '"'
                               for key, expr in expressions.items())
        sql = """WITH RECURSIVE lineage(origin,function_id,name,hierarchy_level,manager_function_id,depth,path) AS (
            SELECT function_id,function_id,name,hierarchy_level,manager_function_id,0,','||function_id||',' FROM function
            UNION ALL
            SELECT l.origin,f.function_id,f.name,f.hierarchy_level,f.manager_function_id,l.depth+1,l.path||f.function_id||','
            FROM lineage l JOIN function f ON f.function_id=l.manager_function_id
            WHERE l.hierarchy_level>3 AND l.depth<20 AND INSTR(l.path,','||f.function_id||',')=0
        ), portfolio AS (SELECT """ + projection + " FROM project p JOIN project_type t ON t.id=p.project_type_id " \
            + "LEFT JOIN function f ON f.function_id=p.function_id) "
        return sql, args, set(expressions)

    @staticmethod
    def _where(query: dict, keys: set[str], *, exclude: str | None = None) -> tuple[str, list]:
        clauses, args = [], []
        search = str(query.get('search') or '').strip()
        if search:
            clauses.append('(INSTR(LOWER(name), LOWER(?))>0 OR INSTR(CAST(project_id AS TEXT),?)>0)')
            args.extend([search, search])
        templates = query.get('templates') or []
        if templates:
            clauses.append('project_template IN (SELECT value FROM json_each(?))')
            args.append(json.dumps(templates))
        for key, rule in (query.get('filters') or {}).items():
            if key not in keys or key == exclude or not isinstance(rule, dict):
                continue
            values = rule.get('values', [])
            if not isinstance(values, list):
                continue
            operator = 'NOT IN' if rule.get('mode') == 'exclude' else 'IN'
            column = '"' + key.replace('"', '""') + '"'
            clauses.append(f"COALESCE({column},'') {operator} (SELECT value FROM json_each(?))")
            args.append(json.dumps([v for v in values if isinstance(v, (str, int, float))]))
        return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), args

    def get_page(self, columns: list[PortfolioColumn], query: dict, offset: int = 0) -> PortfolioPage:
        """Return at most 100 rows from one consistent filtered snapshot."""
        sql, args, keys = self._source(columns)
        where, where_args = self._where(query, keys)
        sort = query.get('sort') or {}
        key = sort.get('column') if sort.get('column') in keys else 'project_id'
        direction = 'DESC' if sort.get('direction') == 'desc' else 'ASC'
        order = '"' + key.replace('"', '""') + '" COLLATE NOCASE ' + direction + ', project_id ASC'
        with project_connection(self.db_path, access=self.access) as conn:
            total = conn.execute(sql + 'SELECT COUNT(*) FROM portfolio' + where, args + where_args).fetchone()[0]
            offset = min(max(0, int(offset)), max(0, (total - 1) // self.PAGE_SIZE * self.PAGE_SIZE))
            cursor = conn.execute(sql + 'SELECT * FROM portfolio' + where + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
                                  args + where_args + [self.PAGE_SIZE, offset])
            names = [c[0] for c in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor]
        return {'rows': rows, 'total': total, 'offset': offset, 'page_size': self.PAGE_SIZE}

    def get_facet(self, columns: list[PortfolioColumn], query: dict, column: str, search: str = '') -> PortfolioFacet:
        """Full-result statistics; at most 200 distinct choices, searchable on demand.

        Ignore this column's own selection, as Excel does, but respect every
        other filter. Include/exclude selections work beyond the returned choices.
        """
        sql, args, keys = self._source(columns)
        if column not in keys:
            raise ValueError('Unknown portfolio column')
        where, where_args = self._where(query, keys, exclude=column)
        value = 'COALESCE("' + column.replace('"', '""') + '",\'\')'
        sql += ', facet AS (SELECT ' + value + ' AS value FROM portfolio' + where + ') '
        args += where_args
        with project_connection(self.db_path, access=self.access) as conn:
            count, filled, unique = conn.execute(sql + "SELECT COUNT(*), COUNT(NULLIF(value,'')), COUNT(DISTINCT NULLIF(value,'')) FROM facet", args).fetchone()
            stats: list = [['Rows', count], ['Filled', filled], ['Unique', unique], ['Empty', count - filled]]
            fmt = next((c.get('format') for c in columns if c['key'] == column), 'text')
            if filled and fmt == 'currency':
                amounts = conn.execute(sql + "SELECT value FROM facet WHERE value<>''", args)
                monetary = monetary_statistics(euro_amount(row[0]) for row in amounts)
                assert monetary is not None
                low, avg, high = (float(amount) for amount in monetary)
                stats.extend([['Minimum', low], ['Average', avg], ['Maximum', high]])
            elif filled and fmt == 'number':
                low, avg, high = conn.execute(sql + "SELECT MIN(value), AVG(value), MAX(value) FROM facet WHERE value<>''", args).fetchone()
                stats.extend([['Minimum', low], ['Average', avg], ['Maximum', high]])
            elif filled:
                top, n = conn.execute(sql + "SELECT value, COUNT(*) n FROM facet WHERE value<>'' GROUP BY value ORDER BY n DESC, value LIMIT 1", args).fetchone()
                stats.append(['Most common', f'{top} ({n})'])
            choices = conn.execute(sql + 'SELECT value, COUNT(*) FROM facet WHERE INSTR(LOWER(CAST(value AS TEXT)),LOWER(?))>0 '
                                   'GROUP BY value ORDER BY value COLLATE NOCASE LIMIT ?', args + [search, self.FACET_SIZE + 1]).fetchall()
        return {'column': column, 'search': search, 'stats': stats, 'format': fmt,
                'values': [{'value': v, 'count': n} for v, n in choices[:self.FACET_SIZE]],
                'has_more': len(choices) > self.FACET_SIZE}

    def revision(self) -> tuple:
        """Reauthorize before cache lookup and isolate revisions by trusted actor/scope."""
        return portfolio_revision(self.db_path, access=self.access)

    def get_detail(self, project_id: int) -> PortfolioRow | None:
        """Read one project summary using the same manager labels as the grid."""
        sql, args, _ = self._source([])
        with project_connection(self.db_path, access=self.access) as conn:
            cursor = conn.execute(sql + 'SELECT * FROM portfolio WHERE project_id=?', args + [project_id])
            row = cursor.fetchone()
            return dict(zip([c[0] for c in cursor.description], row)) if row else None

    def get_catalog(self, *, include_managers: bool = True) -> ProjectCatalog:
        """Read schema; load occupant labels only when rendering a project editor."""
        with project_connection(self.db_path, access=self.access) as conn:
            def records(sql: str) -> list[dict]:
                cursor = conn.execute(sql)
                names = [column[0] for column in cursor.description]
                return [dict(zip(names, row)) for row in cursor]

            groups = records('SELECT * FROM schema_groups ORDER BY display_order,id')
            options = records('SELECT * FROM schema_param_options ORDER BY display_order,id')
            managers = dict(conn.execute("""SELECT f.function_id,
                COALESCE((SELECT NULLIF(TRIM(TRIM(COALESCE(e.firstname,'')) || ' ' || TRIM(COALESCE(e.lastname,''))), '')
                    FROM employee e WHERE e.function_id=f.function_id
                    AND TRIM(COALESCE(e.firstname,'') || COALESCE(e.lastname,''))<>''
                    ORDER BY e.lastname,e.firstname,e.employee_id LIMIT 1), NULLIF(f.name,''), '—')
                FROM function f ORDER BY f.hierarchy_level,f.name""")) if include_managers else {}
            return ProjectCatalog(cast(list[PropertyGroup], groups), parameters(conn),
                                  cast(list[PropertyOption], options), managers)
