"""Business logic and data transformation service for organizational structures."""

from typing import Any, Optional

import pandas as pd

from app.domain.organization.rules import (
    find_level_3_function,
    is_valid_email, validate_function, validate_team, validate_employee,
    validate_occupation_percentage, validate_employee_calendar_exception,
)
from app.presentation.components.organization_frames import (
    enrich_functions, enrich_employees, enrich_teams,
)
from src.logging_config import get_logger

logger = get_logger(__name__)


class OrganizationService:
    """Provides business validation, formatting, and relational data enrichment for organization entities."""

    is_valid_email = staticmethod(is_valid_email)

    validate_function = staticmethod(validate_function)

    validate_team = staticmethod(validate_team)

    validate_employee = staticmethod(validate_employee)

    validate_occupation_percentage = staticmethod(validate_occupation_percentage)

    validate_employee_calendar_exception = staticmethod(validate_employee_calendar_exception)

    enrich_functions = staticmethod(enrich_functions)

    enrich_employees = staticmethod(enrich_employees)

    enrich_teams = staticmethod(enrich_teams)

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

        return OrganizationService._find_level_3_function(
            function_id, OrganizationService._build_function_lookup(df_functions)
        )

    @staticmethod
    def _build_function_lookup(df_functions: pd.DataFrame) -> dict[int, dict[str, Any]]:
        """Index the hierarchy once when enriching a whole portfolio."""
        func_lookup: dict[int, dict[str, Any]] = {}
        for r in df_functions.to_dict("records"):
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

        return func_lookup

    _find_level_3_function = staticmethod(find_level_3_function)

    @staticmethod
    def enrich_projects_with_organization(
        df_projects: pd.DataFrame,
        df_functions: pd.DataFrame,
        df_employees: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Enriches projects DataFrame with assigned Project Manager and Level 3 Managing Function details.

        Args:
            df_projects: Projects DataFrame containing 'function_id'.
            df_functions: Functions DataFrame containing hierarchy details.
            df_employees: Optional employees DataFrame containing names and
                assigned ``function_id`` values. When supplied, an occupying
                employee's full name is preferred over the function name.

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

        func_name_map = OrganizationService.get_function_occupant_names(
            df_functions,
            df_employees,
        )
        df["project_manager"] = df["function_id"].apply(
            lambda x: func_name_map.get(int(x), "—") if pd.notna(x) and int(x) in func_name_map else "—"
        )

        unique_fids = [int(x) for x in df["function_id"].dropna().unique()]
        func_lookup = OrganizationService._build_function_lookup(df_functions)
        level3_map: dict[int, Optional[dict[str, Any]]] = {
            fid: OrganizationService._find_level_3_function(fid, func_lookup)
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

    @staticmethod
    def get_function_occupant_names(
        df_functions: pd.DataFrame,
        df_employees: Optional[pd.DataFrame] = None,
    ) -> dict[int, str]:
        """Return function labels using the first assigned employee's full name.

        Function names remain the fallback for vacant positions. Employee rows
        are consumed in their existing order, which is deterministic for the
        organization repository (last name, then first name).
        """
        labels: dict[int, str] = {}
        if not df_functions.empty:
            for _, row in df_functions.iterrows():
                try:
                    labels[int(row["function_id"])] = str(row.get("name") or "—")
                except (TypeError, ValueError):
                    continue

        if df_employees is None or df_employees.empty or "function_id" not in df_employees.columns:
            return labels

        occupied: set[int] = set()
        for _, row in df_employees.iterrows():
            function_id = row.get("function_id")
            if pd.isna(function_id):
                continue
            try:
                function_id_int = int(function_id)
            except (TypeError, ValueError):
                continue
            if function_id_int in occupied or function_id_int not in labels:
                continue
            full_name = " ".join(
                part
                for part in (
                    str(row.get("firstname") or "").strip(),
                    str(row.get("lastname") or "").strip(),
                )
                if part
            )
            if full_name:
                labels[function_id_int] = full_name
                occupied.add(function_id_int)
        return labels
