"""Repository for organizational structure: hierarchy levels, functions, function types, and employees."""

from typing import Optional

import pandas as pd

from src.database.connection import get_db
from src.logging_config import get_logger
from src.models.organization import Employee, FunctionType, HierarchyLevel, OrgFunction

logger = get_logger(__name__)


class OrganizationRepository:
    """Encapsulates database operations for organizational hierarchy, functions, function types, and employees."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initializes the OrganizationRepository.

        Args:
            db_path: Path to SQLite database. If None, uses configured default.
        """
        self.db_path = db_path

    # =========================================================================
    # 1. HIERARCHY LEVELS
    # =========================================================================
    def get_all_hierarchy_levels(self) -> pd.DataFrame:
        """Retrieves all hierarchy levels ordered by level tier and name.

        Returns:
            pd.DataFrame: Table of hierarchy levels.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT hierarchy_level_id, name, level, parent_hierarchy_level_id, manager_function_id
                FROM hierarchy_level
                ORDER BY level ASC, name ASC
                """,
                conn,
            )

    def get_hierarchy_level_by_id(self, level_id: int) -> Optional[HierarchyLevel]:
        """Retrieves a single hierarchy level by ID.

        Args:
            level_id: Hierarchy level ID.

        Returns:
            Optional[HierarchyLevel]: HierarchyLevel dataclass if found, else None.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT hierarchy_level_id, name, level, parent_hierarchy_level_id, manager_function_id
                FROM hierarchy_level
                WHERE hierarchy_level_id = ?
                """,
                (level_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return HierarchyLevel(
                hierarchy_level_id=row[0],
                name=row[1],
                level=row[2],
                parent_hierarchy_level_id=row[3],
                manager_function_id=row[4],
            )

    def create_hierarchy_level(self, level: HierarchyLevel) -> int:
        """Creates a new hierarchy level record.

        Args:
            level: HierarchyLevel dataclass instance.

        Returns:
            int: Newly created hierarchy_level_id.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO hierarchy_level (name, level, parent_hierarchy_level_id, manager_function_id)
                VALUES (?, ?, ?, ?)
                """,
                (level.name.strip(), level.level, level.parent_hierarchy_level_id, level.manager_function_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_hierarchy_level(self, level: HierarchyLevel) -> bool:
        """Updates an existing hierarchy level.

        Args:
            level: HierarchyLevel dataclass instance with hierarchy_level_id.

        Returns:
            bool: True if row updated, False otherwise.
        """
        if level.hierarchy_level_id is None:
            return False
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE hierarchy_level
                SET name = ?, level = ?, parent_hierarchy_level_id = ?, manager_function_id = ?
                WHERE hierarchy_level_id = ?
                """,
                (level.name.strip(), level.level, level.parent_hierarchy_level_id, level.manager_function_id, level.hierarchy_level_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_hierarchy_level(self, level_id: int) -> bool:
        """Deletes a hierarchy level by ID.

        Args:
            level_id: Hierarchy level ID to delete.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM hierarchy_level WHERE hierarchy_level_id = ?", (level_id,))
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # 2. FUNCTION TYPES
    # =========================================================================
    def get_all_function_types(self) -> pd.DataFrame:
        """Retrieves all function types ordered by name.

        Returns:
            pd.DataFrame: Table of function types.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT function_type_id, function_type
                FROM function_type
                ORDER BY function_type ASC
                """,
                conn,
            )

    def get_function_type_by_id(self, type_id: int) -> Optional[FunctionType]:
        """Retrieves a single function type by ID.

        Args:
            type_id: Function type ID.

        Returns:
            Optional[FunctionType]: FunctionType dataclass if found, else None.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT function_type_id, function_type FROM function_type WHERE function_type_id = ?",
                (type_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return FunctionType(function_type_id=row[0], function_type=row[1])

    def create_function_type(self, ftype: FunctionType) -> int:
        """Creates a new function type record.

        Args:
            ftype: FunctionType dataclass instance.

        Returns:
            int: Newly created function_type_id.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO function_type (function_type) VALUES (?)",
                (ftype.function_type.strip(),),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_function_type(self, ftype: FunctionType) -> bool:
        """Updates an existing function type record.

        Args:
            ftype: FunctionType dataclass instance with function_type_id.

        Returns:
            bool: True if updated.
        """
        if ftype.function_type_id is None:
            return False
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE function_type SET function_type = ? WHERE function_type_id = ?",
                (ftype.function_type.strip(), ftype.function_type_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_function_type(self, type_id: int) -> bool:
        """Deletes a function type record by ID.

        Args:
            type_id: Function type ID to delete.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM function_type WHERE function_type_id = ?", (type_id,))
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # 3. FUNCTIONS
    # =========================================================================
    def get_all_functions(self) -> pd.DataFrame:
        """Retrieves all job functions.

        Returns:
            pd.DataFrame: Table of functions.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id
                FROM function
                ORDER BY name ASC
                """,
                conn,
            )

    def get_function_by_id(self, func_id: int) -> Optional[OrgFunction]:
        """Retrieves a single function by ID.

        Args:
            func_id: Function ID.

        Returns:
            Optional[OrgFunction]: OrgFunction dataclass if found, else None.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id
                FROM function
                WHERE function_id = ?
                """,
                (func_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return OrgFunction(
                function_id=row[0],
                name=row[1],
                hierarchy_level_id=row[2],
                function_type_id=row[3],
                manager_function_id=row[4],
                dual_manager_function_id=row[5],
            )

    def create_function(self, func: OrgFunction) -> int:
        """Creates a new job function record.

        Args:
            func: OrgFunction dataclass instance.

        Returns:
            int: Newly created function_id.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO function (name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (func.name.strip(), func.hierarchy_level_id, func.function_type_id, func.manager_function_id, func.dual_manager_function_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_function(self, func: OrgFunction) -> bool:
        """Updates an existing job function record.

        Args:
            func: OrgFunction dataclass instance with function_id.

        Returns:
            bool: True if updated.
        """
        if func.function_id is None:
            return False
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE function
                SET name = ?, hierarchy_level_id = ?, function_type_id = ?, manager_function_id = ?, dual_manager_function_id = ?
                WHERE function_id = ?
                """,
                (func.name.strip(), func.hierarchy_level_id, func.function_type_id, func.manager_function_id, func.dual_manager_function_id, func.function_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_function(self, func_id: int) -> bool:
        """Deletes a job function by ID.

        Args:
            func_id: Function ID to delete.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM function WHERE function_id = ?", (func_id,))
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # 4. EMPLOYEES
    # =========================================================================
    def get_all_employees(self) -> pd.DataFrame:
        """Retrieves all employee records ordered by lastname and firstname.

        Returns:
            pd.DataFrame: Table of employees.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT employee_id, firstname, lastname, email, mobile, sigle, employee_code, function_id
                FROM employee
                ORDER BY lastname ASC, firstname ASC
                """,
                conn,
            )

    def get_employee_by_id(self, emp_id: int) -> Optional[Employee]:
        """Retrieves a single employee by ID.

        Args:
            emp_id: Employee ID.

        Returns:
            Optional[Employee]: Employee dataclass if found, else None.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT employee_id, firstname, lastname, email, mobile, sigle, employee_code, function_id
                FROM employee
                WHERE employee_id = ?
                """,
                (emp_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return Employee(
                employee_id=row[0],
                firstname=row[1],
                lastname=row[2],
                email=row[3],
                mobile=row[4] or "",
                sigle=row[5] or "",
                employee_code=row[6],
                function_id=row[7],
            )

    def create_employee(self, emp: Employee) -> int:
        """Creates a new employee record.

        Args:
            emp: Employee dataclass instance.

        Returns:
            int: Newly created employee_id.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO employee (firstname, lastname, email, mobile, sigle, employee_code, function_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    emp.firstname.strip(),
                    emp.lastname.strip(),
                    emp.email.strip().lower(),
                    emp.mobile.strip(),
                    emp.sigle.strip().upper(),
                    emp.employee_code.strip().upper(),
                    emp.function_id,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_employee(self, emp: Employee) -> bool:
        """Updates an existing employee record.

        Args:
            emp: Employee dataclass instance with employee_id.

        Returns:
            bool: True if updated.
        """
        if emp.employee_id is None:
            return False
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE employee
                SET firstname = ?, lastname = ?, email = ?, mobile = ?, sigle = ?, employee_code = ?, function_id = ?
                WHERE employee_id = ?
                """,
                (
                    emp.firstname.strip(),
                    emp.lastname.strip(),
                    emp.email.strip().lower(),
                    emp.mobile.strip(),
                    emp.sigle.strip().upper(),
                    emp.employee_code.strip().upper(),
                    emp.function_id,
                    emp.employee_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_employee(self, emp_id: int) -> bool:
        """Deletes an employee record by ID.

        Args:
            emp_id: Employee ID to delete.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM employee WHERE employee_id = ?", (emp_id,))
            conn.commit()
            return cursor.rowcount > 0

    def check_email_exists(self, email: str, exclude_id: Optional[int] = None) -> bool:
        """Checks whether an email address already exists.

        Args:
            email: Email address to test.
            exclude_id: Optional employee_id to exclude (for update checks).

        Returns:
            bool: True if email already registered.
        """
        clean_email = email.strip().lower()
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            if exclude_id is not None:
                cursor.execute(
                    "SELECT 1 FROM employee WHERE LOWER(email) = ? AND employee_id != ?",
                    (clean_email, exclude_id),
                )
            else:
                cursor.execute("SELECT 1 FROM employee WHERE LOWER(email) = ?", (clean_email,))
            return cursor.fetchone() is not None

    def check_code_exists(self, code: str, exclude_id: Optional[int] = None) -> bool:
        """Checks whether an employee code already exists.

        Args:
            code: Employee badge code (e.g. 'EMP-001').
            exclude_id: Optional employee_id to exclude (for update checks).

        Returns:
            bool: True if code already registered.
        """
        clean_code = code.strip().upper()
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            if exclude_id is not None:
                cursor.execute(
                    "SELECT 1 FROM employee WHERE UPPER(employee_code) = ? AND employee_id != ?",
                    (clean_code, exclude_id),
                )
            else:
                cursor.execute("SELECT 1 FROM employee WHERE UPPER(employee_code) = ?", (clean_code,))
            return cursor.fetchone() is not None

    def generate_next_employee_code(self) -> str:
        """Generates the next sequential employee code (e.g. EMP-001, EMP-002).

        Returns:
            str: Auto-calculated unique employee code.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT employee_code FROM employee")
            rows = cursor.fetchall()

            max_num = 0
            for (val,) in rows:
                if isinstance(val, str) and val.startswith("EMP-"):
                    parts = val.split("-")
                    if len(parts) >= 2 and parts[1].isdigit():
                        try:
                            max_num = max(max_num, int(parts[1]))
                        except ValueError:
                            pass

            next_num = max_num + 1
            candidate = f"EMP-{next_num:03d}"
            while self.check_code_exists(candidate):
                next_num += 1
                candidate = f"EMP-{next_num:03d}"
            return candidate
