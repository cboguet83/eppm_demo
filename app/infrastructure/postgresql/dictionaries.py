"""Dictionary-qualified catalog SQL on existing authorized transactions."""

from collections.abc import Callable

import psycopg
from psycopg.rows import dict_row

from app.application.exceptions import DictionaryConflictError, DictionaryStorageError
from app.application.ports.dictionaries import DictionaryEntry, DictionaryStore
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission
from app.domain.dictionaries import DictionaryCode, DictionaryEdit, dictionary_code
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger

logger = get_logger(__name__)
_MISSING = 'The dictionary entry no longer exists.'


class PostgresDictionaryStore:
    """Execute catalog commands without owning their connection or commit."""

    def __init__(self, connection: psycopg.Connection) -> None:
        """Inject the caller's authorized transaction connection."""
        self.connection = connection

    def list_entries(self, code: DictionaryCode, locale: str) -> list[DictionaryEntry]:
        """Resolve translated labels in one query with canonical fallback."""
        selected = dictionary_code(code)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute('''SELECT e.id,e.name,COALESCE(t.label,e.name) AS label
                FROM eppm.business_dictionary_entry e
                LEFT JOIN eppm.business_dictionary_translation t
                  ON t.dictionary_code=e.dictionary_code AND t.entry_id=e.id AND t.locale=%s
                WHERE e.dictionary_code=%s
                ORDER BY lower(COALESCE(t.label,e.name) COLLATE "C") COLLATE "C",e.id''',
                (locale, selected))
            return [DictionaryEntry(**row) for row in rows]

    def translations(self, code: DictionaryCode, item_id: int) -> dict[str, str]:
        """Return only explicit translations, failing on a deleted entry."""
        selected = dictionary_code(code)
        if not self.connection.execute('SELECT 1 FROM eppm.business_dictionary_entry WHERE dictionary_code=%s AND id=%s',
                                       (selected,item_id)).fetchone():
            raise ValueError(_MISSING)
        return dict(self.connection.execute('SELECT locale,label FROM eppm.business_dictionary_translation '
                                           'WHERE dictionary_code=%s AND entry_id=%s', (selected,item_id)))

    def save_entry(self, code: DictionaryCode, edit: DictionaryEdit, item_id: int | None) -> int:
        """Write a canonical name and submitted translations in one transaction."""
        selected = dictionary_code(code)
        if item_id is None:
            row = self.connection.execute('INSERT INTO eppm.business_dictionary_entry(dictionary_code,name) '
                                          'VALUES (%s,%s) RETURNING id', (selected,edit.name)).fetchone()
        else:
            row = self.connection.execute('UPDATE eppm.business_dictionary_entry SET name=%s '
                'WHERE dictionary_code=%s AND id=%s RETURNING id', (edit.name,selected,item_id)).fetchone()
        if row is None:
            raise ValueError(_MISSING)
        identity = row[0]
        for locale, label in edit.translations.items():
            self._save_translation(selected, identity, locale, label)
        return identity

    def _save_translation(self, code: DictionaryCode, item_id: int, locale: str, label: str) -> None:
        """Upsert a submitted override or remove its explicitly blank value."""
        if not label:
            self.connection.execute('DELETE FROM eppm.business_dictionary_translation '
                                    'WHERE dictionary_code=%s AND entry_id=%s AND locale=%s', (code,item_id,locale))
            return
        self.connection.execute('''INSERT INTO eppm.business_dictionary_translation(dictionary_code,entry_id,locale,label)
            VALUES (%s,%s,%s,%s) ON CONFLICT(dictionary_code,entry_id,locale)
            DO UPDATE SET label=excluded.label''', (code,item_id,locale,label))

    def delete_entry(self, code: DictionaryCode, item_id: int) -> None:
        """Delete only one dictionary's unused entry; FKs retain used entries."""
        self.connection.execute('DELETE FROM eppm.business_dictionary_entry WHERE dictionary_code=%s AND id=%s',
                                (dictionary_code(code),item_id))


class PostgresDictionaryGateway:
    """Authorize and replay complete dictionary operations with safe errors."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the runtime pool, signing key and trusted actor policy."""
        self.database, self.key, self.access = database, key, access

    def run[Result](
        self, operation: Callable[[DictionaryStore], Result], *, write: bool = False,
        permission: Permission | None = None,
    ) -> Result:
        """Run one authorized transaction, translating only storage failures."""
        try:
            return run_business(self.database,self.key,self.access,
                lambda connection: operation(PostgresDictionaryStore(connection)),
                write=write,permission=permission)
        except psycopg.IntegrityError:
            raise DictionaryConflictError('Cannot save: this entry is duplicated, missing, or still in use.') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Dictionary storage operation failed (%s)', type(error).__name__)
            raise DictionaryStorageError('Dictionary data could not be accessed. Please try again.') from None
