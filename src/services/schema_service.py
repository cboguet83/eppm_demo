"""Business logic service for schema management and identifier calculations."""

from typing import Any, Optional

import pandas as pd

from src.database.connection import get_db
from src.logging_config import get_logger

logger = get_logger(__name__)


class SchemaService:
    """Service providing helper logic for schema taxonomy operations."""

    @staticmethod
    def get_next_available_group_order(db_path: Optional[str] = None) -> int:
        """Calculates the next available display order for schema groups.

        Args:
            db_path: Optional database filepath.

        Returns:
            int: Next available positive integer display order.
        """
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT display_order FROM schema_groups ORDER BY display_order")
            existing = {r[0] for r in cursor.fetchall() if r[0] is not None}
            candidate = 1
            while candidate in existing:
                candidate += 1
            return candidate

    @staticmethod
    def generate_param_id(db_path: Optional[str] = None) -> str:
        """Generates the next sequential parameter ID (e.g., PRM_001, PRM_002).

        Args:
            db_path: Optional database filepath.

        Returns:
            str: Formatted next parameter ID.
        """
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(schema_parameters)")
            param_cols = [c[1] for c in cursor.fetchall()]
            col_to_select = "param_id" if "param_id" in param_cols else "id"
            cursor.execute(f"SELECT {col_to_select} FROM schema_parameters")
            rows = cursor.fetchall()

            max_num = 0
            for (val,) in rows:
                if isinstance(val, int):
                    max_num = max(max_num, val)
                elif isinstance(val, str):
                    if val.startswith("PRM_"):
                        try:
                            num = int(val.split("_")[1])
                            max_num = max(max_num, num)
                        except (IndexError, ValueError):
                            pass
                    elif val.isdigit():
                        max_num = max(max_num, int(val))

            return f"PRM_{max_num + 1:03d}"

    @staticmethod
    def validate_project_dynamic_attributes(
        dynamic_attributes: dict[str, Any], params_df: pd.DataFrame
    ) -> list[str]:
        """Validates that all mandatory dynamic schema parameters have non-empty values.

        Args:
            dynamic_attributes: Dictionary of submitted dynamic attribute values.
            params_df: DataFrame of schema parameters containing [param_id, param_name, mandatory, alias].

        Returns:
            list[str]: List of parameter labels that are missing or empty.
        """
        missing: list[str] = []
        if params_df.empty or "mandatory" not in params_df.columns:
            return missing

        for _, row in params_df.iterrows():
            is_mandatory = bool(row.get("mandatory", False))
            if not is_mandatory:
                continue

            pid = str(row["param_id"])
            pname = str(row.get("param_name", pid))
            alias = str(row.get("alias", "")).strip() if pd.notna(row.get("alias")) else ""

            # Check value under pid, pname, or alias
            val = dynamic_attributes.get(pid)
            if val is None:
                val = dynamic_attributes.get(pname)
            if val is None and alias:
                val = dynamic_attributes.get(alias)

            if val is None:
                missing.append(pname)
            elif isinstance(val, str) and not val.strip():
                missing.append(pname)
            elif isinstance(val, (list, tuple, set)) and len(val) == 0:
                missing.append(pname)

        return missing
