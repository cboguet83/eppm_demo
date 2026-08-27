"""Business logic and data transformation service for organizational structures."""

import re
from typing import Optional

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
    def validate_hierarchy_level(name: str, level: int) -> None:
        """Validates hierarchy level fields.

        Args:
            name: Hierarchy level name.
            level: Tier number.

        Raises:
            ValueError: If validation fails.
        """
        if not name or not name.strip():
            raise ValueError("Hierarchy level name cannot be empty.")
        if level < 1:
            raise ValueError("Hierarchy level number must be greater than or equal to 1.")

    @staticmethod
    def validate_function(name: str, hierarchy_level_id: Optional[int]) -> None:
        """Validates job function fields.

        Args:
            name: Function title.
            hierarchy_level_id: Associated hierarchy level ID.

        Raises:
            ValueError: If validation fails.
        """
        if not name or not name.strip():
            raise ValueError("Function name cannot be empty.")
        if hierarchy_level_id is None or hierarchy_level_id <= 0:
            raise ValueError("A valid Hierarchy Level must be selected for the function.")

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
    def enrich_hierarchy_levels(
        df_levels: pd.DataFrame,
        df_functions: pd.DataFrame,
    ) -> pd.DataFrame:
        """Enriches hierarchy level DataFrame with readable parent and manager labels.

        Args:
            df_levels: Hierarchy levels DataFrame.
            df_functions: Functions DataFrame.

        Returns:
            pd.DataFrame: Enriched DataFrame.
        """
        if df_levels.empty:
            return df_levels

        df = df_levels.copy()
        level_map = dict(zip(df["hierarchy_level_id"], df["name"]))
        func_map = dict(zip(df_functions["function_id"], df_functions["name"])) if not df_functions.empty else {}

        df["parent_name"] = df["parent_hierarchy_level_id"].apply(
            lambda x: f"Lvl {x} - {level_map.get(x, '')}" if pd.notna(x) and x in level_map else "— (Top Level)"
        )
        df["manager_function_name"] = df["manager_function_id"].apply(
            lambda x: func_map.get(x, "—") if pd.notna(x) and x in func_map else "—"
        )
        return df

    @staticmethod
    def enrich_functions(
        df_functions: pd.DataFrame,
        df_levels: pd.DataFrame,
        df_types: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Enriches job functions DataFrame with readable level, function type, and manager titles.

        Args:
            df_functions: Functions DataFrame.
            df_levels: Hierarchy levels DataFrame.
            df_types: Optional function types DataFrame.

        Returns:
            pd.DataFrame: Enriched DataFrame.
        """
        if df_functions.empty:
            return df_functions

        df = df_functions.copy()
        level_map = dict(zip(df_levels["hierarchy_level_id"], df_levels["name"])) if not df_levels.empty else {}
        type_map = (
            dict(zip(df_types["function_type_id"], df_types["function_type"]))
            if df_types is not None and not df_types.empty
            else {}
        )
        func_map = dict(zip(df["function_id"], df["name"]))

        df["hierarchy_level_name"] = df["hierarchy_level_id"].apply(
            lambda x: level_map.get(x, f"Level {x}") if pd.notna(x) else "—"
        )
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
