"""Business logic service for milestone schedule processing and CSV import/export."""

import io
from typing import Any, Optional

import pandas as pd


class MilestoneService:
    """Service handling milestone schedule validations and CSV operations."""

    @staticmethod
    def get_csv_template() -> str:
        """Returns a CSV string template for bulk step/milestone imports.

        Returns:
            str: CSV text template with sample header and rows.
        """
        return (
            "task_name,phase,start_date,end_date,progress_pct,predecessor_id\n"
            "Architecture Scoping,Phase 1 - Inception,2026-06-01,2026-06-15,100,\n"
            "Architecture Milestone,Phase 1 - Inception,2026-06-15,2026-06-15,100,1\n"
            "Core Build,Phase 2 - Build,2026-06-16,2026-07-30,50,2\n"
        )

    @staticmethod
    def parse_csv(uploaded_file: Any, project_id: str) -> list[dict[str, Any]]:
        """Parses and validates an uploaded step/milestone CSV file.

        Args:
            uploaded_file: Streamlit UploadedFile or file-like buffer.
            project_id: Parent project code to attach to each milestone.

        Returns:
            list[dict[str, Any]]: List of validated milestone dictionary payloads.

        Raises:
            ValueError: If required columns are missing or dates are invalid.
        """
        df = pd.read_csv(uploaded_file)
        required_cols = {"task_name", "start_date", "end_date"}
        if not required_cols.issubset(set(df.columns)):
            missing = required_cols - set(df.columns)
            raise ValueError(f"CSV is missing required columns: {missing}")

        results: list[dict[str, Any]] = []
        for idx, row in df.iterrows():
            start_str = str(row["start_date"]).strip()
            end_str = str(row["end_date"]).strip()
            if start_str > end_str:
                raise ValueError(f"Row {idx + 1}: End Date ({end_str}) must be greater than or equal to Start Date ({start_str}).")

            pred_val: Optional[int] = None
            if "predecessor_id" in row and pd.notna(row["predecessor_id"]):
                try:
                    pred_val = int(row["predecessor_id"])
                except (ValueError, TypeError):
                    pred_val = None

            results.append({
                "project_id": project_id,
                "task_name": str(row["task_name"]).strip(),
                "phase": str(row.get("phase", "General")).strip(),
                "start_date": start_str,
                "end_date": end_str,
                "progress_pct": int(row.get("progress_pct", 0)),
                "predecessor_id": pred_val,
            })
        return results
