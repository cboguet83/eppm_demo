"""Native project templates and typed defaults with complete callback replay."""

from collections.abc import Callable, Collection

import psycopg

from app.application.exceptions import ProjectTypeConflictError, ProjectTypeStorageError
from app.application.ports.project_types import ProjectTypeStore
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission
from app.domain.projects.project_types import ProjectType, PropertyApplicability, PropertyDefinition, PropertyValue
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.property_store import parameters, read_values, write_value
from app.shared.logging import get_logger

logger = get_logger(__name__)


class PostgresProjectTypeStore:
    """Execute explicit template SQL on the caller-owned authorized connection."""

    def __init__(self, connection: psycopg.Connection) -> None:
        """Retain the current transaction without committing or switching roles."""
        self.connection = connection

    def list_types(self) -> list[ProjectType]:
        """Return General first, followed by the existing binary name order."""
        return [ProjectType(*row) for row in self.connection.execute(
            'SELECT id,name,description,is_general FROM eppm.project_type ORDER BY is_general DESC,name COLLATE "C"')]

    def find_type(self, type_id: int) -> ProjectType | None:
        """Find one template without exposing a driver row."""
        row = self.connection.execute('SELECT id,name,description,is_general FROM eppm.project_type WHERE id=%s', (type_id,)).fetchone()
        return ProjectType(*row) if row else None

    def insert_type(self, name: str, description: str) -> int:
        """Insert normalized details and return the generated identity."""
        return self.connection.execute('INSERT INTO eppm.project_type(name,description) VALUES (%s,%s) RETURNING id', (name, description)).fetchone()[0]

    def update_type(self, type_id: int, name: str, description: str) -> None:
        """Persist details within the transaction containing rename validation."""
        self.connection.execute('UPDATE eppm.project_type SET name=%s,description=%s WHERE id=%s', (name, description, type_id))

    def delete_type(self, type_id: int) -> None:
        """Delete after application guards; native constraints still apply."""
        self.connection.execute('DELETE FROM eppm.project_type WHERE id=%s', (type_id,))

    def has_projects(self, type_id: int) -> bool:
        """Check visible project references before template deletion."""
        return self.connection.execute('SELECT EXISTS(SELECT 1 FROM eppm.project WHERE project_type_id=%s)', (type_id,)).fetchone()[0]

    def has_exclusive_properties(self, type_id: int) -> bool:
        """Detect selected-only properties that deletion would orphan."""
        return self.connection.execute(
            'SELECT EXISTS(SELECT 1 FROM eppm.project_type_property m JOIN eppm.schema_parameters p USING(param_id) '
            'WHERE m.project_type_id=%s AND NOT p.applies_to_all AND NOT EXISTS('
            'SELECT 1 FROM eppm.project_type_property other WHERE other.param_id=m.param_id AND other.project_type_id<>%s))',
            (type_id, type_id),
        ).fetchone()[0]

    def property_definitions(self) -> list[PropertyDefinition]:
        """Return the explicit typed schema projection for template resolution."""
        return parameters(self.connection)

    def selected_properties(self, type_id: int) -> set[str]:
        """Read properties explicitly assigned to this type."""
        return {row[0] for row in self.connection.execute('SELECT param_id FROM eppm.project_type_property WHERE project_type_id=%s', (type_id,))}

    def required_overrides(self, type_id: int) -> dict[str, bool | int | None]:
        """Read nullable native booleans without integer coercion."""
        return dict(self.connection.execute('SELECT param_id,mandatory_override FROM eppm.project_type_property_rule WHERE project_type_id=%s', (type_id,)))

    def defaults(self, type_id: int) -> dict[str, PropertyValue]:
        """Read exact numeric defaults and preserve explicit empty values."""
        return read_values(self.connection, defaults=True, owner_id=type_id).get(type_id, {})

    def get_applicability(self, param_id: str) -> PropertyApplicability | None:
        """Read the scope flag and its ordered membership in one snapshot."""
        row = self.connection.execute('SELECT applies_to_all FROM eppm.schema_parameters WHERE param_id=%s', (param_id,)).fetchone()
        if row is None:
            return None
        type_ids = tuple(item[0] for item in self.connection.execute(
            'SELECT project_type_id FROM eppm.project_type_property WHERE param_id=%s ORDER BY project_type_id', (param_id,)))
        return PropertyApplicability(row[0], type_ids)

    def set_applicability(self, param_id: str, scope: PropertyApplicability) -> None:
        """Lock the definition and replace flag/membership atomically."""
        updated = self.connection.execute('UPDATE eppm.schema_parameters SET applies_to_all=%s WHERE param_id=%s', (scope.applies_to_all, param_id))
        if not updated.rowcount:
            raise ValueError('Unknown property')
        self.connection.execute('DELETE FROM eppm.project_type_property WHERE param_id=%s', (param_id,))
        with self.connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.project_type_property(project_type_id,param_id) VALUES (%s,%s)',
                               [(type_id, param_id) for type_id in scope.type_ids])

    def save_rule(self, type_id: int, param_id: str, mandatory_override: bool | None,
                  *, has_default: bool, default_value: PropertyValue) -> None:
        """Save the rule and typed default, with native mandatory audit on both."""
        self.connection.execute('INSERT INTO eppm.project_type_property_rule(project_type_id,param_id,mandatory_override) VALUES (%s,%s,%s) '
                                'ON CONFLICT(project_type_id,param_id) DO UPDATE SET mandatory_override=excluded.mandatory_override',
                                (type_id, param_id, mandatory_override))
        if has_default:
            write_value(self.connection, type_id, param_id, default_value, defaults=True)
        else:
            self.connection.execute('DELETE FROM eppm.project_type_property_default WHERE project_type_id=%s AND param_id=%s', (type_id, param_id))


class PostgresProjectTypeGateway:
    """Bind the actor and replay whole project-template operations after rollback."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the shared runtime pool, server key and explicit access context."""
        self.database, self.key, self.access = database, key, access

    def run[Result](self, operation: Callable[[ProjectTypeStore], Result], *, write: bool = False,
                    permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Translate safe application failures only after transaction rollback/replay."""
        try:
            return run_business(self.database, self.key, self.access,
                                lambda connection: operation(PostgresProjectTypeStore(connection)), write=write,
                                permission=permission, project_ids=project_ids)
        except psycopg.IntegrityError as error:
            message = ('A project type with this name already exists' if error.diag.constraint_name == 'project_type_name'
                       else 'The change conflicts with an existing reference or property constraint')
            raise ProjectTypeConflictError(message) from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Project-type storage operation failed (%s)', type(error).__name__)
            raise ProjectTypeStorageError('Project-type data could not be accessed. Please try again.') from None
