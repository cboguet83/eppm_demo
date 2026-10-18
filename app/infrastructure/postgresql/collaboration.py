"""Native project contacts, localized catalogs, events and useful links."""

from collections.abc import Callable, Collection, Sequence
from datetime import date

import psycopg
from psycopg.rows import dict_row

from app.application.exceptions import CollaborationConflictError, CollaborationStorageError
from app.application.ports.collaboration import (
    CatalogEntry, CollaborationStore, FunctionChoice, FunctionContact,
    ProjectContact, ProjectEvent, ProjectLink,
)
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission
from app.domain.projects.collaboration import CatalogKind, EventValues, validate_catalog
from app.domain.projects.links import LinkValues
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.dictionaries import PostgresDictionaryStore
from app.domain.dictionaries import DictionaryCode, dictionary_edit
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger

logger = get_logger(__name__)


def _catalog_code(kind: CatalogKind) -> DictionaryCode:
    """Map the established collaboration kinds to shared dictionary codes."""
    return {'role': 'project_role', 'event_type': 'project_event_type'}[validate_catalog(kind)]


class PostgresCollaborationStore:
    """Execute explicit collaboration SQL in the caller's authorized snapshot."""

    def __init__(self, connection: psycopg.Connection) -> None:
        """Retain the transaction without committing, closing or changing roles."""
        self.connection = connection

    def _rows[Row](self, model: type[Row], query: str, parameters: Sequence[object] = ()) -> list[Row]:
        """Decode an explicit projection at the dynamic driver-row boundary."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return [model(**row) for row in cursor.execute(query, parameters)]

    def list_links(self, project_id: int) -> list[ProjectLink]:
        """Read only the visible project's links in creation order."""
        return self._rows(ProjectLink, 'SELECT id,url,alias FROM eppm.project_link WHERE project_id=%s ORDER BY id', (project_id,))

    def save_link(self, project_id: int, values: LinkValues, link_id: int | None) -> int:
        """Insert or update a validated link without changing its project owner."""
        if link_id is None:
            return self.connection.execute('INSERT INTO eppm.project_link(project_id,url,alias) VALUES (%s,%s,%s) RETURNING id',
                                           (project_id, values['url'], values['alias'])).fetchone()[0]
        changed = self.connection.execute('UPDATE eppm.project_link SET url=%s,alias=%s WHERE project_id=%s AND id=%s',
                                          (values['url'], values['alias'], project_id, link_id))
        if not changed.rowcount:
            raise ValueError('The link no longer exists in this project.')
        return link_id

    def delete_link(self, project_id: int, link_id: int) -> None:
        """Retain project-qualified, no-op deletion for absent links."""
        self.connection.execute('DELETE FROM eppm.project_link WHERE project_id=%s AND id=%s', (project_id, link_id))

    def list_catalog(self, kind: CatalogKind, locale: str) -> list[CatalogEntry]:
        """Return translated labels with canonical fallback and stable ordering."""
        return PostgresDictionaryStore(self.connection).list_entries(_catalog_code(kind), locale)

    def save_catalog(self, kind: CatalogKind, name: str, item_id: int | None) -> int:
        """Save canonical name and English translation through shared storage."""
        return PostgresDictionaryStore(self.connection).save_entry(_catalog_code(kind), dictionary_edit(name), item_id)

    def delete_catalog(self, kind: CatalogKind, item_id: int) -> None:
        """Delete one unused catalog entry with native reference protection."""
        PostgresDictionaryStore(self.connection).delete_entry(_catalog_code(kind), item_id)

    def function_choices(self) -> list[FunctionChoice]:
        """Use the minimal name directory without fetching employee contact fields."""
        return self._rows(FunctionChoice, '''WITH occupants AS (
            SELECT function_id,string_agg(trim(firstname || ' ' || lastname), ', '
                ORDER BY lastname COLLATE "C" NULLS FIRST,firstname COLLATE "C" NULLS FIRST) AS person
            FROM eppm.employee_name_directory GROUP BY function_id
        ) SELECT f.function_id,f.name AS function_name,COALESCE(o.person,f.name) AS person
          FROM eppm.active_function f LEFT JOIN occupants o ON o.function_id=f.function_id
          ORDER BY lower(COALESCE(o.person,f.name) COLLATE "C") COLLATE "C",f.function_id''')

    def list_functions(self) -> list[FunctionContact]:
        """Resolve employee phones only through shared-management row policies."""
        return self._rows(FunctionContact, '''WITH occupants AS (
            SELECT ef.function_id,
                string_agg(trim(firstname || ' ' || lastname), ', '
                    ORDER BY lastname COLLATE "C" NULLS FIRST,firstname COLLATE "C" NULLS FIRST,e.employee_id) AS person,
                string_agg(NULLIF(mobile,''), ', '
                    ORDER BY lastname COLLATE "C" NULLS FIRST,firstname COLLATE "C" NULLS FIRST,e.employee_id) AS mobile,
                string_agg(NULLIF(landline,''), ', '
                    ORDER BY lastname COLLATE "C" NULLS FIRST,firstname COLLATE "C" NULLS FIRST,e.employee_id) AS landline
            FROM eppm.active_employee e JOIN eppm.active_employee_function ef ON ef.employee_id=e.employee_id
            GROUP BY ef.function_id
        ) SELECT f.function_id,f.name AS function_name,COALESCE(o.person,f.name) AS person,
                 COALESCE(o.mobile,'') AS mobile,COALESCE(o.landline,'') AS landline
          FROM eppm.active_function f LEFT JOIN occupants o ON o.function_id=f.function_id
          ORDER BY lower(COALESCE(o.person,f.name) COLLATE "C") COLLATE "C",f.function_id''')

    def list_contacts(self, project_id: int, locale: str) -> list[ProjectContact]:
        """Resolve only an authorized project's assigned functions and phones."""
        return self._rows(ProjectContact,
            'SELECT c.id,c.role_id,c.function_id,c.function_name,c.person,c.mobile,c.landline,COALESCE(t.label,r.name) AS role '
            "FROM eppm.project_contacts(%s) c JOIN eppm.business_dictionary_entry r ON r.id=c.role_id AND r.dictionary_code='project_role' "
            'LEFT JOIN eppm.business_dictionary_translation t ON t.dictionary_code=r.dictionary_code AND t.entry_id=r.id AND t.locale=%s '
            'ORDER BY COALESCE(t.label,r.name) COLLATE "C",c.id', (project_id, locale))

    def save_contact(self, project_id: int, role_id: int, function_id: int, contact_id: int | None) -> int:
        """Save the role/function assignment within its existing project owner."""
        if contact_id is None:
            return self.connection.execute('INSERT INTO eppm.project_contact(project_id,role_id,function_id) VALUES (%s,%s,%s) RETURNING id',
                                           (project_id, role_id, function_id)).fetchone()[0]
        changed = self.connection.execute('UPDATE eppm.project_contact SET role_id=%s,function_id=%s WHERE id=%s AND project_id=%s',
                                          (role_id, function_id, contact_id, project_id))
        if not changed.rowcount:
            raise ValueError('The contact no longer exists in this project.')
        return contact_id

    def delete_contact(self, project_id: int, contact_id: int) -> None:
        """Delete only the matching project's contact assignment."""
        self.connection.execute('DELETE FROM eppm.project_contact WHERE id=%s AND project_id=%s', (contact_id, project_id))

    def reassign_contact(self, project_id: int, contact_id: int, function_id: int) -> None:
        """Change only the function, preserving the contact's role and ownership."""
        changed = self.connection.execute('UPDATE eppm.project_contact SET function_id=%s WHERE project_id=%s AND id=%s',
                                          (function_id, project_id, contact_id))
        if not changed.rowcount:
            raise ValueError('The contact no longer exists in this project.')

    def list_events(self, project_id: int, locale: str, *, offset: int, limit: int) -> list[ProjectEvent]:
        """Read one scoped log page with ISO dates and existing UTC timestamp text."""
        return self._rows(ProjectEvent, '''SELECT e.id,e.project_id,e.title,e.description,
            to_char(e.deadline,'YYYY-MM-DD') AS deadline,e.scope,e.comment,e.event_type_id,e.status,
            to_char(e.created_at AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') AS created_at,
            to_char(e.updated_at AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') AS updated_at,
            COALESCE(t.label,c.name) AS event_type FROM eppm.project_log_event e
            JOIN eppm.business_dictionary_entry c ON c.id=e.event_type_id AND c.dictionary_code='project_event_type'
            LEFT JOIN eppm.business_dictionary_translation t ON t.dictionary_code=c.dictionary_code AND t.entry_id=c.id AND t.locale=%s
            WHERE e.project_id=%s ORDER BY e.id DESC LIMIT %s OFFSET %s''', (locale, project_id, limit, offset))

    def save_event(self, project_id: int, values: EventValues, event_id: int | None) -> int:
        """Persist validated fields with native dates and project-qualified updates."""
        parameters = (values['title'], values['description'], date.fromisoformat(values['deadline']) if values['deadline'] else None,
                      values['scope'], values['comment'], values['event_type_id'], values['status'])
        if event_id is None:
            return self.connection.execute('INSERT INTO eppm.project_log_event(title,description,deadline,scope,comment,event_type_id,status,project_id) '
                                           'VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id', (*parameters, project_id)).fetchone()[0]
        changed = self.connection.execute('UPDATE eppm.project_log_event SET title=%s,description=%s,deadline=%s,scope=%s,comment=%s,'
                                          'event_type_id=%s,status=%s,updated_at=current_timestamp WHERE id=%s AND project_id=%s',
                                          (*parameters, event_id, project_id))
        if not changed.rowcount:
            raise ValueError('The event no longer exists in this project.')
        return event_id


class PostgresCollaborationGateway:
    """Bind actors and replay complete collaboration use cases after rollback."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the runtime pool, trusted signing key and explicit actor policy."""
        self.database, self.key, self.access = database, key, access

    def run[Result](self, operation: Callable[[CollaborationStore], Result], *, write: bool = False,
                    permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Translate safe failures after complete transaction rollback and replay."""
        try:
            return run_business(self.database, self.key, self.access,
                                lambda connection: operation(PostgresCollaborationStore(connection)), write=write,
                                permission=permission, project_ids=project_ids)
        except psycopg.IntegrityError:
            raise CollaborationConflictError('Cannot save: this entry is duplicated, missing, or still in use.') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Collaboration storage operation failed (%s)', type(error).__name__)
            raise CollaborationStorageError('Collaboration data could not be accessed. Please try again.') from None
