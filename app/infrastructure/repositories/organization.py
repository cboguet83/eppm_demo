"""SQLite organization adapter; SQL methods share a caller-owned transaction."""

from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date
import sqlite3

from app.application.exceptions import OrganizationConflictError, OrganizationStorageError
from app.application.ports.organization import CalendarExceptionRow, OrganizationStore
from app.domain.organization.models import (
    Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team,
)
from app.infrastructure.database.connection import get_db
from app.shared.logging import get_logger

logger = get_logger(__name__)


class SqliteOrganizationStore:
    """Read and write existing organization tables without owning commits."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Use the connection owned by the gateway transaction."""
        self.connection = connection

    def get_all_function_types(self) -> list[FunctionType]:
        """Retrieves all function types ordered by name."""
        conn = self.connection
        return [FunctionType(**dict(row)) for row in conn.execute("""
            SELECT function_type_id, function_type
            FROM function_type
            ORDER BY function_type ASC
        """, ()).fetchall()]

    def get_function_type_by_id(self, type_id: int) -> FunctionType | None:
        """Retrieves a single function type by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            "SELECT function_type_id, function_type FROM function_type "
            "WHERE function_type_id = ?", (type_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return FunctionType(function_type_id=row[0], function_type=row[1])

    def create_function_type(self, ftype: FunctionType) -> int:
        """Creates a new function type record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO function_type (function_type) VALUES (?)",
            (ftype.function_type,),
        )
        return int(cursor.lastrowid)

    def update_function_type(self, ftype: FunctionType) -> bool:
        """Updates an existing function type record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE function_type SET function_type = ? WHERE function_type_id = ?",
            (ftype.function_type, ftype.function_type_id),
        )
        return cursor.rowcount > 0

    def delete_function_type(self, type_id: int) -> bool:
        """Deletes a function type record by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute('DELETE FROM function_type WHERE function_type_id = ?', (type_id,))
        return cursor.rowcount > 0

    def get_all_functions(self) -> list[OrgFunction]:
        """Retrieves all job functions ordered by hierarchy level and name."""
        conn = self.connection
        return [OrgFunction(**dict(row)) for row in conn.execute("""
            SELECT function_id, name, hierarchy_level, function_type_id, manager_function_id,
                dual_manager_function_id, fte_percentage, has_reports
            FROM function
            ORDER BY hierarchy_level ASC, name ASC
        """, ()).fetchall()]

    def get_function_by_id(self, func_id: int) -> OrgFunction | None:
        """Retrieves a single function by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            SELECT function_id, name, hierarchy_level, function_type_id, manager_function_id,
                dual_manager_function_id, fte_percentage, has_reports
            FROM function
            WHERE function_id = ?
        """, (func_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return OrgFunction(
            function_id=row[0], name=row[1], hierarchy_level=row[2],
            function_type_id=row[3], manager_function_id=row[4],
            dual_manager_function_id=row[5],
            fte_percentage=row[6] if row[6] is not None else 100,
            has_reports=bool(row[7]),
        )

    def create_function(self, func: OrgFunction) -> int:
        """Creates a new job function record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO function (name, hierarchy_level, function_type_id, manager_function_id,
                dual_manager_function_id, fte_percentage, has_reports)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            func.name, func.hierarchy_level, func.function_type_id,
            func.manager_function_id, func.dual_manager_function_id,
            func.fte_percentage, int(func.has_reports),
        ))
        return int(cursor.lastrowid)

    def update_function(self, func: OrgFunction) -> bool:
        """Updates an existing job function record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE function
            SET name = ?, hierarchy_level = ?, function_type_id = ?, manager_function_id = ?,
                dual_manager_function_id = ?, fte_percentage = ?, has_reports = ?
            WHERE function_id = ?
        """, (
            func.name, func.hierarchy_level, func.function_type_id,
            func.manager_function_id, func.dual_manager_function_id,
            func.fte_percentage, int(func.has_reports), func.function_id,
        ))
        return cursor.rowcount > 0

    def delete_function(self, func_id: int) -> bool:
        """Deletes a job function by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute('DELETE FROM function WHERE function_id = ?', (func_id,))
        return cursor.rowcount > 0

    def get_all_teams(self) -> list[Team]:
        """Retrieves all team records ordered by name."""
        conn = self.connection
        return [Team(**dict(row)) for row in conn.execute("""
            SELECT team_id, team_name, manager_function_id, leader_function_id
            FROM team
            ORDER BY team_name ASC
        """, ()).fetchall()]

    def get_team_by_id(self, team_id: int) -> Team | None:
        """Retrieves a single team by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            SELECT team_id, team_name, manager_function_id, leader_function_id
            FROM team
            WHERE team_id = ?
        """, (team_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return Team(
            team_id=row[0], team_name=row[1],
            manager_function_id=row[2], leader_function_id=row[3],
        )

    def create_team(self, team: Team) -> int:
        """Creates a new team record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO team (team_name, manager_function_id, leader_function_id)
            VALUES (?, ?, ?)
        """, (team.team_name, team.manager_function_id, team.leader_function_id))
        return int(cursor.lastrowid)

    def update_team(self, team: Team) -> bool:
        """Updates an existing team record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE team
            SET team_name = ?, manager_function_id = ?, leader_function_id = ?
            WHERE team_id = ?
        """, (
            team.team_name, team.manager_function_id,
            team.leader_function_id, team.team_id,
        ))
        return cursor.rowcount > 0

    def delete_team(self, team_id: int) -> bool:
        """Deletes a team record by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute('DELETE FROM team WHERE team_id = ?', (team_id,))
        return cursor.rowcount > 0

    def get_all_employees(self) -> list[Employee]:
        """Retrieves all employee records ordered by lastname and firstname."""
        conn = self.connection
        return [Employee(**dict(row)) for row in conn.execute("""
            SELECT employee_id, firstname, lastname, email, mobile, sigle, employee_code,
                   function_id, occupation_percentage
            FROM employee
            ORDER BY lastname ASC, firstname ASC
        """, ()).fetchall()]

    def get_employee_by_id(self, emp_id: int) -> Employee | None:
        """Retrieves a single employee by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            SELECT employee_id, firstname, lastname, email, mobile, sigle, employee_code,
                   function_id, occupation_percentage
            FROM employee
            WHERE employee_id = ?
        """, (emp_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return Employee(
            employee_id=row[0], firstname=row[1], lastname=row[2], email=row[3],
            mobile=row[4] or "", sigle=row[5] or "", employee_code=row[6],
            function_id=row[7], occupation_percentage=float(row[8]),
        )

    def create_employee(self, emp: Employee) -> int:
        """Creates a new employee record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO employee (
                firstname, lastname, email, mobile, sigle, employee_code,
                function_id, occupation_percentage
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            emp.firstname, emp.lastname, emp.email, emp.mobile, emp.sigle,
            emp.employee_code, emp.function_id, emp.occupation_percentage,
        ))
        return int(cursor.lastrowid)

    def update_employee(self, emp: Employee) -> bool:
        """Updates an existing employee record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE employee
            SET firstname = ?, lastname = ?, email = ?, mobile = ?, sigle = ?,
                employee_code = ?, function_id = ?, occupation_percentage = ?
            WHERE employee_id = ?
        """, (
            emp.firstname, emp.lastname, emp.email, emp.mobile, emp.sigle,
            emp.employee_code, emp.function_id, emp.occupation_percentage,
            emp.employee_id,
        ))
        return cursor.rowcount > 0

    def delete_employee(self, emp_id: int) -> bool:
        """Deletes an employee record by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute('DELETE FROM employee WHERE employee_id = ?', (emp_id,))
        return cursor.rowcount > 0

    def get_employee_calendar_exceptions(self, emp_id: int | None = None) -> list[CalendarExceptionRow]:
        """Retrieves calendar exceptions, optionally for one employee."""
        conn = self.connection
        query = """
            SELECT ece.exception_id, ece.employee_id, e.employee_code,
                   e.firstname, e.lastname, ece.start_date, ece.end_date,
                   ece.occupation_percentage, ece.reason
            FROM employee_calendar_exception AS ece
            JOIN employee AS e ON e.employee_id = ece.employee_id
        """
        params: tuple[int, ...] = ()
        if emp_id is not None:
            query += ' WHERE ece.employee_id = ?'
            params = (emp_id,)
        query += ' ORDER BY ece.start_date DESC, ece.end_date DESC, ece.exception_id DESC'
        return [CalendarExceptionRow(**dict(row)) for row in conn.execute(query, params).fetchall()]

    def get_employee_calendar_exception_by_id(
        self, exception_id: int,
    ) -> EmployeeCalendarException | None:
        """Retrieves one employee calendar exception by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            SELECT exception_id, employee_id, start_date, end_date,
                   occupation_percentage, reason
            FROM employee_calendar_exception
            WHERE exception_id = ?
        """, (exception_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return EmployeeCalendarException(
            exception_id=row[0], employee_id=row[1],
            start_date=date.fromisoformat(row[2]), end_date=date.fromisoformat(row[3]),
            occupation_percentage=float(row[4]), reason=row[5] or "",
        )

    def has_overlapping_calendar_exception(
        self, employee_id: int, start_date: date, end_date: date,
        exclude_id: int | None = None,
    ) -> bool:
        """Checks for an inclusive period overlap for one employee."""
        conn = self.connection
        query = """
            SELECT 1
            FROM employee_calendar_exception
            WHERE employee_id = ?
              AND start_date <= ?
              AND end_date >= ?
        """
        params: list[int | str] = [employee_id, end_date.isoformat(), start_date.isoformat()]
        if exclude_id is not None:
            query += ' AND exception_id != ?'
            params.append(exclude_id)
        query += ' LIMIT 1'
        cursor = conn.cursor()
        cursor.execute(query, tuple(params))
        return cursor.fetchone() is not None

    def create_employee_calendar_exception(self, exception: EmployeeCalendarException) -> int:
        """Creates a non-overlapping employee calendar exception."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO employee_calendar_exception (
                employee_id, start_date, end_date, occupation_percentage, reason
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            exception.employee_id, exception.start_date.isoformat(),
            exception.end_date.isoformat(), exception.occupation_percentage,
            exception.reason,
        ))
        return int(cursor.lastrowid)

    def update_employee_calendar_exception(self, exception: EmployeeCalendarException) -> bool:
        """Updates a non-overlapping employee calendar exception."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE employee_calendar_exception
            SET employee_id = ?, start_date = ?, end_date = ?,
                occupation_percentage = ?, reason = ?
            WHERE exception_id = ?
        """, (
            exception.employee_id, exception.start_date.isoformat(),
            exception.end_date.isoformat(), exception.occupation_percentage,
            exception.reason, exception.exception_id,
        ))
        return cursor.rowcount > 0

    def delete_employee_calendar_exception(self, exception_id: int) -> bool:
        """Deletes an employee calendar exception."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute('DELETE FROM employee_calendar_exception WHERE exception_id = ?', (exception_id,))
        return cursor.rowcount > 0

    def get_effective_occupation_percentage(self, employee_id: int, on_date: date) -> float | None:
        """Returns the exception percentage for a date, or the employee's normal percentage."""
        conn = self.connection
        target_date = on_date.isoformat()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(
                (
                    SELECT occupation_percentage
                    FROM employee_calendar_exception
                    WHERE employee_id = e.employee_id
                      AND start_date <= ?
                      AND end_date >= ?
                    ORDER BY start_date DESC, exception_id DESC
                    LIMIT 1
                ),
                e.occupation_percentage
            )
            FROM employee AS e
            WHERE e.employee_id = ?
        """, (target_date, target_date, employee_id))
        row = cursor.fetchone()
        return float(row[0]) if row else None

    def check_email_exists(self, email: str, exclude_id: int | None = None) -> bool:
        """Checks whether an email address already exists."""
        conn = self.connection
        clean_email = email.strip().lower()
        cursor = conn.cursor()
        if exclude_id is not None:
            cursor.execute('SELECT 1 FROM employee WHERE LOWER(email) = ? AND employee_id != ?', (clean_email, exclude_id))
        else:
            cursor.execute('SELECT 1 FROM employee WHERE LOWER(email) = ?', (clean_email,))
        return cursor.fetchone() is not None

    def check_code_exists(self, code: str, exclude_id: int | None = None) -> bool:
        """Checks whether an employee code already exists."""
        conn = self.connection
        clean_code = code.strip().upper()
        cursor = conn.cursor()
        if exclude_id is not None:
            cursor.execute('SELECT 1 FROM employee WHERE UPPER(employee_code) = ? AND employee_id != ?', (clean_code, exclude_id))
        else:
            cursor.execute('SELECT 1 FROM employee WHERE UPPER(employee_code) = ?', (clean_code,))
        return cursor.fetchone() is not None

    def get_team_functions(self, team_id: int) -> list[int]:
        """Read team membership in stable function-ID order."""
        return [row[0] for row in self.connection.execute(
            "SELECT function_id FROM team_function WHERE team_id = ? ORDER BY function_id", (team_id,))]

    def set_team_functions(self, team_id: int, function_ids: list[int]) -> None:
        """Replace membership inside the surrounding team transaction."""
        self.connection.execute("DELETE FROM team_function WHERE team_id = ?", (team_id,))
        self.connection.executemany(
            "INSERT INTO team_function (team_id, function_id) VALUES (?, ?)",
            [(team_id, function_id) for function_id in sorted(set(function_ids))],
        )

    def add_team_function(self, team_id: int, function_id: int) -> bool:
        """Add a member once, preserving the legacy boolean result."""
        return self.connection.execute(
            "INSERT OR IGNORE INTO team_function (team_id, function_id) VALUES (?, ?)",
            (team_id, function_id),
        ).rowcount > 0

    def remove_team_function(self, team_id: int, function_id: int) -> bool:
        """Remove a member without deleting its function."""
        return self.connection.execute(
            "DELETE FROM team_function WHERE team_id = ? AND function_id = ?",
            (team_id, function_id),
        ).rowcount > 0

    def employee_codes(self) -> list[str]:
        """Read the existing employee codes for a consistent preview."""
        return [row[0] for row in self.connection.execute("SELECT employee_code FROM employee")]


class SqliteOrganizationGateway:
    """Own organization connection lifetime, writer reservation, and safe errors."""

    def __init__(self, db_path: str | None = None) -> None:
        """Store the configured path without opening the database."""
        self.db_path = db_path

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[OrganizationStore]:
        """Commit once or roll back every write and always close the connection."""
        try:
            with closing(get_db(self.db_path)) as connection:
                connection.row_factory = sqlite3.Row
                with connection:
                    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                    yield SqliteOrganizationStore(connection)
        except sqlite3.IntegrityError as exc:
            raise OrganizationConflictError(
                "The organization change conflicts with an existing reference or unique value."
            ) from exc
        except sqlite3.DatabaseError as exc:
            logger.error("Organization storage operation failed (%s)", type(exc).__name__)
            raise OrganizationStorageError(
                "Organization data could not be accessed. Please try again."
            ) from exc
