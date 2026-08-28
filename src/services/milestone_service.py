"""Business logic service for milestone schedule processing and CSV import/export."""

import datetime
import io
from typing import Any, Optional, Union

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
            "task_name,phase,start_date,end_date,progress_pct,description,predecessor_id\n"
            "Architecture Scoping,Phase 1 - Inception,2026-06-01,2026-06-15,100,Define system blueprint,\n"
            "Architecture Milestone,Phase 1 - Inception,2026-06-15,2026-06-15,100,Sign-off on specs,1\n"
            "Core Build,Phase 2 - Build,2026-06-16,2026-07-30,50,Core API services,2\n"
        )

    @staticmethod
    def parse_csv(uploaded_file: Any, project_id: Union[int, str]) -> list[dict[str, Any]]:
        """Parses and validates an uploaded step/milestone CSV file.

        Args:
            uploaded_file: Uploaded file object from Streamlit.
            project_id: Project ID to associate with imported milestones.

        Returns:
            list[dict[str, Any]]: List of milestone records ready for database insertion.

        Raises:
            ValueError: If file is empty, missing required columns, or contains invalid dates.
        """
        if uploaded_file is None:
            raise ValueError("No file uploaded.")

        try:
            df = pd.read_csv(uploaded_file)
        except Exception as e:
            raise ValueError(f"Failed to read CSV file: {e}")

        if df.empty:
            raise ValueError("Uploaded CSV is empty.")

        required_cols = {"task_name", "start_date", "end_date"}
        missing_cols = required_cols - set(df.columns)
        if missing_cols:
            raise ValueError(f"Missing required columns in CSV: {', '.join(sorted(missing_cols))}")

        records: list[dict[str, Any]] = []
        for idx, row in df.iterrows():
            row_num = idx + 2  # CSV 1-indexed plus header
            task_name = str(row["task_name"]).strip()
            if not task_name:
                raise ValueError(f"Row {row_num}: 'task_name' cannot be empty.")

            try:
                start_date = pd.to_datetime(row["start_date"]).strftime("%Y-%m-%d")
                end_date = pd.to_datetime(row["end_date"]).strftime("%Y-%m-%d")
            except Exception as e:
                raise ValueError(f"Row {row_num}: Invalid date format ({e}). Use YYYY-MM-DD.")

            if start_date > end_date:
                raise ValueError(
                    f"Row {row_num}: Start date ({start_date}) cannot be after End date ({end_date})."
                )

            phase = str(row.get("phase", "General")).strip() or "General"
            description = str(row.get("description", "")).strip() if pd.notna(row.get("description")) else ""

            try:
                progress = int(row.get("progress_pct", 0)) if pd.notna(row.get("progress_pct")) else 0
                progress = max(0, min(100, progress))
            except (ValueError, TypeError):
                progress = 0

            pred_val = row.get("predecessor_id")
            predecessor_id = None
            if pd.notna(pred_val) and str(pred_val).strip():
                try:
                    predecessor_id = int(float(str(pred_val).strip()))
                except (ValueError, TypeError):
                    predecessor_id = None

            records.append({
                "project_id": project_id,
                "task_name": task_name,
                "phase": phase,
                "start_date": start_date,
                "end_date": end_date,
                "progress_pct": progress,
                "description": description,
                "predecessor_id": predecessor_id,
            })

        return records

    @staticmethod
    def evaluate_constraints(
        tasks: list[dict[str, Any]],
        dependencies: list[dict[str, Any]],
        project_bounds: Optional[dict[str, tuple[Optional[str], Optional[str]]]] = None,
    ) -> tuple[list[dict[str, Any]], dict[int, list[str]]]:
        """Evaluates scheduling constraints across multi-dependency links with high performance.

        Supports standard link types:
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
        tasks_by_id: dict[int, dict[str, Any]] = {}
        parsed_dates: dict[int, tuple[datetime.date, datetime.date]] = {}
        task_violations: dict[int, list[str]] = {}

        for t in tasks:
            if "id" not in t:
                continue
            tid = int(t["id"])
            tasks_by_id[tid] = t
            task_violations[tid] = []
            try:
                s_str = str(t.get("start_date", "")).split()[0]
                e_str = str(t.get("end_date", "")).split()[0]
                parsed_dates[tid] = (
                    datetime.date.fromisoformat(s_str),
                    datetime.date.fromisoformat(e_str),
                )
            except Exception:
                pass

        evaluated_deps: list[dict[str, Any]] = []

        for dep in dependencies:
            task_id = dep.get("task_id")
            if task_id is None:
                continue
            task_id = int(task_id)
            if task_id not in tasks_by_id or task_id not in parsed_dates:
                continue

            task = tasks_by_id[task_id]
            s_start_dt, s_end_dt = parsed_dates[task_id]

            pred_task_id = dep.get("predecessor_task_id")
            pred_proj_id = dep.get("predecessor_project_id")
            link_type = str(dep.get("link_type", "FS")).upper()
            lag_days = int(dep.get("lag_days", 0))

            p_start_str: Optional[str] = None
            p_end_str: Optional[str] = None
            p_start_dt: Optional[datetime.date] = None
            p_end_dt: Optional[datetime.date] = None
            p_label: str = "Predecessor"

            if pred_task_id is not None and int(pred_task_id) in tasks_by_id:
                pid = int(pred_task_id)
                pred_task = tasks_by_id[pid]
                p_start_str = str(pred_task.get("start_date", ""))
                p_end_str = str(pred_task.get("end_date", ""))
                if pid in parsed_dates:
                    p_start_dt, p_end_dt = parsed_dates[pid]
                p_label = str(pred_task.get("task_name", f"Step #{pred_task_id}"))
            elif pred_task_id is not None:
                p_start_str = dep.get("pred_start_date")
                p_end_str = dep.get("pred_end_date")
                p_label = f"{dep.get('predecessor_project_name') or pred_proj_id or 'Ext'} > {dep.get('predecessor_task_name') or f'Step #{pred_task_id}'}"
                if p_start_str and p_end_str:
                    try:
                        p_start_dt = datetime.date.fromisoformat(str(p_start_str).split()[0])
                        p_end_dt = datetime.date.fromisoformat(str(p_end_str).split()[0])
                    except Exception:
                        pass
            elif pred_proj_id is not None:
                p_b = bounds.get(str(pred_proj_id), (None, None))
                p_start_str, p_end_str = p_b
                p_label = f"Project [{dep.get('predecessor_project_name') or pred_proj_id}]"
                if p_start_str and p_end_str:
                    try:
                        p_start_dt = datetime.date.fromisoformat(str(p_start_str).split()[0])
                        p_end_dt = datetime.date.fromisoformat(str(p_end_str).split()[0])
                    except Exception:
                        pass

            if not p_start_dt or not p_end_dt:
                evaluated_deps.append({**dep, "is_violated": False, "violation_text": None})
                continue

            delta = datetime.timedelta(days=lag_days)
            is_violated = False
            message = ""

            if link_type == "FS":
                target_dt = p_end_dt + delta
                is_violated = s_start_dt < target_dt
                req_str = target_dt.isoformat()
                act_str = str(task["start_date"])
                message = f"FS with '{p_label}' ({lag_days:+d}d offset): Start must be ≥ {req_str} (actual: {act_str})"
            elif link_type == "FF":
                target_dt = p_end_dt + delta
                is_violated = s_end_dt < target_dt
                req_str = target_dt.isoformat()
                act_str = str(task["end_date"])
                message = f"FF with '{p_label}' ({lag_days:+d}d offset): End must be ≥ {req_str} (actual: {act_str})"
            elif link_type == "SS":
                target_dt = p_start_dt + delta
                is_violated = s_start_dt < target_dt
                req_str = target_dt.isoformat()
                act_str = str(task["start_date"])
                message = f"SS with '{p_label}' ({lag_days:+d}d offset): Start must be ≥ {req_str} (actual: {act_str})"
            elif link_type == "SF":
                target_dt = p_start_dt + delta
                is_violated = s_end_dt < target_dt
                req_str = target_dt.isoformat()
                act_str = str(task["end_date"])
                message = f"SF with '{p_label}' ({lag_days:+d}d offset): End must be ≥ {req_str} (actual: {act_str})"

            eval_dict = {
                **dep,
                "is_violated": is_violated,
                "violation_text": message if is_violated else None,
                "pred_start": p_start_str,
                "pred_end": p_end_str,
                "pred_label": p_label,
            }
            evaluated_deps.append(eval_dict)

            if is_violated:
                task_violations[task_id].append(message)

        return evaluated_deps, task_violations
