"""Native tag catalogs, assignments and scoped, consistent task-tag pages."""

from collections.abc import Callable, Collection, Sequence
from typing import cast

import psycopg
from psycopg.rows import class_row, dict_row

from app.application.exceptions import TagConflictError, TagStorageError
from app.application.ports.tag_records import (
    DictionaryRow, EntityChoice, PoolTagRow, ProjectTagRow, TagGroupRow,
    TagLink, TaskChoice, TaskTagPage, TaskTagRow,
)
from app.application.ports.tags import TagStore
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission
from app.domain.tags.models import ProjectTag, ResourcePoolTag, TagDictionary, TagGroup, TaskTag
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger
from app.infrastructure.postgresql.plan_guards import require_current_edit

logger = get_logger(__name__)

_TASK_JOINS = (
    'FROM eppm.task_tag tt LEFT JOIN eppm.project_task ptk ON tt.task_id=ptk.id '
    'LEFT JOIN eppm.project p ON ptk.project_id=p.id '
    'LEFT JOIN eppm.tag_dictionnary td ON tt.tag_id=td.id '
    'LEFT JOIN eppm.tag_group tg ON td.tag_group_id=tg.id '
)
_TASK_COLUMNS = (
    'SELECT tt.id,tt.task_id,ptk.task_name,ptk.project_id,p.name AS project_name,'
    'tt.tag_id,td.tag AS tag_name,tg.tag_group_name,tt.free_tag '
)


