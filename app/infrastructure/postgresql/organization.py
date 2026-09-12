"""Native organization queries and atomic mutations on an injected transaction."""

from collections.abc import Callable, Collection, Sequence
from datetime import date

import psycopg
from psycopg.rows import class_row

from app.application.exceptions import OrganizationConflictError, OrganizationStorageError
from app.application.ports.organization import CalendarExceptionRow, OrganizationStore
from app.application.ports.references import EmployeeReference, FunctionReference
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission
from app.domain.hierarchy import HierarchyType
from app.domain.organization.models import Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.hierarchy import hierarchy_types
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger

logger = get_logger(__name__)


class PostgresOrganizationStore:
    """Preserve organization DTOs while using native boolean and date values."""

    def __init__(self, connection: psycopg.Connection) -> None:
        """Use one caller-owned connection without committing or changing roles."""
        self.connection = connection

    def _rows[Record](self, model: type[Record], query: str,
                      parameters: Sequence[object] = ()) -> list[Record]:
        with self.connection.cursor(row_factory=class_row(model)) as cursor:
            return cursor.execute(query, parameters).fetchall()

    def _one[Record](self, model: type[Record], query: str,
                     parameters: Sequence[object]) -> Record | None:
        with self.connection.cursor(row_factory=class_row(model)) as cursor:
            return cursor.execute(query, parameters).fetchone()

    def function_references(self) -> list[FunctionReference]:
        """Read reporting ancestry without employee or staffing records."""
        return self._rows(FunctionReference, 'SELECT function_id,name,hierarchy_level,manager_function_id '
                          'FROM eppm.function ORDER BY hierarchy_level,name COLLATE "C"')

    def employee_references(self) -> list[EmployeeReference]:
        """Read the dedicated name-only directory for authorized project labels."""
        return self._rows(EmployeeReference, 'SELECT function_id,firstname,lastname FROM eppm.employee_name_directory '
                          'ORDER BY lastname COLLATE "C",firstname COLLATE "C"')

    def get_all_hierarchy_types(self) -> list[HierarchyType]:
        """Read the shared hierarchy catalog and all translations in one query."""
        return hierarchy_types(self.connection)

    def save_hierarchy_type(self, value: HierarchyType) -> int:
        """Keep the stable code and replace localized labels atomically."""
        type_id = value.id
        if type_id is None:
            type_id = self.connection.execute('INSERT INTO eppm.hierarchy_type(code) VALUES (%s) RETURNING id', (value.code,)).fetchone()[0]
        else:
            current = self.connection.execute('SELECT code FROM eppm.hierarchy_type WHERE id=%s FOR UPDATE', (type_id,)).fetchone()
            if current is None:
                raise ValueError('This hierarchy type no longer exists. Please refresh.')
            if current[0] != value.code:
                raise ValueError('Hierarchy type codes cannot be changed; edit the labels instead.')
        self.connection.execute('DELETE FROM eppm.hierarchy_type_translation WHERE hierarchy_type_id=%s', (type_id,))
        with self.connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.hierarchy_type_translation(hierarchy_type_id,locale,label) VALUES (%s,%s,%s)',
                               [(type_id, locale, label) for locale, label in sorted(value.translations.items())])
        return type_id

    def delete_hierarchy_type(self, type_id: int) -> bool:
        """Delete unused catalog entries; foreign keys protect assigned types."""
        return self.connection.execute('DELETE FROM eppm.hierarchy_type WHERE id=%s', (type_id,)).rowcount > 0

    def get_all_function_types(self) -> list[FunctionType]:
        """Read function types in the existing binary name order."""
        return self._rows(FunctionType, 'SELECT function_type_id,function_type FROM eppm.function_type ORDER BY function_type COLLATE "C"')

    def get_function_type_by_id(self, type_id: int) -> FunctionType | None:
        """Find a function type by its stable reference."""
        return self._one(FunctionType, 'SELECT function_type_id,function_type FROM eppm.function_type WHERE function_type_id=%s', (type_id,))

    def create_function_type(self, ftype: FunctionType) -> int:
        """Insert a normalized function type and return its generated ID."""
        return self.connection.execute('INSERT INTO eppm.function_type(function_type) VALUES (%s) RETURNING function_type_id', (ftype.function_type,)).fetchone()[0]

    def update_function_type(self, ftype: FunctionType) -> bool:
        """Update existing details and preserve the missing-record result."""
        return self.connection.execute('UPDATE eppm.function_type SET function_type=%s WHERE function_type_id=%s',
                                       (ftype.function_type, ftype.function_type_id)).rowcount > 0

    def delete_function_type(self, type_id: int) -> bool:
        """Delete an unused function type in the current transaction."""
        return self.connection.execute('DELETE FROM eppm.function_type WHERE function_type_id=%s', (type_id,)).rowcount > 0

    def get_all_functions(self) -> list[OrgFunction]:
        """Read functions by hierarchy level and binary name order."""
        return self._rows(OrgFunction, 'SELECT function_id,name,hierarchy_level,function_type_id,manager_function_id,'
                          'dual_manager_function_id,fte_percentage,has_reports FROM eppm.function '
                          'ORDER BY hierarchy_level,name COLLATE "C"')

    def get_function_by_id(self, func_id: int) -> OrgFunction | None:
        """Read one function with the established defaults for nullable flags."""
        return self._one(OrgFunction, 'SELECT function_id,name,hierarchy_level,function_type_id,manager_function_id,'
                         'dual_manager_function_id,coalesce(fte_percentage,100) AS fte_percentage,'
                         'coalesce(has_reports,false) AS has_reports FROM eppm.function WHERE function_id=%s', (func_id,))

    def create_function(self, func: OrgFunction) -> int:
        """Persist native booleans and generated function identity."""
        return self.connection.execute('INSERT INTO eppm.function(name,hierarchy_level,function_type_id,manager_function_id,'
                                       'dual_manager_function_id,fte_percentage,has_reports) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING function_id',
                                       (func.name, func.hierarchy_level, func.function_type_id, func.manager_function_id,
                                        func.dual_manager_function_id, func.fte_percentage, func.has_reports)).fetchone()[0]

    def update_function(self, func: OrgFunction) -> bool:
        """Update reporting relationships and native boolean flags together."""
        return self.connection.execute('UPDATE eppm.function SET name=%s,hierarchy_level=%s,function_type_id=%s,manager_function_id=%s,'
                                       'dual_manager_function_id=%s,fte_percentage=%s,has_reports=%s WHERE function_id=%s',
                                       (func.name, func.hierarchy_level, func.function_type_id, func.manager_function_id,
                                        func.dual_manager_function_id, func.fte_percentage, func.has_reports, func.function_id)).rowcount > 0

    def delete_function(self, func_id: int) -> bool:
        """Delete an unreferenced function with native referential protection."""
        return self.connection.execute('DELETE FROM eppm.function WHERE function_id=%s', (func_id,)).rowcount > 0

    def get_all_teams(self) -> list[Team]:
        """Read optional hierarchy assignments in the existing name order."""
        return self._rows(Team, 'SELECT team_id,team_name,manager_function_id,leader_function_id,hierarchy_type_id '
                          'FROM eppm.team ORDER BY team_name COLLATE "C"')

    def get_team_by_id(self, team_id: int) -> Team | None:
        """Find a team without loading or altering its members."""
        return self._one(Team, 'SELECT team_id,team_name,manager_function_id,leader_function_id,hierarchy_type_id '
                         'FROM eppm.team WHERE team_id=%s', (team_id,))

    def create_team(self, team: Team) -> int:
        """Insert team details within the surrounding membership transaction."""
        return self.connection.execute('INSERT INTO eppm.team(team_name,manager_function_id,leader_function_id,hierarchy_type_id) '
                                       'VALUES (%s,%s,%s,%s) RETURNING team_id',
                                       (team.team_name, team.manager_function_id, team.leader_function_id, team.hierarchy_type_id)).fetchone()[0]

    def update_team(self, team: Team) -> bool:
        """Update team details and preserve absent-team behavior."""
        return self.connection.execute('UPDATE eppm.team SET team_name=%s,manager_function_id=%s,leader_function_id=%s,hierarchy_type_id=%s '
                                       'WHERE team_id=%s', (team.team_name, team.manager_function_id,
                                                           team.leader_function_id, team.hierarchy_type_id, team.team_id)).rowcount > 0

    def delete_team(self, team_id: int) -> bool:
        """Delete a team and let native cascades remove its memberships."""
        return self.connection.execute('DELETE FROM eppm.team WHERE team_id=%s', (team_id,)).rowcount > 0

    def get_all_employees(self) -> list[Employee]:
        """Read private employee records through the shared-data policy."""
        return self._rows(Employee, 'SELECT employee_id,firstname,lastname,email,mobile,sigle,employee_code,'
                          'function_id,occupation_percentage,landline FROM eppm.employee ORDER BY lastname COLLATE "C",firstname COLLATE "C"')

    def get_employee_by_id(self, emp_id: int) -> Employee | None:
        """Read one private employee, preserving nullable contact defaults."""
        return self._one(Employee, "SELECT employee_id,firstname,lastname,email,coalesce(mobile,'') AS mobile,coalesce(sigle,'') AS sigle,"
                         'employee_code,function_id,occupation_percentage,landline FROM eppm.employee WHERE employee_id=%s', (emp_id,))

    def create_employee(self, emp: Employee) -> int:
        """Insert an employee within its optional initial-calendar transaction."""
        return self.connection.execute('INSERT INTO eppm.employee(firstname,lastname,email,mobile,sigle,employee_code,function_id,occupation_percentage,landline) '
                                       'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING employee_id',
                                       (emp.firstname, emp.lastname, emp.email, emp.mobile, emp.sigle, emp.employee_code,
                                        emp.function_id, emp.occupation_percentage, emp.landline)).fetchone()[0]

    def update_employee(self, emp: Employee) -> bool:
        """Update the employee record under native uniqueness constraints."""
        return self.connection.execute('UPDATE eppm.employee SET firstname=%s,lastname=%s,email=%s,mobile=%s,sigle=%s,employee_code=%s,'
                                       'function_id=%s,occupation_percentage=%s,landline=%s WHERE employee_id=%s',
                                       (emp.firstname, emp.lastname, emp.email, emp.mobile, emp.sigle, emp.employee_code,
                                        emp.function_id, emp.occupation_percentage, emp.landline, emp.employee_id)).rowcount > 0

    def delete_employee(self, emp_id: int) -> bool:
        """Delete the employee and its cascading calendar exceptions."""
        return self.connection.execute('DELETE FROM eppm.employee WHERE employee_id=%s', (emp_id,)).rowcount > 0

    def get_employee_calendar_exceptions(self, emp_id: int | None = None) -> list[CalendarExceptionRow]:
        """Return native calendar dates as explicit ISO presentation values."""
        return self._rows(CalendarExceptionRow, "SELECT c.exception_id,c.employee_id,e.employee_code,e.firstname,e.lastname,"
                          "to_char(c.start_date,'YYYY-MM-DD') AS start_date,to_char(c.end_date,'YYYY-MM-DD') AS end_date,"
                          'c.occupation_percentage,c.reason FROM eppm.employee_calendar_exception c JOIN eppm.employee e USING(employee_id) '
                          'WHERE (%s::bigint IS NULL OR c.employee_id=%s) ORDER BY c.start_date DESC,c.end_date DESC,c.exception_id DESC', (emp_id, emp_id))

    def get_employee_calendar_exception_by_id(self, exception_id: int) -> EmployeeCalendarException | None:
        """Keep native Python dates in the domain exception model."""
        return self._one(EmployeeCalendarException, "SELECT exception_id,employee_id,start_date,end_date,occupation_percentage,coalesce(reason,'') AS reason "
                         'FROM eppm.employee_calendar_exception WHERE exception_id=%s', (exception_id,))

    def has_overlapping_calendar_exception(self, employee_id: int, start_date: date, end_date: date,
                                           exclude_id: int | None = None) -> bool:
        """Check inclusive overlap in the operation's current snapshot."""
        return self.connection.execute('SELECT EXISTS(SELECT 1 FROM eppm.employee_calendar_exception WHERE employee_id=%s '
                                       'AND start_date<=%s AND end_date>=%s AND (%s::bigint IS NULL OR exception_id<>%s))',
                                       (employee_id, end_date, start_date, exclude_id, exclude_id)).fetchone()[0]

    def create_employee_calendar_exception(self, exception: EmployeeCalendarException) -> int:
        """Insert a native date interval guarded against concurrent overlap."""
        return self.connection.execute('INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage,reason) '
                                       'VALUES (%s,%s,%s,%s,%s) RETURNING exception_id',
                                       (exception.employee_id, exception.start_date, exception.end_date,
                                        exception.occupation_percentage, exception.reason)).fetchone()[0]

    def update_employee_calendar_exception(self, exception: EmployeeCalendarException) -> bool:
        """Change the interval and owner together under native overlap guards."""
        return self.connection.execute('UPDATE eppm.employee_calendar_exception SET employee_id=%s,start_date=%s,end_date=%s,occupation_percentage=%s,reason=%s '
                                       'WHERE exception_id=%s', (exception.employee_id, exception.start_date, exception.end_date,
                                                                 exception.occupation_percentage, exception.reason, exception.exception_id)).rowcount > 0

    def delete_employee_calendar_exception(self, exception_id: int) -> bool:
        """Remove one exception without changing normal occupation."""
        return self.connection.execute('DELETE FROM eppm.employee_calendar_exception WHERE exception_id=%s', (exception_id,)).rowcount > 0

    def get_effective_occupation_percentage(self, employee_id: int, on_date: date) -> float | None:
        """Use an inclusive exception or fall back to normal occupation."""
        row = self.connection.execute('SELECT coalesce((SELECT occupation_percentage FROM eppm.employee_calendar_exception '
                                      'WHERE employee_id=e.employee_id AND start_date<=%s AND end_date>=%s '
                                      'ORDER BY start_date DESC,exception_id DESC LIMIT 1),e.occupation_percentage) '
                                      'FROM eppm.employee e WHERE employee_id=%s', (on_date, on_date, employee_id)).fetchone()
        return row[0] if row else None

    def check_email_exists(self, email: str, exclude_id: int | None = None) -> bool:
        """Check a normalized email, optionally excluding the edited employee."""
        return self.connection.execute('SELECT EXISTS(SELECT 1 FROM eppm.employee WHERE lower(email)=%s '
                                       'AND (%s::bigint IS NULL OR employee_id<>%s))', (email.strip().lower(), exclude_id, exclude_id)).fetchone()[0]

    def check_code_exists(self, code: str, exclude_id: int | None = None) -> bool:
        """Check a normalized employee code without leaking private rows."""
        return self.connection.execute('SELECT EXISTS(SELECT 1 FROM eppm.employee WHERE upper(employee_code)=%s '
                                       'AND (%s::bigint IS NULL OR employee_id<>%s))', (code.strip().upper(), exclude_id, exclude_id)).fetchone()[0]

    def get_team_functions(self, team_id: int) -> list[int]:
        """Read stable, deduplicated membership references."""
        return [row[0] for row in self.connection.execute('SELECT function_id FROM eppm.team_function WHERE team_id=%s ORDER BY function_id', (team_id,))]

    def set_team_functions(self, team_id: int, function_ids: list[int]) -> None:
        """Lock the team before replacing all membership rows atomically."""
        self.connection.execute('SELECT team_id FROM eppm.team WHERE team_id=%s FOR UPDATE', (team_id,))
        self.connection.execute('DELETE FROM eppm.team_function WHERE team_id=%s', (team_id,))
        with self.connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.team_function(team_id,function_id) VALUES (%s,%s)',
                               [(team_id, function_id) for function_id in sorted(set(function_ids))])

    def add_team_function(self, team_id: int, function_id: int) -> bool:
        """Ignore only an existing membership, preserving all other constraints."""
        return self.connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (%s,%s) '
                                       'ON CONFLICT(team_id,function_id) DO NOTHING', (team_id, function_id)).rowcount > 0

    def remove_team_function(self, team_id: int, function_id: int) -> bool:
        """Remove one membership while retaining the referenced function."""
        return self.connection.execute('DELETE FROM eppm.team_function WHERE team_id=%s AND function_id=%s', (team_id, function_id)).rowcount > 0

    def employee_codes(self) -> list[str]:
        """Read existing codes for a preview; native uniqueness protects saves."""
        return [row[0] for row in self.connection.execute('SELECT employee_code FROM eppm.employee')]


class PostgresOrganizationGateway:
    """Bind actual actors and replay complete organization use cases."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject one process pool, trusted server key and current actor policy."""
        self.database, self.key, self.access = database, key, access

    def run[Result](self, operation: Callable[[OrganizationStore], Result], *, write: bool = False,
                    permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Return after commit and translate database errors after rollback/replay."""
        try:
            return run_business(self.database, self.key, self.access,
                                lambda connection: operation(PostgresOrganizationStore(connection)), write=write,
                                permission=permission, project_ids=project_ids)
        except psycopg.IntegrityError:
            raise OrganizationConflictError('The organization change conflicts with an existing reference or unique value.') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Organization storage operation failed (%s)', type(error).__name__)
            raise OrganizationStorageError('Organization data could not be accessed. Please try again.') from None
