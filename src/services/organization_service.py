"""Business logic and data transformation service for organizational structures."""

import re
from typing import Any, Optional

import pandas as pd

from src.logging_config import get_logger

logger = get_logger(__name__)

EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")


class OrganizationService:
    """Provides business validation, formatting, and relational data enrichment for organization entities."""

    @staticmethod
    def is_valid_email(email: str) -> bool:
        """Validates standard email format.

        Args:
            email: Email address string to test.

        Returns:
            bool: True if valid email format.
        """
        if not email or not isinstance(email, str):
            return False
        return bool(EMAIL_REGEX.match(email.strip()))

    @staticmethod
    def validate_function(name: str, hierarchy_level: Optional[int], fte_percentage: int = 100) -> None:
        """Validates job function fields.

        Args:
            name: Function title.
            hierarchy_level: Numerical hierarchy level rank (must be >= 1).
            fte_percentage: FTE workload percentage.

        Raises:
            ValueError: If validation fails.
        """
        if not name or not name.strip():
            raise ValueError("Function name cannot be empty.")
        if hierarchy_level is None or hierarchy_level < 1:
            raise ValueError("Hierarchy level must be an integer greater than or equal to 1.")
        if fte_percentage < 0 or fte_percentage > 100:
            raise ValueError("FTE percentage must be between 0 and 100.")

    @staticmethod
    def validate_team(team_name: str) -> None:
        """Validates team fields.

        Args:
            team_name: Team name.

        Raises:
            ValueError: If validation fails.
        """
        if not team_name or not team_name.strip():
            raise ValueError("Team name cannot be empty.")

    @staticmethod
    def validate_employee(
        firstname: str,
        lastname: str,
        email: str,
        employee_code: str,
    ) -> None:
        """Validates employee profile fields.

        Args:
            firstname: First name.
            lastname: Last name.
            email: Email address.
            employee_code: Unique badge code.

        Raises:
            ValueError: If validation fails.
        """
        if not firstname or not firstname.strip():
            raise ValueError("First name cannot be empty.")
        if not lastname or not lastname.strip():
            raise ValueError("Last name cannot be empty.")
        if not email or not OrganizationService.is_valid_email(email):
            raise ValueError(f"Invalid email address: '{email}'.")
        if not employee_code or not employee_code.strip():
            raise ValueError("Employee code cannot be empty.")

    @staticmethod
    def enrich_functions(
        df_functions: pd.DataFrame,
        df_types: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Enriches job functions DataFrame with readable function type and manager titles.

        Args:
            df_functions: Functions DataFrame.
            df_types: Optional function types DataFrame.

        Returns:
            pd.DataFrame: Enriched DataFrame.
        """
        if df_functions.empty:
            return df_functions

        df = df_functions.copy()
        type_map = (
            dict(zip(df_types["function_type_id"], df_types["function_type"]))
            if df_types is not None and not df_types.empty
            else {}
        )
        func_map = dict(zip(df["function_id"], df["name"]))

        df["function_type_name"] = df["function_type_id"].apply(
            lambda x: type_map.get(x, "—") if pd.notna(x) and x in type_map else "—"
        )
        df["manager_function_name"] = df["manager_function_id"].apply(
            lambda x: func_map.get(x, "—") if pd.notna(x) and x in func_map else "—"
        )
        df["dual_manager_function_name"] = df["dual_manager_function_id"].apply(
            lambda x: func_map.get(x, "—") if pd.notna(x) and x in func_map else "—"
        )
        return df

    @staticmethod
    def enrich_employees(
        df_employees: pd.DataFrame,
        df_functions: pd.DataFrame,
        df_types: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Enriches employee records with full names, function names, and inherited function types.

        Args:
            df_employees: Employees DataFrame.
            df_functions: Functions DataFrame.
            df_types: Optional function types DataFrame.

        Returns:
            pd.DataFrame: Enriched DataFrame.
        """
        if df_employees.empty:
            return df_employees

        df = df_employees.copy()
        func_map = dict(zip(df_functions["function_id"], df_functions["name"])) if not df_functions.empty else {}

        type_lookup = (
            dict(zip(df_types["function_type_id"], df_types["function_type"]))
            if df_types is not None and not df_types.empty
            else {}
        )

        func_to_type = {}
        if not df_functions.empty and "function_type_id" in df_functions.columns:
            for _, r in df_functions.iterrows():
                fid = r.get("function_id")
                ftid = r.get("function_type_id")
                if pd.notna(fid) and pd.notna(ftid) and ftid in type_lookup:
                    func_to_type[fid] = type_lookup[ftid]

        df["full_name"] = df["lastname"].astype(str).str.upper() + " " + df["firstname"].astype(str)
        df["function_name"] = df["function_id"].apply(
            lambda x: func_map.get(x, "—") if pd.notna(x) and x in func_map else "—"
        )
        df["function_type_name"] = df["function_id"].apply(
            lambda x: func_to_type.get(x, "—") if pd.notna(x) and x in func_to_type else "—"
        )
        return df

    @staticmethod
    def enrich_teams(
        df_teams: pd.DataFrame,
        df_functions: pd.DataFrame,
    ) -> pd.DataFrame:
        """Enriches teams DataFrame with readable manager and leader function titles.

        Args:
            df_teams: Teams DataFrame.
            df_functions: Functions DataFrame.

        Returns:
            pd.DataFrame: Enriched DataFrame.
        """
        if df_teams.empty:
            return df_teams

        df = df_teams.copy()
        func_map = dict(zip(df_functions["function_id"], df_functions["name"])) if not df_functions.empty else {}

        df["manager_function_name"] = df["manager_function_id"].apply(
            lambda x: func_map.get(x, "—") if pd.notna(x) and x in func_map else "—"
        )
        df["leader_function_name"] = df["leader_function_id"].apply(
            lambda x: func_map.get(x, "—") if pd.notna(x) and x in func_map else "—"
        )
        return df

    @staticmethod
    def get_level_3_managing_function(
        function_id: Optional[int],
        df_functions: pd.DataFrame,
    ) -> Optional[dict[str, Any]]:
        """Finds the managing function at hierarchy level 3 by traversing up the reporting chain.

        If the function itself is at level 3, returns itself. If above level 3 (levels 1 or 2),
        returns None. If below level 3 (levels 4, 5, etc.), ascends via manager_function_id
        until reaching the ancestor at level 3.

        Args:
            function_id: ID of the starting function (e.g. assigned Project Manager).
            df_functions: DataFrame containing all functions with columns:
                          'function_id', 'name', 'hierarchy_level', 'manager_function_id'.

        Returns:
            Optional[dict[str, Any]]: Dictionary with 'function_id', 'name', and 'hierarchy_level'
                                     of the level 3 function, or None if not found or starting function is None.
        """
        if function_id is None or df_functions.empty or "function_id" not in df_functions.columns:
            return None

        func_lookup: dict[int, dict[str, Any]] = {}
        for _, r in df_functions.iterrows():
            fid = r.get("function_id")
            if pd.isna(fid):
                continue
            try:
                fid_int = int(fid)
                lvl = int(r.get("hierarchy_level", 1)) if pd.notna(r.get("hierarchy_level")) else 1
                mgr = int(r.get("manager_function_id")) if pd.notna(r.get("manager_function_id")) else None
                func_lookup[fid_int] = {
                    "function_id": fid_int,
                    "name": str(r.get("name", "")),
                    "hierarchy_level": lvl,
                    "manager_function_id": mgr,
                }
            except (ValueError, TypeError):
                continue

        curr_id: Optional[int] = function_id
        visited: set[int] = set()
        max_depth = 20
        depth = 0

        while curr_id is not None and curr_id not in visited and depth < max_depth:
            visited.add(curr_id)
            depth += 1
            node = func_lookup.get(curr_id)
            if not node:
                break
            if node["hierarchy_level"] == 3:
                return node
            if node["hierarchy_level"] < 3:
                break
            curr_id = node["manager_function_id"]

        return None

    @staticmethod
    def enrich_projects_with_organization(
        df_projects: pd.DataFrame,
        df_functions: pd.DataFrame,
    ) -> pd.DataFrame:
        """Enriches projects DataFrame with assigned Project Manager and Level 3 Managing Function details.

        Args:
            df_projects: Projects DataFrame containing 'function_id'.
            df_functions: Functions DataFrame containing hierarchy details.

        Returns:
            pd.DataFrame: Enriched projects DataFrame with 'project_manager',
                          'level_3_manager_name', and 'level_3_manager_id'.
        """
        if df_projects.empty:
            return df_projects

        df = df_projects.copy()
        if df_functions.empty:
            df["project_manager"] = "—"
            df["level_3_manager_name"] = "—"
            df["level_3_manager_id"] = None
            return df

        func_name_map = dict(zip(df_functions["function_id"], df_functions["name"]))
        df["project_manager"] = df["function_id"].apply(
            lambda x: func_name_map.get(int(x), "—") if pd.notna(x) and int(x) in func_name_map else "—"
        )

        unique_fids = [int(x) for x in df["function_id"].dropna().unique()]
        level3_map: dict[int, Optional[dict[str, Any]]] = {
            fid: OrganizationService.get_level_3_managing_function(fid, df_functions)
            for fid in unique_fids
        }

        def _get_l3_name(x: Any) -> str:
            if pd.isna(x):
                return "—"
            l3_info = level3_map.get(int(x))
            return l3_info["name"] if l3_info else "—"

        def _get_l3_id(x: Any) -> Optional[int]:
            if pd.isna(x):
                return None
            l3_info = level3_map.get(int(x))
            return int(l3_info["function_id"]) if l3_info else None

        df["level_3_manager_name"] = df["function_id"].apply(_get_l3_name)
        df["level_3_manager_id"] = df["function_id"].apply(_get_l3_id)
        return df


