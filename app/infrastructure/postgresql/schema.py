"""Native schema catalogs, translations and atomic administration callbacks."""

from collections.abc import Callable, Collection

import psycopg

from app.application.exceptions import SchemaConflictError, SchemaStorageError
from app.application.ports.schema import SchemaStore
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission
from app.domain.projects.project_types import PropertyApplicability
from app.domain.projects.schema import SchemaGroup, SchemaParameter, SchemaParamOption
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.project_types import PostgresProjectTypeStore
from app.shared.logging import get_logger

logger = get_logger(__name__)


class PostgresSchemaStore:
    """Execute explicit catalog SQL in the caller's authorized transaction."""

    def __init__(self, connection: psycopg.Connection) -> None:
        """Retain the existing transaction without committing or switching roles."""
        self.connection = connection

    def groups(self) -> list[SchemaGroup]:
        """Return groups in their established display order."""
        return [SchemaGroup(*row) for row in self.connection.execute(
            'SELECT group_name,display_order,id FROM eppm.schema_groups ORDER BY display_order,id')]

    def parameters(self) -> list[SchemaParameter]:
        """Read an explicit catalog projection with native boolean flags."""
        return [SchemaParameter(*row) for row in self.connection.execute(
            'SELECT param_id,param_name,param_type,group_id,COALESCE(mandatory,false),alias,applies_to_all '
            'FROM eppm.schema_parameters ORDER BY param_id COLLATE "C"')]

    def options(self) -> list[SchemaParamOption]:
        """Return ordered choices, retaining historical duplicate choices."""
        return [SchemaParamOption(*row) for row in self.connection.execute(
            'SELECT param_id,option_value,display_order,id FROM eppm.schema_param_options ORDER BY display_order,id')]

    def alias_translations(self, locale: str) -> dict[str, str]:
        """Fetch every explicit property label for one locale in a single query."""
        return dict(self.connection.execute(
            'SELECT param_id,alias FROM eppm.schema_parameter_translation WHERE locale=%s', (locale,)))

    def set_alias_translation(self, param_id: str, locale: str, alias: str) -> None:
        """Upsert a label or remove a blank translation without changing its ID."""
        if not alias:
            self.connection.execute('DELETE FROM eppm.schema_parameter_translation WHERE param_id=%s AND locale=%s',
                                    (param_id, locale))
            return
        self.connection.execute(
            'INSERT INTO eppm.schema_parameter_translation(param_id,locale,alias) VALUES (%s,%s,%s) '
            'ON CONFLICT(param_id,locale) DO UPDATE SET alias=excluded.alias', (param_id, locale, alias))

    def parameter_identifiers(self) -> list[str]:
        """Read stable identifiers for an automatic ID or its nonbinding preview."""
        return [row[0] for row in self.connection.execute('SELECT param_id FROM eppm.schema_parameters')]

    def find_parameter(self, param_id: str) -> SchemaParameter | None:
        """Read the definition used to validate a compound edit."""
        row = self.connection.execute(
            'SELECT param_id,param_name,param_type,group_id,COALESCE(mandatory,false),alias,applies_to_all '
            'FROM eppm.schema_parameters WHERE param_id=%s', (param_id,)).fetchone()
        return SchemaParameter(*row) if row else None

    def find_option(self, option_id: int) -> SchemaParamOption | None:
        """Read the exact choice lifetime used by reference and deletion checks."""
        row = self.connection.execute(
            'SELECT param_id,option_value,display_order,id FROM eppm.schema_param_options WHERE id=%s', (option_id,)).fetchone()
        return SchemaParamOption(*row) if row else None

    def has_property_values(self, param_id: str) -> bool:
        """Include explicitly cleared project values and template defaults."""
        return self.connection.execute(
            'SELECT EXISTS(SELECT 1 FROM eppm.project_property_value WHERE param_id=%s) '
            'OR EXISTS(SELECT 1 FROM eppm.project_type_property_default WHERE param_id=%s)', (param_id, param_id)).fetchone()[0]

    def is_option_referenced(self, option: SchemaParamOption) -> bool:
        """Check scalar and list selections in both projects and template defaults."""
        return self.connection.execute(
            'SELECT EXISTS(SELECT 1 FROM eppm.project_property_value WHERE param_id=%s AND text_value=%s '
            'UNION ALL SELECT 1 FROM eppm.project_property_value_item WHERE param_id=%s AND value=%s '
            'UNION ALL SELECT 1 FROM eppm.project_type_property_default WHERE param_id=%s AND text_value=%s '
            'UNION ALL SELECT 1 FROM eppm.project_type_property_default_item WHERE param_id=%s AND value=%s)',
            (option.param_id, option.option_value) * 4).fetchone()[0]

    def insert_group(self, group_name: str, display_order: int) -> int:
        """Insert normalized details, leaving uniqueness to native constraints."""
        return self.connection.execute(
            'INSERT INTO eppm.schema_groups(group_name,display_order) VALUES (%s,%s) RETURNING id',
            (group_name, display_order)).fetchone()[0]

    def update_group(self, group_id: int, group_name: str, display_order: int) -> bool:
        """Persist the group details within the complete use case."""
        return self.connection.execute('UPDATE eppm.schema_groups SET group_name=%s,display_order=%s WHERE id=%s',
                                       (group_name, display_order, group_id)).rowcount > 0

    def ungroup_parameters(self, group_id: int) -> None:
        """Detach properties while preserving their definitions and stored values."""
        self.connection.execute('UPDATE eppm.schema_parameters SET group_id=NULL WHERE group_id=%s', (group_id,))

    def delete_group(self, group_id: int) -> bool:
        """Delete the group after detaching its properties in this transaction."""
        return self.connection.execute('DELETE FROM eppm.schema_groups WHERE id=%s', (group_id,)).rowcount > 0

    def insert_parameter(self, parameter: SchemaParameter) -> None:
        """Insert details before assigning applicability on the same connection."""
        self.connection.execute(
            'INSERT INTO eppm.schema_parameters(param_id,group_id,param_name,param_type,mandatory,alias) VALUES (%s,%s,%s,%s,%s,%s)',
            (parameter.param_id, parameter.group_id, parameter.param_name, parameter.param_type, parameter.mandatory, parameter.alias))

    def update_parameter(self, parameter: SchemaParameter) -> bool:
        """Update details without implicitly changing selected type membership."""
        return self.connection.execute(
            'UPDATE eppm.schema_parameters SET group_id=%s,param_name=%s,param_type=%s,mandatory=%s,alias=%s WHERE param_id=%s',
            (parameter.group_id, parameter.param_name, parameter.param_type, parameter.mandatory, parameter.alias, parameter.param_id)).rowcount > 0

    def set_applicability(self, param_id: str, scope: PropertyApplicability) -> None:
        """Use native template membership operations in the same transaction."""
        PostgresProjectTypeStore(self.connection).set_applicability(param_id, scope)

    def delete_parameter(self, param_id: str) -> bool:
        """Remove choices and the guarded definition atomically."""
        self.connection.execute('DELETE FROM eppm.schema_param_options WHERE param_id=%s', (param_id,))
        return self.connection.execute('DELETE FROM eppm.schema_parameters WHERE param_id=%s', (param_id,)).rowcount > 0

    def insert_option(self, param_id: str, option_value: str, display_order: int) -> int:
        """Insert a new choice lifetime without committing the outer edit."""
        return self.connection.execute(
            'INSERT INTO eppm.schema_param_options(param_id,option_value,display_order) VALUES (%s,%s,%s) RETURNING id',
            (param_id, option_value, display_order)).fetchone()[0]

    def delete_option(self, option_id: int) -> bool:
        """Delete the checked choice; native triggers invalidate categorical grants."""
        return self.connection.execute('DELETE FROM eppm.schema_param_options WHERE id=%s', (option_id,)).rowcount > 0


class PostgresSchemaGateway:
    """Bind actual actors and replay complete schema administration operations."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the process pool, trusted server key and explicit actor policy."""
        self.database, self.key, self.access = database, key, access

    def run[Result](self, operation: Callable[[SchemaStore], Result], *, write: bool = False,
                    permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Translate safe application failures only after rollback and replay."""
        try:
            return run_business(self.database, self.key, self.access,
                                lambda connection: operation(PostgresSchemaStore(connection)), write=write,
                                permission=permission, project_ids=project_ids)
        except psycopg.IntegrityError as error:
            messages = {
                'schema_groups_group_name_key': 'A group with this name already exists.',
                'schema_groups_display_order_key': 'This group display order is already in use.',
                'schema_parameters_pkey': 'A property with this ID already exists.',
            }
            raise SchemaConflictError(messages.get(error.diag.constraint_name,
                'The schema change conflicts with an existing reference or constraint.')) from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Schema storage operation failed (%s)', type(error).__name__)
            raise SchemaStorageError('Schema data could not be accessed. Please try again.') from None
