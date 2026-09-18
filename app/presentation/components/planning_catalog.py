"""Project catalog formatting for planning's dynamic filters.

Any marks the presentation DataFrame boundary for project and occupant labels.
"""

from typing import Any
import pandas as pd


def enrich_projects_with_organization(
    df_projects: pd.DataFrame, df_functions: pd.DataFrame, df_employees: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Enrich projects with their directly assigned project manager label.

    Args:
        df_projects: Projects DataFrame containing 'function_id'.
        df_functions: Functions DataFrame containing function identities and names.
        df_employees: Optional employees DataFrame containing names and
            assigned ``function_id`` values. When supplied, an occupying
            employee's full name is preferred over the function name.

    Returns:
        pd.DataFrame: A copy containing the assigned 'project_manager' label.
    """
    if df_projects.empty:
        return df_projects
    df = df_projects.copy()
    if df_functions.empty:
        df["project_manager"] = "—"
        return df
    func_name_map = get_function_occupant_names(df_functions, df_employees)
    df["project_manager"] = df["function_id"].apply(
        lambda x: (
            func_name_map.get(int(x), "—") if pd.notna(x) and int(x) in func_name_map else "—"
        )
    )
    return df


def get_function_occupant_names(
    df_functions: pd.DataFrame, df_employees: pd.DataFrame | None = None
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
            except TypeError, ValueError:
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
        except TypeError, ValueError:
            continue
        if function_id_int in occupied or function_id_int not in labels:
            continue
        full_name = " ".join(
            (
                part
                for part in (
                    str(row.get("firstname") or "").strip(),
                    str(row.get("lastname") or "").strip(),
                )
                if part
            )
        )
        if full_name:
            labels[function_id_int] = full_name
            occupied.add(function_id_int)
    return labels


def flatten_dynamic_attributes(df_projects: pd.DataFrame, params: pd.DataFrame) -> pd.DataFrame:
    """Unpacks in-memory attributes into individual DataFrame columns.

    Args:
        df_projects: Projects DataFrame containing id and dynamic_attributes columns.
        params: Schema parameters DataFrame with param_id, param_type.

    Returns:
        pd.DataFrame: Merged DataFrame with flattened dynamic attributes.
    """
    if df_projects.empty:
        return df_projects
    flattened_rows: list[dict[str, Any]] = []
    for _, row in df_projects.iterrows():
        attrs = dict(row["dynamic_attributes"])
        attrs["id"] = row["id"]
        flattened_rows.append(attrs)
    df_dyn = pd.DataFrame(flattened_rows)
    df_merged = pd.merge(df_projects, df_dyn, on="id", how="left", suffixes=("", "_dyn"))
    if not params.empty and "param_id" in params.columns:
        for _, p in params.iterrows():
            pid = str(p["param_id"])
            pname = str(p.get("param_name", pid))
            ptype = str(p.get("param_type", "TEXT"))
            if pid not in df_merged.columns:
                df_merged[pid] = None
            if ptype in ("MULTI_ENUM", "TAGS"):
                df_merged[pid] = df_merged[pid].apply(
                    lambda x: x if isinstance(x, list) else [x] if pd.notna(x) and x != "" else []
                )
            if pname != pid:
                df_merged[pname] = df_merged[pid]
    return df_merged
