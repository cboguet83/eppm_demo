"""Scoped native portfolio pages, facets, catalogs and exact budget aggregates."""

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
import json
from typing import cast

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import set_json_loads

from app.application.exceptions import ProjectStorageError
from app.application.ports.portfolio import (
    PortfolioColumn, PortfolioFacet, PortfolioMetrics, PortfolioPage, PortfolioRow,
    ProjectCatalog, PropertyGroup, PropertyOption, Scalar,
)
from app.application.services.business_access import BusinessAccess
from app.domain.projects.budgets import BudgetAmounts, decimal_mean, summarize_budgets
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.portfolio_query import DIRECTORY, facet_projection, order, source, where
from app.infrastructure.postgresql.property_store import parameters
from app.infrastructure.postgresql.revisions import read_revisions
from app.shared.logging import get_logger


logger = get_logger(__name__)


class PostgresPortfolioReader:
    """Keep each bounded page or facet in one authorized repeatable-read snapshot."""

    PAGE_SIZE = 100
    FACET_SIZE = 200

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the process pool and current trusted actor without opening I/O."""
        self.database, self.key, self.access = database, key, access

    def _run[Result](self, operation: Callable[[psycopg.Connection], Result]) -> Result:
        try:
            return run_business(self.database, self.key, self.access, operation)
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Portfolio storage operation failed (%s)', type(error).__name__)
            raise ProjectStorageError('Project display data could not be accessed. Please try again.') from None

    def revision(self) -> tuple:
        """Resolve actor, current membership and source revisions in one snapshot."""
        return self._run(lambda connection: read_revisions(connection, self.access).key())

    def get_metrics(self) -> PortfolioMetrics:
        """Aggregate visible native euro amounts without hydrating project records."""
        def operation(connection: psycopg.Connection) -> PortfolioMetrics:
            count, planned, actual = connection.execute('SELECT count(*),coalesce(sum(planned_budget),0),'
                'coalesce(sum(actual_budget),0) FROM eppm.project').fetchone()
            return replace(summarize_budgets([BudgetAmounts(planned, actual)]), total_projects=count)
        return self._run(operation)

    def get_page(self, columns: list[PortfolioColumn], query: dict, offset: int = 0) -> PortfolioPage:
        """Read scoped counts and at most 100 rows in a stable, clamped page."""
        prefix, arguments, formats = source(columns)
        clause, filters = where(query, formats)
        sort = query.get('sort') or {}
        key = sort.get('column') if sort.get('column') in formats else 'project_id'
        ordering = order(sql.SQL('to_jsonb({})').format(sql.Identifier(key)), descending=sort.get('direction') == 'desc')
        def operation(connection: psycopg.Connection) -> PortfolioPage:
            total = connection.execute(prefix + sql.SQL('SELECT count(*) FROM portfolio') + clause, arguments + filters).fetchone()[0]
            position = min(max(0, offset), max(0, (total - 1) // self.PAGE_SIZE * self.PAGE_SIZE))
            with connection.cursor(row_factory=dict_row) as cursor:
                set_json_loads(lambda value: json.loads(value, parse_float=Decimal, parse_int=Decimal), cursor)
                # Select IDs before hydration so OFFSET never evaluates every
                # discarded row's dynamic properties or manager labels.
                rows = cursor.execute(prefix + sql.SQL(', selected AS MATERIALIZED (SELECT project_id,'
                    'row_number() OVER(ORDER BY {},project_id ASC) AS position FROM portfolio').format(ordering) + clause +
                    sql.SQL(' ORDER BY {},project_id ASC LIMIT %s OFFSET %s) '
                            'SELECT portfolio.* FROM portfolio JOIN selected USING(project_id) ORDER BY selected.position').format(ordering),
                    arguments + filters + [self.PAGE_SIZE, position]).fetchall()
            return PortfolioPage(rows=cast(list[PortfolioRow], rows), total=total, offset=position, page_size=self.PAGE_SIZE)
        return self._run(operation)

    def get_facet(self, columns: list[PortfolioColumn], query: dict, column: str, search: str = '') -> PortfolioFacet:
        """Read all-result statistics and 200 choices, excluding this column's filter."""
        prefix, arguments, formats = source(columns)
        if column not in formats:
            raise ValueError('Unknown portfolio column')
        fmt = next((item.get('format', 'text') for item in columns if item['key'] == column), 'text')
        clause, filters = where(query, formats, exclude=column)
        prefix += sql.SQL(', facet AS MATERIALIZED (SELECT coalesce(to_jsonb({}),\'""\'::jsonb) AS value FROM portfolio').format(sql.Identifier(column)) + clause + sql.SQL(') ')
        arguments += filters
        def operation(connection: psycopg.Connection) -> PortfolioFacet:
            with connection.cursor() as cursor:
                set_json_loads(lambda value: json.loads(value, parse_float=Decimal, parse_int=Decimal), cursor)
                row = cursor.execute(prefix + facet_projection(), arguments + [search, self.FACET_SIZE + 1]).fetchone()
                stats, choices = self._statistics(row[:-1], fmt), row[-1]
            return PortfolioFacet(column=column, search=search, stats=stats, format=fmt,
                values=[{'value': value, 'count': int(count)} for value, count in choices[:self.FACET_SIZE]],
                has_more=len(choices) > self.FACET_SIZE)
        return self._run(operation)

    @staticmethod
    def _statistics(row: tuple, fmt: str) -> list[list[Scalar]]:
        """Decode the fixed SQL statistics row; preserve numeric financial results."""
        count, filled, unique, low, total, high, numeric_count, top, frequency = row
        stats: list[list[Scalar]] = [['Rows', count], ['Filled', filled], ['Unique', unique], ['Empty', count - filled]]
        if not filled:
            return stats
        if fmt in ('currency', 'number'):
            if numeric_count:
                stats.extend([['Minimum', low], ['Average', decimal_mean(total, numeric_count)], ['Maximum', high]])
        else:
            stats.append(['Most common', f'{top} ({frequency})'])
        return stats

    def get_detail(self, project_id: int) -> PortfolioRow | None:
        """Read one visible row using the same manager labels as the grid."""
        prefix, arguments, _ = source([])
        def operation(connection: psycopg.Connection) -> PortfolioRow | None:
            with connection.cursor(row_factory=dict_row) as cursor:
                return cast(PortfolioRow | None, cursor.execute(prefix + sql.SQL('SELECT * FROM portfolio WHERE project_id=%s'),
                                                               arguments + [project_id]).fetchone())
        return self._run(operation)

    def get_catalog(self, *, include_managers: bool = True) -> ProjectCatalog:
        """Read reference metadata and optional manager labels without raw employees."""
        def operation(connection: psycopg.Connection) -> ProjectCatalog:
            with connection.cursor(row_factory=dict_row) as cursor:
                groups = cursor.execute('SELECT id,group_name,display_order FROM eppm.schema_groups ORDER BY display_order,id').fetchall()
                options = cursor.execute('SELECT id,param_id,option_value,display_order FROM eppm.schema_param_options ORDER BY display_order,id').fetchall()
            managers = dict(connection.execute(sql.SQL('WITH ') + DIRECTORY + sql.SQL(" SELECT f.function_id,"
                "coalesce(occupants.choice_label,nullif(f.name,''),'—') FROM eppm.function f "
                'LEFT JOIN occupants ON occupants.function_id=f.function_id ORDER BY f.hierarchy_level,f.name COLLATE "C"'))
            ) if include_managers else {}
            return ProjectCatalog(cast(list[PropertyGroup], groups), parameters(connection), cast(list[PropertyOption], options), managers)
        return self._run(operation)
