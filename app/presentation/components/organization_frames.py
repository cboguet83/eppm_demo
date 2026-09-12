"""Format plain organization records for Streamlit."""

from dataclasses import asdict

import pandas as pd

from app.application.ports.organization import CalendarExceptionRow
from app.domain.organization.models import Employee, FunctionType, OrgFunction, Team

def function_types_frame(records: list[FunctionType]) -> pd.DataFrame:
    """Retain the existing function types columns, including empty catalogs."""
    return pd.DataFrame([asdict(record) for record in records], columns=['function_type_id', 'function_type'])


def functions_frame(records: list[OrgFunction]) -> pd.DataFrame:
    """Retain the existing functions columns, including empty catalogs."""
    return pd.DataFrame([asdict(record) for record in records], columns=['function_id', 'name', 'hierarchy_level', 'function_type_id', 'manager_function_id', 'dual_manager_function_id', 'fte_percentage', 'has_reports'])


def teams_frame(records: list[Team]) -> pd.DataFrame:
    """Retain the existing teams columns, including empty catalogs."""
    return pd.DataFrame([asdict(record) for record in records], columns=['team_id', 'team_name', 'manager_function_id', 'leader_function_id', 'hierarchy_type_id'])


def employees_frame(records: list[Employee]) -> pd.DataFrame:
    """Retain the existing employees columns, including empty catalogs."""
    return pd.DataFrame([asdict(record) for record in records], columns=['employee_id', 'firstname', 'lastname', 'email', 'mobile', 'landline', 'sigle', 'employee_code', 'function_id', 'occupation_percentage'])


def exceptions_frame(records: list[CalendarExceptionRow]) -> pd.DataFrame:
    """Retain the existing exceptions columns, including empty catalogs."""
    return pd.DataFrame([asdict(record) for record in records], columns=['exception_id', 'employee_id', 'employee_code', 'firstname', 'lastname', 'start_date', 'end_date', 'occupation_percentage', 'reason'])


def enrich_functions(
    df_functions: pd.DataFrame,
    df_types: pd.DataFrame | None = None,
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


def enrich_employees(
    df_employees: pd.DataFrame,
    df_functions: pd.DataFrame,
    df_types: pd.DataFrame | None = None,
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