class PostgresTagStore:
    """Execute tag operations on the caller-owned, actor-bound connection."""

    def __init__(self, connection: psycopg.Connection) -> None:
        """Retain the transaction without committing, closing or switching roles."""
        self.connection = connection

    def _rows[Row](self, model: type[Row], query: str, params: Sequence[object] = ()) -> list[Row]:
        """Decode the explicit query projection into its declared record type."""
        with self.connection.cursor(row_factory=class_row(model)) as cursor:
            return cursor.execute(query, params).fetchall()

    def _one[Row](self, model: type[Row], query: str, params: Sequence[object]) -> Row | None:
        """Decode one record selected by a unique identity."""
        with self.connection.cursor(row_factory=class_row(model)) as cursor:
            return cursor.execute(query, params).fetchone()

    def get_all_tag_groups(self) -> list[TagGroupRow]:
        """Fetch groups and dictionary counts in one aggregate query."""
        return self._rows(TagGroupRow,
            'SELECT tg.id,tg.tag_group_name,count(td.id) AS tag_count FROM eppm.tag_group tg '
            'LEFT JOIN eppm.tag_dictionnary td ON td.tag_group_id=tg.id '
            'GROUP BY tg.id ORDER BY tg.tag_group_name COLLATE "C",tg.id')

    def get_tag_group_by_id(self, group_id: int) -> TagGroup | None:
        """Find the group without loading its dictionary."""
        return self._one(TagGroup, 'SELECT id,tag_group_name FROM eppm.tag_group WHERE id=%s', (group_id,))

    def create_tag_group(self, group: TagGroup) -> int:
        """Insert normalized group details and return their identity."""
        return self.connection.execute('INSERT INTO eppm.tag_group(tag_group_name) VALUES (%s) RETURNING id', (group.tag_group_name,)).fetchone()[0]

    def update_tag_group(self, group: TagGroup) -> bool:
        """Update one group within the complete application operation."""
        return self.connection.execute('UPDATE eppm.tag_group SET tag_group_name=%s WHERE id=%s', (group.tag_group_name, group.id)).rowcount > 0

    def delete_tag_group(self, group_id: int) -> bool:
        """Delete after service reference checks; native foreign keys remain active."""
        return self.connection.execute('DELETE FROM eppm.tag_group WHERE id=%s', (group_id,)).rowcount > 0

    def count_tags_by_group(self, group_id: int) -> int:
        """Count the dictionary references used by the group deletion guard."""
        return self.connection.execute('SELECT count(*) FROM eppm.tag_dictionnary WHERE tag_group_id=%s', (group_id,)).fetchone()[0]

    def get_all_tags(self) -> list[DictionaryRow]:
        """Aggregate scoped project, task and pool usage before joining labels."""
        return self._rows(DictionaryRow,
            'WITH usages AS (SELECT tag_id FROM eppm.project_tag UNION ALL SELECT tag_id FROM eppm.task_tag '
            'UNION ALL SELECT tag_id FROM eppm.resource_pool_tag), counts AS '
            '(SELECT tag_id,count(*) AS usage_count FROM usages GROUP BY tag_id) '
            'SELECT td.id,td.tag,td.tag_group_id,tg.tag_group_name,COALESCE(c.usage_count,0) AS usage_count '
            'FROM eppm.tag_dictionnary td LEFT JOIN eppm.tag_group tg ON td.tag_group_id=tg.id '
            'LEFT JOIN counts c ON c.tag_id=td.id ORDER BY td.tag COLLATE "C",td.id')

    def get_tags_by_group_name(self, group_name: str) -> list[DictionaryRow]:
        """Match the existing ASCII, underscore/space-insensitive selector names."""
        normalized = group_name.strip().lower().replace('_', '').replace(' ', '')
        return self._rows(DictionaryRow,
            'SELECT td.id,td.tag,td.tag_group_id,tg.tag_group_name FROM eppm.tag_dictionnary td '
            'JOIN eppm.tag_group tg ON tg.id=td.tag_group_id '
            'WHERE lower(replace(replace(tg.tag_group_name,\'_\',\'\'),\' \',\'\') COLLATE "C") IN (%s,%s) '
            'ORDER BY td.tag COLLATE "C",td.id', (normalized, normalized + 's'))

    def get_project_tag_group_tags(self) -> list[DictionaryRow]:
        """Return dictionary selector choices in the project-tag group."""
        return self.get_tags_by_group_name('project_tag')

    def get_task_tag_group_tags(self) -> list[DictionaryRow]:
        """Return dictionary selector choices in the task-tag group."""
        return self.get_tags_by_group_name('Task_Tag')

    def get_tag_group_for_tag(self, tag_id: int) -> TagGroup | None:
        """Read the optional group for one dictionary entry."""
        return self._one(TagGroup, 'SELECT tg.id,tg.tag_group_name FROM eppm.tag_group tg '
                         'JOIN eppm.tag_dictionnary td ON td.tag_group_id=tg.id WHERE td.id=%s', (tag_id,))

    def get_tag_by_id(self, tag_id: int) -> TagDictionary | None:
        """Read only dictionary fields for the requested identity."""
        return self._one(TagDictionary, 'SELECT id,tag,tag_group_id FROM eppm.tag_dictionnary WHERE id=%s', (tag_id,))

    def create_tag(self, tag_item: TagDictionary) -> int:
        """Insert a normalized dictionary label with its optional group."""
        return self.connection.execute('INSERT INTO eppm.tag_dictionnary(tag,tag_group_id) VALUES (%s,%s) RETURNING id',
                                       (tag_item.tag, tag_item.tag_group_id)).fetchone()[0]

    def update_tag(self, tag_item: TagDictionary) -> bool:
        """Update dictionary fields without changing assignment identities."""
        return self.connection.execute('UPDATE eppm.tag_dictionnary SET tag=%s,tag_group_id=%s WHERE id=%s',
                                       (tag_item.tag, tag_item.tag_group_id, tag_item.id)).rowcount > 0

    def delete_tag(self, tag_id: int) -> bool:
        """Remove assignments and the dictionary entry as one guarded change."""
        for table in ('project_tag', 'task_tag', 'resource_pool_tag'):
            self.connection.execute(f'DELETE FROM eppm.{table} WHERE tag_id=%s', (tag_id,))
        return self.connection.execute('DELETE FROM eppm.tag_dictionnary WHERE id=%s', (tag_id,)).rowcount > 0

    def count_tag_usages(self, tag_id: int) -> int:
        """Count only policy-visible assignments, including pool memberships."""
        return self.connection.execute(
            'SELECT (SELECT count(*) FROM eppm.project_tag WHERE tag_id=%s) + '
            '(SELECT count(*) FROM eppm.task_tag WHERE tag_id=%s) + '
            '(SELECT count(*) FROM eppm.resource_pool_tag WHERE tag_id=%s)', (tag_id,) * 3).fetchone()[0]

    def get_all_resource_pool_tags(self) -> list[PoolTagRow]:
        """Return pool assignments with pool, dictionary and group labels."""
        return self._rows(PoolTagRow, 'SELECT rpt.id,rpt.pool_id,rpt.tag_id,rp.name AS pool_name,td.tag AS tag_name,tg.tag_group_name '
            'FROM eppm.resource_pool_tag rpt JOIN eppm.resource_pool rp ON rp.id=rpt.pool_id '
            'JOIN eppm.tag_dictionnary td ON td.id=rpt.tag_id LEFT JOIN eppm.tag_group tg ON tg.id=td.tag_group_id '
            'ORDER BY rp.name COLLATE "C",td.tag COLLATE "C",rpt.id')

    def get_resource_pool_tags(self, pool_id: int) -> list[PoolTagRow]:
        """Return a pool's assignment labels with the existing compact projection."""
        return self._rows(PoolTagRow, 'SELECT rpt.id,rpt.pool_id,rpt.tag_id,td.tag AS tag_name,tg.tag_group_name '
            'FROM eppm.resource_pool_tag rpt JOIN eppm.tag_dictionnary td ON td.id=rpt.tag_id '
            'LEFT JOIN eppm.tag_group tg ON tg.id=td.tag_group_id WHERE rpt.pool_id=%s ORDER BY td.tag COLLATE "C",rpt.id', (pool_id,))

    def create_resource_pool_tag(self, pool_tag: ResourcePoolTag) -> int:
        """Return one stable assignment identity, including concurrent duplicates."""
        return self.connection.execute('INSERT INTO eppm.resource_pool_tag(pool_id,tag_id) VALUES (%s,%s) '
            'ON CONFLICT(pool_id,tag_id) DO UPDATE SET tag_id=excluded.tag_id RETURNING id', (pool_tag.pool_id, pool_tag.tag_id)).fetchone()[0]

    def delete_resource_pool_tag(self, pool_tag_id: int) -> bool:
        """Remove one pool assignment under shared-management authorization."""
        return self.connection.execute('DELETE FROM eppm.resource_pool_tag WHERE id=%s', (pool_tag_id,)).rowcount > 0

    def get_all_project_tags(self) -> list[ProjectTagRow]:
        """Return policy-visible project assignments with display labels."""
        return self._rows(ProjectTagRow,
            'SELECT pt.id,pt.project_id,pt.tag_id,pt.free_tag,p.name AS project_name,td.tag AS tag_name,tg.tag_group_name '
            'FROM eppm.project_tag pt LEFT JOIN eppm.project p ON p.id=pt.project_id '
            'LEFT JOIN eppm.tag_dictionnary td ON td.id=pt.tag_id LEFT JOIN eppm.tag_group tg ON tg.id=td.tag_group_id ORDER BY pt.id DESC')

    def get_project_tags_by_project(self, project_id: int) -> list[ProjectTagRow]:
        """Return compact labels for one visible project in assignment order."""
        return self._rows(ProjectTagRow,
            'SELECT pt.id,pt.project_id,pt.tag_id,pt.free_tag,td.tag AS tag_name,tg.tag_group_name FROM eppm.project_tag pt '
            'LEFT JOIN eppm.tag_dictionnary td ON td.id=pt.tag_id LEFT JOIN eppm.tag_group tg ON tg.id=td.tag_group_id '
            'WHERE pt.project_id=%s ORDER BY pt.id', (project_id,))

    def get_project_tag_by_id(self, pt_id: int) -> ProjectTag | None:
        """Find one visible assignment for the editor."""
        return self._one(ProjectTag, 'SELECT id,project_id,tag_id,free_tag FROM eppm.project_tag WHERE id=%s', (pt_id,))

    def create_project_tag(self, pt: ProjectTag) -> int:
        """Insert combined or free-form content under the project's edit guard."""
        return self.connection.execute('INSERT INTO eppm.project_tag(project_id,tag_id,free_tag) VALUES (%s,%s,%s) RETURNING id',
                                       (pt.project_id, pt.tag_id, pt.free_tag)).fetchone()[0]

    def update_project_tag(self, pt: ProjectTag) -> bool:
        """Update content; native guards check both previous and requested owners."""
        return self.connection.execute('UPDATE eppm.project_tag SET project_id=%s,tag_id=%s,free_tag=%s WHERE id=%s',
                                       (pt.project_id, pt.tag_id, pt.free_tag, pt.id)).rowcount > 0

    def delete_project_tag(self, pt_id: int) -> bool:
        """Delete a visible assignment only with its owner's edit permission."""
        return self.connection.execute('DELETE FROM eppm.project_tag WHERE id=%s', (pt_id,)).rowcount > 0

    def get_task_tags_page(self, *, page: int = 1, page_size: int = 100, search: str = '',
                          filters: dict[str, object] | None = None, sort: str = 'id', ascending: bool = False) -> TaskTagPage:
        """Apply RLS before counts, literal substring filters, sorting and paging."""
        columns = {'id': 'tt.id', 'task_name': 'ptk.task_name', 'project_name': 'p.name',
                   'tag_name': 'td.tag', 'tag_group_name': 'tg.tag_group_name', 'free_tag': 'tt.free_tag'}
        conditions, params = [], []
        def contains(column: str) -> str:
            return f'strpos(lower(COALESCE({column}::text,\'\') COLLATE "C"),lower(%s COLLATE "C"))>0'
        if search.strip():
            conditions.append('(' + ' OR '.join(contains(column) for column in columns.values()) + ')')
            params.extend([search.strip()] * len(columns))
        for key, value in (filters or {}).items():
            if key in columns and str(value or '').strip():
                conditions.append(contains(columns[key]))
                params.append(str(value).strip())
        where = 'WHERE ' + ' AND '.join(conditions) + ' ' if conditions else ''
        column = columns.get(sort, 'tt.id')
        order = column if column == 'tt.id' else f'lower({column} COLLATE "C") COLLATE "C"'
        direction, nulls = ('ASC', 'FIRST') if ascending else ('DESC', 'LAST')
        total = self.connection.execute('SELECT count(*) FROM eppm.task_tag').fetchone()[0]
        filtered = self.connection.execute('SELECT count(*) ' + _TASK_JOINS + where, params).fetchone()[0] if conditions else total
        page_size = max(1, min(200, int(page_size)))
        pages = max(1, (filtered + page_size - 1) // page_size)
        page = max(1, min(pages, int(page)))
        rows = self._rows(TaskTagRow, _TASK_COLUMNS + _TASK_JOINS + where +
            f'ORDER BY {order} {direction} NULLS {nulls},tt.id {direction} LIMIT %s OFFSET %s', params + [page_size, (page - 1) * page_size])
        return TaskTagPage(rows, total, filtered, page, pages, page_size)

    def get_all_task_tags(self) -> list[TaskTagRow]:
        """Read only visible task assignments and their project/catalog labels."""
        return self._rows(TaskTagRow, _TASK_COLUMNS + _TASK_JOINS + 'ORDER BY tt.id DESC')

    def get_task_tags_by_task(self, task_id: int) -> list[TaskTagRow]:
        """Read one task's compact assignment labels without other task fields."""
        return self._rows(TaskTagRow,
            'SELECT tt.id,tt.task_id,tt.tag_id,tt.free_tag,td.tag AS tag_name,tg.tag_group_name FROM eppm.task_tag tt '
            'LEFT JOIN eppm.tag_dictionnary td ON td.id=tt.tag_id LEFT JOIN eppm.tag_group tg ON tg.id=td.tag_group_id '
            'WHERE tt.task_id=%s ORDER BY tt.id', (task_id,))

    def get_task_tag_by_id(self, tt_id: int) -> TaskTag | None:
        """Find one visible task assignment by identity."""
        return self._one(TaskTag, 'SELECT id,task_id,tag_id,free_tag FROM eppm.task_tag WHERE id=%s', (tt_id,))

    def create_task_tag(self, tt: TaskTag) -> int:
        """Insert content with authoritative edit checks on the task's owner."""
        require_current_edit(self.connection, task_id=tt.task_id)
        return self.connection.execute('INSERT INTO eppm.task_tag(task_id,tag_id,free_tag) VALUES (%s,%s,%s) RETURNING id',
                                       (tt.task_id, tt.tag_id, tt.free_tag)).fetchone()[0]

    def update_task_tag(self, tt: TaskTag) -> bool:
        """Validate old and new task owners through permanent mutation guards."""
        require_current_edit(self.connection, task_id=tt.task_id)
        previous = self.get_task_tag_by_id(tt.id)
        if previous:
            require_current_edit(self.connection, task_id=previous.task_id)
        return self.connection.execute('UPDATE eppm.task_tag SET task_id=%s,tag_id=%s,free_tag=%s WHERE id=%s',
                                       (tt.task_id, tt.tag_id, tt.free_tag, tt.id)).rowcount > 0

    def delete_task_tag(self, tt_id: int) -> bool:
        """Delete a visible assignment under its current owner's edit guard."""
        previous = self.get_task_tag_by_id(tt_id)
        if previous:
            require_current_edit(self.connection, task_id=previous.task_id)
        return self.connection.execute('DELETE FROM eppm.task_tag WHERE id=%s', (tt_id,)).rowcount > 0

    def _links(self, ids: list[int], *, tasks: bool) -> dict[int, list[TagLink]]:
        """Batch explicit link rows; only internal constants select SQL identifiers."""
        if not ids:
            return {}
        table, owner = ('task_tag', 'task_id') if tasks else ('project_tag', 'project_id')
        result: dict[int, list[TagLink]] = {identity: [] for identity in ids}
        with self.connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                f'SELECT assignment.id,assignment.{owner},assignment.tag_id,td.tag AS tag_name,tg.tag_group_name,assignment.free_tag '
                f'FROM eppm.{table} assignment LEFT JOIN eppm.tag_dictionnary td ON td.id=assignment.tag_id '
                f'LEFT JOIN eppm.tag_group tg ON tg.id=td.tag_group_id WHERE assignment.{owner}=ANY(%s::bigint[]) ORDER BY assignment.id', (ids,))
            for row in rows:
                result[row[owner]].append(cast(TagLink, row))
        return result

    def get_task_tags_by_task_ids(self, task_ids: list[int]) -> dict[int, list[TagLink]]:
        """Keep input keys and fetch visible task links in one array-bound query."""
        return self._links([int(identity) for identity in task_ids if identity is not None], tasks=True)

    def get_project_tags_by_project_ids(self, project_ids: list[int]) -> dict[int, list[TagLink]]:
        """Keep input keys and fetch visible project links in one array-bound query."""
        return self._links([int(identity) for identity in project_ids], tasks=False)

    def project_choices(self) -> list[EntityChoice]:
        """Read policy-visible project IDs and labels only."""
        return self._rows(EntityChoice, 'SELECT id,name FROM eppm.project ORDER BY id')

    def search_task_choices(self, search: str = '', *, limit: int = 50) -> list[TaskChoice]:
        """Bound selector results and support exact #ID and literal text searches."""
        search = search.strip()
        if search.lstrip('#').isdigit():
            where, params = 'WHERE t.id=%s ', [int(search.lstrip('#'))]
        elif search:
            where = ('WHERE strpos(lower(t.task_name COLLATE "C"),lower(%s COLLATE "C"))>0 '
                     'OR strpos(lower(p.name COLLATE "C"),lower(%s COLLATE "C"))>0 ')
            params = [search, search]
        else:
            where, params = '', []
        return self._rows(TaskChoice, 'SELECT t.id,t.task_name,t.project_id,p.name AS project_name FROM eppm.project_task t '
            'JOIN eppm.project p ON p.id=t.project_id ' + where + 'ORDER BY t.id DESC LIMIT %s', params + [max(1, min(100, int(limit)))])

    def get_task_choice(self, task_id: int) -> TaskChoice | None:
        """Find a selected task even when outside the selector's first page."""
        rows = self.search_task_choices(f'#{task_id}')
        return rows[0] if rows else None


class PostgresTagGateway:
    """Run whole tag operations with authoritative scope checks on each attempt."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the process pool, trusted server key and explicit actor policy."""
        self.database, self.key, self.access = database, key, access

    def run[Result](self, operation: Callable[[TagStore], Result], *, write: bool = False,
                    permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Translate storage failures only after complete rollback and replay."""
        try:
            return run_business(self.database, self.key, self.access,
                                lambda connection: operation(PostgresTagStore(connection)), write=write,
                                permission=permission, project_ids=project_ids)
        except psycopg.IntegrityError:
            raise TagConflictError('The tag change conflicts with an existing reference or constraint.') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Tag storage operation failed (%s)', type(error).__name__)
            raise TagStorageError('Tag data could not be accessed. Please try again.') from None
