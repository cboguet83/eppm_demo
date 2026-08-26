"""Business logic service for milestone schedule processing and CSV import/export."""

import io
from typing import Any

import pandas as pd


class MilestoneService:
    """Service handling milestone schedule validations and CSV operations."""

    @staticmethod
    def get_csv_template() -> str:
        """Returns a CSV string template for bulk milestone imports.

        Returns:
            str: CSV text template with sample header and rows.
        """
        return (
            "task_name,phase,start_date,end_date,progress_pct\n"
            "Sample Task 1,Phase 1 - Inception,2026-06-01,2026-06-30,50\n"
            "Sample Task 2,Phase 2 - Build,2026-07-01,2026-08-15,0\n"
        )

    @staticmethod
    def parse_csv(uploaded_file: Any, project_id: str) -> list[dict[str, Any]]:
        """Parses and validates an uploaded milestone CSV file.

        Args:
            uploaded_file: Streamlit UploadedFile or file-like buffer.
            project_id: Parent project code to attach to each milestone.

        Returns:
            list[dict[str, Any]]: List of validated milestone dictionary payloads.

        Raises:
            ValueError: If required columns are missing or data is malformed.
        """
        df = pd.read_csv(uploaded_file)
        required_cols = {"task_name", "start_date", "end_date"}
        if not required_cols.issubset(set(df.columns)):
            missing = required_cols - set(df.columns)
            raise ValueError(f"CSV is missing required columns: {missing}")

        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            results.append({
                "project_id": project_id,
                "task_name": str(row["task_name"]).strip(),
                "phase": str(row.get("phase", "General")).strip(),
                "start_date": str(row["start_date"]).strip(),
                "end_date": str(row["end_date"]).strip(),
                "progress_pct": int(row.get("progress_pct", 0)),
            })
        return results
