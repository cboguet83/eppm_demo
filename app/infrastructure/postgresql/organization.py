"""Native organization queries and atomic mutations on an injected transaction."""

from collections.abc import Callable, Collection, Sequence
from datetime import date
from uuid import uuid4

import psycopg
from psycopg.rows import class_row, dict_row

from app.application.exceptions import OrganizationConflictError, OrganizationStorageError
from app.application.ports.organization import CalendarExceptionRow, OrganizationStore
from app.application.ports.references import EmployeeReference, FunctionReference
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission
from app.domain.hierarchy import HierarchyType
from app.domain.organization.models import Employee, EmployeeCalendarException, EmployeeFunction, FunctionType, OrgFunction, Team
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.hierarchy import hierarchy_types
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.resource_references import require_live_reference, require_live_references
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
        return self._rows(FunctionReference, 'SELECT function_id,name,manager_function_id '
                          'FROM eppm.active_function ORDER BY name COLLATE "C",function_id')

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
            current = self.connection.execute('SELECT code FROM eppm.hierarchy_type WHERE id=%s AND NOT deleted_flag FOR UPDATE', (type_id,)).fetchone()
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
        """Retain the classification and translations as deleted history."""
        return self.connection.execute('UPDATE eppm.hierarchy_type SET deleted_flag=true WHERE id=%s AND NOT deleted_flag', (type_id,)).rowcount > 0

    def hierarchy_type_in_use(self, type_id: int) -> bool:
        """Include historical references when checking classification usage."""
        return self.connection.execute('SELECT EXISTS(SELECT 1 FROM eppm.team WHERE hierarchy_type_id=%s) '
                                       'OR EXISTS(SELECT 1 FROM eppm.resource_pool WHERE hierarchy_type_id=%s)',
                                       (type_id, type_id)).fetchone()[0]

    def function_type_in_use(self, type_id: int) -> bool:
        """Include retained functions when checking classification usage."""
        return self.connection.execute('SELECT EXISTS(SELECT 1 FROM eppm.function WHERE function_type_id=%s)',
                                       (type_id,)).fetchone()[0]

    def get_all_function_types(self) -> list[FunctionType]:
        """Read function types in the existing binary name order."""
        return self._rows(FunctionType, 'SELECT function_type_id,function_type FROM eppm.active_function_type ORDER BY function_type COLLATE "C"')

    def get_function_type_by_id(self, type_id: int) -> FunctionType | None:
        """Find a function type by its stable reference."""
        return self._one(FunctionType, 'SELECT function_type_id,function_type FROM eppm.active_function_type WHERE function_type_id=%s AND NOT deleted_flag', (type_id,))

    def create_function_type(self, ftype: FunctionType) -> int:
        """Insert a normalized function type and return its generated ID."""
        return self.connection.execute('INSERT INTO eppm.function_type(function_type) VALUES (%s) RETURNING function_type_id', (ftype.function_type,)).fetchone()[0]

    def update_function_type(self, ftype: FunctionType) -> bool:
        """Update existing details and preserve the missing-record result."""
        return self.connection.execute('UPDATE eppm.function_type SET function_type=%s WHERE function_type_id=%s AND NOT deleted_flag',
                                       (ftype.function_type, ftype.function_type_id)).rowcount > 0

    def delete_function_type(self, type_id: int) -> bool:
        """Flag the function type while retaining its identity."""
        return self.connection.execute('UPDATE eppm.function_type SET deleted_flag=true WHERE function_type_id=%s AND NOT deleted_flag', (type_id,)).rowcount > 0

    def get_all_functions(self, *, include_deleted: bool = False) -> list[OrgFunction]:
        """Read functions in binary name and identity order."""
        source = 'eppm.function' if include_deleted else 'eppm.active_function'
        return self._rows(OrgFunction, 'SELECT function_id,name,function_type_id,manager_function_id,'
                          f'dual_manager_function_id,fte_percentage,deleted_flag FROM {source} '
                          'ORDER BY name COLLATE "C",function_id')

    def get_function_by_id(self, func_id: int) -> OrgFunction | None:
        """Read one active function with the established FTE default."""
        return self._one(OrgFunction, 'SELECT function_id,name,function_type_id,manager_function_id,'
                         'dual_manager_function_id,coalesce(fte_percentage,100) AS fte_percentage,deleted_flag '
                         'FROM eppm.active_function WHERE function_id=%s AND NOT deleted_flag', (func_id,))

    def create_function(self, func: OrgFunction) -> int:
        """Persist reporting relationships and a generated function identity."""
        self._function_references(func)
        return self.connection.execute('INSERT INTO eppm.function(name,function_type_id,manager_function_id,'
                                       'dual_manager_function_id,fte_percentage) VALUES (%s,%s,%s,%s,%s) RETURNING function_id',
                                       (func.name, func.function_type_id, func.manager_function_id,
                                        func.dual_manager_function_id, func.fte_percentage)).fetchone()[0]

    def update_function(self, func: OrgFunction) -> bool:
        """Update function attributes and reporting relationships together."""
        self._function_references(func)
        return self.connection.execute('UPDATE eppm.function SET name=%s,function_type_id=%s,manager_function_id=%s,'
                                       'dual_manager_function_id=%s,fte_percentage=%s WHERE function_id=%s AND NOT deleted_flag',
                                       (func.name, func.function_type_id, func.manager_function_id,
                                        func.dual_manager_function_id, func.fte_percentage, func.function_id)).rowcount > 0

    def write_imported_function(self, func: OrgFunction) -> None:
        """Persist validated final catalog fields without changing retained memberships."""
        if not func.deleted_flag:
            require_live_reference(self.connection, 'function_type', func.function_type_id)
        try:
            self.connection.execute('UPDATE eppm.function SET name=%s,function_type_id=%s,'
                'manager_function_id=%s,dual_manager_function_id=%s,fte_percentage=%s,deleted_flag=%s WHERE function_id=%s',
                (func.name, func.function_type_id, func.manager_function_id,
                 func.dual_manager_function_id, func.fte_percentage, func.deleted_flag, func.function_id))
        except psycopg.IntegrityError as error:
            field = {
                'function_function_type_id_fkey': 'function_type_id',
                'function_manager_function_id_fkey': 'manager_function_id',
                'function_dual_manager_function_id_fkey': 'dual_manager_function_id',
            }.get(error.diag.constraint_name)
            reason = f'{field} references a missing record.' if field else 'A reference or value violates a database constraint.'
            raise OrganizationConflictError(reason) from None

    def delete_function(self, func_id: int) -> bool:
        """Flag the function while retaining all historical relationships."""
        return self.connection.execute('UPDATE eppm.function SET deleted_flag=true WHERE function_id=%s AND NOT deleted_flag', (func_id,)).rowcount > 0

    def _function_references(self, func: OrgFunction) -> None:
        require_live_reference(self.connection, 'function_type', func.function_type_id)
        require_live_reference(self.connection, 'function', func.manager_function_id)
        require_live_reference(self.connection, 'function', func.dual_manager_function_id)

    def _team_references(self, team: Team) -> None:
        require_live_reference(self.connection, 'hierarchy_type', team.hierarchy_type_id)
        require_live_reference(self.connection, 'team', team.parent_team_id)
        require_live_reference(self.connection, 'function', team.manager_function_id)

    def get_all_teams(self, *, include_deleted: bool = False) -> list[Team]:
        """Read optional hierarchy assignments in the existing name order."""
        source = 'eppm.team' if include_deleted else 'eppm.active_team'
        return self._rows(Team, 'SELECT team_id,team_name,manager_function_id,hierarchy_type_id,parent_team_id,deleted_flag '
                          f'FROM {source} ORDER BY team_name COLLATE "C"')

    def write_imported_team(self, team: Team) -> None:
        """Write validated catalog fields, retaining memberships and history."""
        if not team.deleted_flag:
            require_live_reference(self.connection, 'hierarchy_type', team.hierarchy_type_id)
            require_live_reference(self.connection, 'function', team.manager_function_id)
        self.connection.execute('UPDATE eppm.team SET team_name=%s,manager_function_id=%s,hierarchy_type_id=%s,'
            'parent_team_id=%s,deleted_flag=%s WHERE team_id=%s',
            (team.team_name, team.manager_function_id, team.hierarchy_type_id,
             team.parent_team_id, team.deleted_flag, team.team_id))

    def all_team_functions(self) -> dict[int, list[int]]:
        """Read live explicit memberships in one batch."""
        result: dict[int, list[int]] = {}
        for team_id, function_id in self.connection.execute('SELECT team_id,function_id FROM eppm.active_team_function'):
            result.setdefault(team_id, []).append(function_id)
        return result

    def team_pool_mappings(self) -> list[dict]:
        """Read live team-to-pool mappings without loading project allocations."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return cursor.execute("SELECT m.target_id AS team_id,p.id AS pool_id,p.name AS pool_name,m.allocation_pct "
                "FROM eppm.active_pool_mapping m JOIN eppm.active_resource_pool p ON p.id=m.pool_id "
                "WHERE m.target_type='team' ORDER BY p.name,p.id").fetchall()

    def get_team_by_id(self, team_id: int) -> Team | None:
        """Find a team without loading or altering its members."""
        return self._one(Team, 'SELECT team_id,team_name,manager_function_id,hierarchy_type_id,parent_team_id '
                         'FROM eppm.active_team WHERE team_id=%s AND NOT deleted_flag', (team_id,))

    def create_team(self, team: Team) -> int:
        """Insert team details within the surrounding membership transaction."""
        self._team_references(team)
        return self.connection.execute('INSERT INTO eppm.team(team_name,manager_function_id,hierarchy_type_id,parent_team_id) '
                                       'VALUES (%s,%s,%s,%s) RETURNING team_id',
                                       (team.team_name, team.manager_function_id,
                                        team.hierarchy_type_id, team.parent_team_id)).fetchone()[0]

    def update_team(self, team: Team) -> bool:
        """Update team details and preserve absent-team behavior."""
        self._team_references(team)
        return self.connection.execute('UPDATE eppm.team SET team_name=%s,manager_function_id=%s,hierarchy_type_id=%s,parent_team_id=%s '
                                       'WHERE team_id=%s AND NOT deleted_flag', (team.team_name, team.manager_function_id,
                                                           team.hierarchy_type_id,
                                                           team.parent_team_id, team.team_id)).rowcount > 0

    def delete_team(self, team_id: int) -> bool:
        """Flag the team while retaining its explicit memberships."""
        return self.connection.execute('UPDATE eppm.team SET deleted_flag=true WHERE team_id=%s AND NOT deleted_flag', (team_id,)).rowcount > 0

    def get_all_employees(self, *, include_deleted: bool = False) -> list[Employee]:
        """Read private employee records through the shared-data policy."""
        employees = self._rows(Employee, 'SELECT employee_id,firstname,lastname,email,mobile,sigle,'
                          'NULL::bigint AS function_id,occupation_percentage,landline,deleted_flag FROM eppm.employee '
                          'WHERE (%s OR NOT deleted_flag) '
                          "ORDER BY (upper(lastname) || ' ' || firstname) COLLATE \"C\",employee_id", (include_deleted,))
        return self._attach_employee_functions(employees)

    def _attach_employee_functions(self, employees: list[Employee]) -> list[Employee]:
        people = {person.employee_id: person for person in employees}
        for person in employees:
            person.function_assignments = []
        for employee, function, percentage in self.connection.execute(
            'SELECT employee_id,function_id,allocation_pct FROM eppm.employee_function '
            'WHERE employee_id=ANY(%s::bigint[]) ORDER BY function_id', (list(people),)):
            people[employee].function_assignments.append(EmployeeFunction(function, percentage))
        for person in employees:
            person.function_id = person.function_assignments[0].function_id if len(person.function_assignments) == 1 else None
        return employees

    def get_employee_by_id(self, emp_id: int) -> Employee | None:
        """Read one private employee, preserving nullable contact defaults."""
        person = self._one(Employee, "SELECT employee_id,firstname,lastname,email,coalesce(mobile,'') AS mobile,coalesce(sigle,'') AS sigle,"
                         'NULL::bigint AS function_id,occupation_percentage,landline FROM eppm.active_employee WHERE employee_id=%s AND NOT deleted_flag', (emp_id,))
        return self._attach_employee_functions([person])[0] if person else None

    def create_employee(self, emp: Employee) -> int:
        """Insert an employee within its optional initial-calendar transaction."""
        identity = self.connection.execute('INSERT INTO eppm.employee(firstname,lastname,email,mobile,sigle,function_id,occupation_percentage,landline) '
                                       'VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING employee_id',
                                       (emp.firstname, emp.lastname, emp.email, emp.mobile, emp.sigle,
                                        None, emp.occupation_percentage, emp.landline)).fetchone()[0]
        self._save_employee_functions(identity, emp.assignments())
        return identity

    def _save_employee_functions(self, employee_id: int, assignments: list[EmployeeFunction]) -> None:
        existing = {row[0] for row in self.connection.execute(
            'SELECT function_id FROM eppm.employee_function WHERE employee_id=%s', (employee_id,))}
        require_live_references(self.connection, 'function', [row.function_id for row in assignments if row.function_id not in existing])
        self.connection.execute('DELETE FROM eppm.employee_function WHERE employee_id=%s', (employee_id,))
        with self.connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.employee_function(employee_id,function_id,allocation_pct) VALUES (%s,%s,%s)',
                               [(employee_id, row.function_id, row.allocation_pct) for row in assignments])

    def update_employee(self, emp: Employee) -> bool:
        """Update the employee record under native uniqueness constraints."""
        changed = self.connection.execute('UPDATE eppm.employee SET firstname=%s,lastname=%s,email=%s,mobile=%s,sigle=%s,'
                                       'function_id=%s,occupation_percentage=%s,landline=%s WHERE employee_id=%s AND NOT deleted_flag',
                                       (emp.firstname, emp.lastname, emp.email, emp.mobile, emp.sigle,
                                        None, emp.occupation_percentage, emp.landline, emp.employee_id)).rowcount > 0
        if changed:
            self._save_employee_functions(emp.employee_id, emp.assignments())
        return changed

    def delete_employee(self, emp_id: int) -> bool:
        """Flag the employee while retaining its calendar and mappings."""
        return self.connection.execute('UPDATE eppm.employee SET deleted_flag=true WHERE employee_id=%s AND NOT deleted_flag', (emp_id,)).rowcount > 0

    def write_imported_employee(self, emp: Employee) -> None:
        """Save imported profiles and deletion state without touching calendar history."""
        self.connection.execute('UPDATE eppm.employee SET firstname=%s,lastname=%s,email=%s,mobile=%s,sigle=%s,'
            'occupation_percentage=%s,landline=%s,deleted_flag=%s WHERE employee_id=%s',
            (emp.firstname, emp.lastname, emp.email, emp.mobile, emp.sigle,
             emp.occupation_percentage, emp.landline, emp.deleted_flag, emp.employee_id))
        self._save_employee_functions(emp.employee_id, emp.assignments())

    def get_employee_calendar_exceptions(self, emp_id: int | None = None) -> list[CalendarExceptionRow]:
        """Return native calendar dates as explicit ISO presentation values."""
        return self._rows(CalendarExceptionRow, "SELECT c.exception_id,c.employee_id,e.firstname,e.lastname,"
                          "to_char(c.start_date,'YYYY-MM-DD') AS start_date,to_char(c.end_date,'YYYY-MM-DD') AS end_date,"
                          'c.occupation_percentage,c.reason FROM eppm.employee_calendar_exception c JOIN eppm.active_employee e USING(employee_id) '
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
        if exception.exception_id is not None:
            return self.connection.execute('INSERT INTO eppm.employee_calendar_exception '
                '(exception_id,employee_id,start_date,end_date,occupation_percentage,reason) VALUES (%s,%s,%s,%s,%s,%s) RETURNING exception_id',
                (exception.exception_id, exception.employee_id, exception.start_date, exception.end_date,
                 exception.occupation_percentage, exception.reason)).fetchone()[0]
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
                                      'FROM eppm.active_employee e WHERE employee_id=%s AND NOT deleted_flag', (on_date, on_date, employee_id)).fetchone()
        return row[0] if row else None

    def check_email_exists(self, email: str, exclude_id: int | None = None) -> bool:
        """Check a normalized email, optionally excluding the edited employee."""
        return self.connection.execute('SELECT EXISTS(SELECT 1 FROM eppm.employee WHERE lower(email)=%s '
                                       'AND (%s::bigint IS NULL OR employee_id<>%s))', (email.strip().lower(), exclude_id, exclude_id)).fetchone()[0]

    def get_team_functions(self, team_id: int) -> list[int]:
        """Read stable, deduplicated membership references."""
        return [row[0] for row in self.connection.execute('SELECT function_id FROM eppm.active_team_function WHERE team_id=%s ORDER BY function_id', (team_id,))]

    def set_team_functions(self, team_id: int, function_ids: list[int]) -> None:
        """Lock the team before replacing all membership rows atomically."""
        require_live_reference(self.connection, 'team', team_id)
        require_live_references(self.connection, 'function', function_ids)
        self.connection.execute('SELECT team_id FROM eppm.team WHERE team_id=%s AND NOT deleted_flag FOR UPDATE', (team_id,))
        self.connection.execute('DELETE FROM eppm.team_function WHERE team_id=%s '
                                'AND function_id IN (SELECT function_id FROM eppm.active_function)', (team_id,))
        with self.connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.team_function(team_id,function_id) VALUES (%s,%s)',
                               [(team_id, function_id) for function_id in sorted(set(function_ids))])

    def add_team_function(self, team_id: int, function_id: int) -> bool:
        """Ignore only an existing membership, preserving all other constraints."""
        require_live_reference(self.connection, 'team', team_id)
        require_live_reference(self.connection, 'function', function_id)
        return self.connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (%s,%s) '
                                       'ON CONFLICT(team_id,function_id) DO NOTHING', (team_id, function_id)).rowcount > 0

    def remove_team_function(self, team_id: int, function_id: int) -> bool:
        """Remove one membership while retaining the referenced function."""
        return self.connection.execute('DELETE FROM eppm.team_function WHERE team_id=%s AND function_id=%s', (team_id, function_id)).rowcount > 0


class PostgresOrganizationGateway:
    """Bind actual actors and replay complete organization use cases."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject one process pool, trusted server key and current actor policy."""
        self.database, self.key, self.access = database, key, access

    def run[Result](self, operation: Callable[[OrganizationStore], Result], *, write: bool = False,
                    permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Return after commit and translate database errors after rollback/replay."""
        try:
            def execute(connection):
                result = operation(PostgresOrganizationStore(connection))
                if write:
                    from app.infrastructure.postgresql.staffing_projection import refresh_staffing
                    refresh_staffing(connection)
                return result
            return run_business(self.database, self.key, self.access,
                                execute, write=write,
                                permission=permission, project_ids=project_ids)
        except psycopg.IntegrityError:
            raise OrganizationConflictError('The organization change conflicts with an existing reference or unique value.') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            reference = uuid4().hex[:12]
            source = 'database connection' if isinstance(error, (DatabaseUnavailableError, psycopg.OperationalError)) else 'database operation'
            logger.error('Organization storage operation failed reference=%s source=%s error=%s sqlstate=%s',
                         reference, source, type(error).__name__, getattr(error, 'sqlstate', None))
            raise OrganizationStorageError(f'Organization data could not be accessed: {source} failed. '
                                           f'Please try again. Error reference: {reference}.') from None
