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

    @staticmethod
    def evaluate_constraints(
        tasks: list[dict[str, Any]],
        dependencies: list[dict[str, Any]],
        project_bounds: Optional[dict[str, tuple[Optional[str], Optional[str]]]] = None,
    ) -> tuple[list[dict[str, Any]], dict[int, list[str]]]:
        """Evaluates scheduling constraints across all dependencies.

        Rules:
            FS: Successor Start >= Predecessor End + Lag Days
            FF: Successor End >= Predecessor End + Lag Days
            SS: Successor Start >= Predecessor Start + Lag Days
            SF: Successor End >= Predecessor Start + Lag Days

        Args:
            tasks: List of task dictionaries for the active project.
            dependencies: List of dependency dictionaries.
            project_bounds: Dict mapping project_id -> (min_start_date, max_end_date) for external project predecessors.

        Returns:
            tuple:
                - evaluated_dependencies: list of dependency dicts with keys [is_violated, violation_text, pred_start, pred_end, target_date, actual_date].
                - task_violations: dict mapping task_id -> list of violation explanation strings.
        """
        bounds = project_bounds or {}
        tasks_by_id = {int(t["id"]): t for t in tasks if "id" in t}
        evaluated_deps: list[dict[str, Any]] = []
        task_violations: dict[int, list[str]] = {int(t["id"]): [] for t in tasks if "id" in t}

        for dep in dependencies:
            task_id = dep.get("task_id")
            if task_id is None or int(task_id) not in tasks_by_id:
                continue

            task_id = int(task_id)
            task = tasks_by_id[task_id]
            pred_task_id = dep.get("predecessor_task_id")
            pred_proj_id = dep.get("predecessor_project_id")
            link_type = str(dep.get("link_type", "FS")).upper()
            lag_days = int(dep.get("lag_days", 0))

            p_start: Optional[str] = None
            p_end: Optional[str] = None
            p_label: str = "Predecessor"

            if pred_task_id is not None and int(pred_task_id) in tasks_by_id:
                pred_task = tasks_by_id[int(pred_task_id)]
                p_start = pred_task.get("start_date")
                p_end = pred_task.get("end_date")
                p_label = str(pred_task.get("task_name", f"Step #{pred_task_id}"))
            elif pred_task_id is not None:
                p_start = dep.get("pred_start_date")
                p_end = dep.get("pred_end_date")
                p_label = f"{dep.get('predecessor_project_name') or pred_proj_id or 'Ext'} > {dep.get('predecessor_task_name') or f'Step #{pred_task_id}'}"
            elif pred_proj_id is not None:
                p_b = bounds.get(str(pred_proj_id), (None, None))
                p_start, p_end = p_b
                p_label = f"Project [{dep.get('predecessor_project_name') or pred_proj_id}]"

            if not p_start or not p_end:
                evaluated_deps.append({**dep, "is_violated": False, "violation_text": None})
                continue

            s_start_dt = pd.to_datetime(task["start_date"])
            s_end_dt = pd.to_datetime(task["end_date"])
            p_start_dt = pd.to_datetime(p_start)
            p_end_dt = pd.to_datetime(p_end)

            is_violated = False
            message = ""
            target_dt = None

            if link_type == "FS":
                target_dt = p_end_dt + pd.Timedelta(days=lag_days)
                is_violated = s_start_dt < target_dt
                req_str = target_dt.strftime("%Y-%m-%d")
                act_str = str(task["start_date"])
                message = f"FS with '{p_label}' ({lag_days:+d}d offset): Start must be ≥ {req_str} (actual: {act_str})"
            elif link_type == "FF":
                target_dt = p_end_dt + pd.Timedelta(days=lag_days)
                is_violated = s_end_dt < target_dt
                req_str = target_dt.strftime("%Y-%m-%d")
                act_str = str(task["end_date"])
                message = f"FF with '{p_label}' ({lag_days:+d}d offset): End must be ≥ {req_str} (actual: {act_str})"
            elif link_type == "SS":
                target_dt = p_start_dt + pd.Timedelta(days=lag_days)
                is_violated = s_start_dt < target_dt
                req_str = target_dt.strftime("%Y-%m-%d")
                act_str = str(task["start_date"])
                message = f"SS with '{p_label}' ({lag_days:+d}d offset): Start must be ≥ {req_str} (actual: {act_str})"
            elif link_type == "SF":
                target_dt = p_start_dt + pd.Timedelta(days=lag_days)
                is_violated = s_end_dt < target_dt
                req_str = target_dt.strftime("%Y-%m-%d")
                act_str = str(task["end_date"])
                message = f"SF with '{p_label}' ({lag_days:+d}d offset): End must be ≥ {req_str} (actual: {act_str})"

            eval_dict = {
                **dep,
                "is_violated": is_violated,
                "violation_text": message if is_violated else None,
                "pred_start": p_start,
                "pred_end": p_end,
                "pred_label": p_label,
            }
            evaluated_deps.append(eval_dict)

            if is_violated:
                task_violations[task_id].append(message)

        return evaluated_deps, task_violations
