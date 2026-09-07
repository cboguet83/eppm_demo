"""Business logic, capacity calculation, de-duplication, and daily overassignment analysis for Resource Pools."""

import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import pandas as pd

from src.logging_config import get_logger
from src.models.resource_pool import (
    DailyOverassignment,
    PoolCapacityDetail,
    PoolFunctionContribution,
)
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository

logger = get_logger(__name__)


class ResourcePoolService:
    """Provides validation, capacity calculation, de-duplication, and daily overassignment evaluation for Resource Pools."""

    @staticmethod
    def validate_pool_name(name: str) -> None:
        """Validates that a resource pool name is non-empty.

        Args:
            name: Resource pool name to validate.

        Raises:
            ValueError: If name is empty or whitespace.
        """
        if not name or not name.strip():
            raise ValueError("Resource pool name cannot be empty.")

    @staticmethod
    def validate_allocation_pct(allocation_pct: float) -> None:
        """Validates that a mapping allocation percentage is between 0.0 and 100.0.

        Args:
            allocation_pct: Percentage value to test.

        Raises:
            ValueError: If percentage is outside [0.0, 100.0].
        """
        if allocation_pct < 0.0 or allocation_pct > 100.0:
            raise ValueError(f"Allocation percentage must be between 0.0 and 100.0 (got {allocation_pct}).")

    @staticmethod
    def validate_fte(fte: float) -> None:
        """Validates that an assigned FTE value is non-negative.

        Args:
            fte: FTE value to test.

        Raises:
            ValueError: If FTE is negative.
        """
        if fte < 0.0:
            raise ValueError(f"Assigned FTE must be greater than or equal to 0.0 (got {fte}).")

    @staticmethod
    def validate_capacity_fte(capacity_fte: float) -> None:
        """Validate a user-defined pool capacity limit."""
        if capacity_fte < 0.0:
            raise ValueError(f"Pool capacity must be greater than or equal to 0.0 (got {capacity_fte}).")

    @classmethod
    def calculate_pool_capacity(
        cls,
        pool_id: int,
        org_repo: OrganizationRepository,
        pool_repo: ResourcePoolRepository,
        milestone_repo: Optional[MilestoneRepository] = None,
    ) -> PoolCapacityDetail:
        """Calculate defined capacity, deduplicated assigned capacity, and demand status.

        Employees can be mapped directly or reached through one or more assigned teams.
        Each employee contributes at most once. A direct employee/function mapping takes
        precedence over team-derived membership; among multiple teams, the highest
        allocation is used. Legacy function-only pools remain supported.

        Daily overassignment rule: On each calendar date, total assigned FTE is aggregated.
        If the peak daily assigned FTE exceeds total pool capacity, the pool is overassigned.

        Args:
            pool_id: Resource pool ID.
            org_repo: Organization repository instance.
            pool_repo: Resource pool repository instance.
            milestone_repo: Optional milestone repository instance for project date bounds.

        Returns:
            PoolCapacityDetail: Complete breakdown of capacity, contributions, and daily overassignments.
        """
        pool = pool_repo.get_pool_by_id(pool_id)
        pool_name = pool.name if pool else f"Pool #{pool_id}"

        # 1. Fetch Mappings
        df_mappings = pool_repo.get_mappings_by_pool(pool_id)
        df_funcs = org_repo.get_all_functions()
        df_teams = org_repo.get_all_teams()
        df_employees = org_repo.get_all_employees()

        func_dict: Dict[int, Dict[str, Any]] = {}
        if not df_funcs.empty:
            for _, r in df_funcs.iterrows():
                func_dict[int(r["function_id"])] = {
                    "name": str(r["name"]),
                    "fte_percentage": float(r["fte_percentage"]) if pd.notna(r.get("fte_percentage")) else 100.0,
                    "manager_function_id": int(r["manager_function_id"]) if pd.notna(r.get("manager_function_id")) else None,
                }

        team_dict: Dict[int, Dict[str, Any]] = {}
        if not df_teams.empty:
            for _, r in df_teams.iterrows():
                team_dict[int(r["team_id"])] = {
                    "name": str(r["team_name"]),
                    "manager_function_id": int(r["manager_function_id"]) if pd.notna(r.get("manager_function_id")) else None,
                    "leader_function_id": int(r["leader_function_id"]) if pd.notna(r.get("leader_function_id")) else None,
                }

        employee_dict: Dict[int, Dict[str, Any]] = {}
        employees_by_function: Dict[int, List[int]] = {}
        if not df_employees.empty:
            for _, r in df_employees.iterrows():
                employee_id = int(r["employee_id"])
                function_id = int(r["function_id"]) if pd.notna(r.get("function_id")) else None
                employee_dict[employee_id] = {
                    "name": f"{str(r['firstname']).strip()} {str(r['lastname']).strip()}".strip(),
                    "function_id": function_id,
                    "occupation_percentage": (
                        float(r["occupation_percentage"])
                        if pd.notna(r.get("occupation_percentage"))
                        else 100.0
                    ),
                }
                if function_id is not None:
                    employees_by_function.setdefault(function_id, []).append(employee_id)

        # Separate direct function mappings and team mappings
        direct_employee_mappings: Dict[int, float] = {}
        direct_function_mappings: Dict[int, float] = {}
        team_mappings: Dict[int, float] = {}

        if not df_mappings.empty:
            for _, m in df_mappings.iterrows():
                m_type = str(m["target_type"]).strip().lower()
                m_tid = int(m["target_id"])
                m_pct = float(m["allocation_pct"])
                if m_type == "employee":
                    direct_employee_mappings[m_tid] = m_pct
                elif m_type == "function":
                    direct_function_mappings[m_tid] = m_pct
                elif m_type == "team":
                    team_mappings[m_tid] = m_pct

        # Resource keys are (type, ID). Employees are the normal capacity unit;
        # legacy functions are used only when no employee occupies that function.
        ResourceKey = Tuple[str, int]
        team_derived_resources: Dict[ResourceKey, Tuple[int, str, float]] = {}
        team_resource_occurrences: Dict[ResourceKey, int] = {}
        for t_id, t_pct in team_mappings.items():
            t_info = team_dict.get(t_id, {"name": f"Team #{t_id}"})
            t_name = t_info["name"]

            # Get explicit team functions from repository
            member_fids = pool_repo.get_team_functions(t_id)

            # Include manager and leader if defined
            mgr_fid = t_info.get("manager_function_id")
            if mgr_fid is not None:
                member_fids.append(mgr_fid)
            ldr_fid = t_info.get("leader_function_id")
            if ldr_fid is not None:
                member_fids.append(ldr_fid)

            # Fallback: if no explicit member functions, include functions reporting to manager
            if len(member_fids) <= 2 and mgr_fid is not None:
                for fid, f_data in func_dict.items():
                    if f_data.get("manager_function_id") == mgr_fid:
                        member_fids.append(fid)

            for fid in set(member_fids):
                if fid in func_dict:
                    employee_ids = employees_by_function.get(fid, [])
                    resource_keys: List[ResourceKey] = (
                        [("employee", eid) for eid in employee_ids]
                        if employee_ids
                        else [("function", fid)]
                    )
                    for resource_key in resource_keys:
                        team_resource_occurrences[resource_key] = team_resource_occurrences.get(resource_key, 0) + 1
                        previous = team_derived_resources.get(resource_key)
                        if previous is None or t_pct > previous[2]:
                            team_derived_resources[resource_key] = (t_id, t_name, t_pct)

        direct_resources: Dict[ResourceKey, Tuple[float, str]] = {}
        direct_resource_occurrences: Dict[ResourceKey, int] = {}

        # Legacy direct function mappings resolve to their occupying employees.
        for fid, allocation_pct in direct_function_mappings.items():
            employee_ids = employees_by_function.get(fid, [])
            resource_keys = (
                [("employee", eid) for eid in employee_ids]
                if employee_ids
                else [("function", fid)]
            )
            for resource_key in resource_keys:
                direct_resource_occurrences[resource_key] = direct_resource_occurrences.get(resource_key, 0) + 1
                direct_resources[resource_key] = (allocation_pct, "Direct Function Mapping")

        # An explicit employee mapping is the most specific source and overrides
        # both team-derived and legacy function-derived allocation percentages.
        for employee_id, allocation_pct in direct_employee_mappings.items():
            if employee_id not in employee_dict:
                continue
            resource_key = ("employee", employee_id)
            direct_resource_occurrences[resource_key] = direct_resource_occurrences.get(resource_key, 0) + 1
            direct_resources[resource_key] = (allocation_pct, "Direct Employee Mapping")

        # 2. Build the unique contributing-resource list.
        contributions: List[PoolFunctionContribution] = []
        all_resource_keys = set(direct_resources).union(team_derived_resources)
        assigned_capacity_fte = 0.0

        for resource_type, resource_id in sorted(all_resource_keys):
            resource_key = (resource_type, resource_id)
            is_direct = resource_key in direct_resources
            is_team = resource_key in team_derived_resources
            is_dedup = (
                (is_direct and is_team)
                or direct_resource_occurrences.get(resource_key, 0) > 1
                or team_resource_occurrences.get(resource_key, 0) > 1
            )

            if resource_type == "employee":
                employee_info = employee_dict.get(resource_id)
                if employee_info is None:
                    continue
                employee_id: Optional[int] = resource_id
                employee_name: Optional[str] = employee_info["name"]
                function_id = employee_info["function_id"] or 0
                function_name = func_dict.get(function_id, {}).get("name", "Unassigned function")
                nominal_fte = employee_info["occupation_percentage"] / 100.0
            else:
                function_info = func_dict.get(resource_id)
                if function_info is None:
                    continue
                employee_id = None
                employee_name = None
                function_id = resource_id
                function_name = function_info["name"]
                nominal_fte = function_info["fte_percentage"] / 100.0

            if is_direct:
                effective_pct, direct_source_name = direct_resources[resource_key]
                src_type = "direct"
                src_name = direct_source_name
            else:
                _, t_name, t_pct = team_derived_resources[resource_key]
                effective_pct = t_pct
                src_type = "team"
                src_name = t_name

            effective_fte = round(nominal_fte * (effective_pct / 100.0), 3)
            assigned_capacity_fte += effective_fte

            contributions.append(
                PoolFunctionContribution(
                    function_id=function_id,
                    function_name=function_name,
                    nominal_fte=nominal_fte,
                    effective_allocation_pct=effective_pct,
                    effective_fte=effective_fte,
                    source_type=src_type,
                    source_name=src_name,
                    is_deduplicated=is_dedup,
                    employee_id=employee_id,
                    employee_name=employee_name,
                    resource_type=resource_type,
                )
            )

        assigned_capacity_fte = round(assigned_capacity_fte, 3)
        defined_capacity_fte = pool.capacity_fte if pool else None
        total_capacity_fte = (
            round(float(defined_capacity_fte), 3)
            if defined_capacity_fte is not None
            else assigned_capacity_fte
        )

        # 3. Fetch Assignments & Analyze Daily Overassignments
        df_assign = pool_repo.get_assignments(pool_id=pool_id)
        assignments_payload: List[Dict[str, Any]] = []

        # Map: date_str (YYYY-MM-DD) -> daily_assigned_fte
        daily_usage: Dict[str, float] = {}
        total_scalar_assigned = 0.0

        # Pre-fetch project bounds if needed
        proj_bounds: Dict[int, Tuple[str, str]] = {}
        if milestone_repo is not None:
            proj_bounds = milestone_repo.get_all_project_date_bounds()

        if not df_assign.empty:
            for _, a in df_assign.iterrows():
                a_id = int(a["id"])
                p_id = int(a["project_id"])
                p_name = str(a.get("project_name", f"Project #{p_id}"))
                t_id = int(a["task_id"]) if pd.notna(a.get("task_id")) else None
                t_name = str(a.get("task_name", "—")) if pd.notna(a.get("task_name")) else "— Project Level"
                fte = float(a["fte_assigned"])
                total_scalar_assigned += fte

                c_start = str(a["custom_start_date"]) if pd.notna(a.get("custom_start_date")) else None
                c_end = str(a["custom_end_date"]) if pd.notna(a.get("custom_end_date")) else None

                t_start = str(a["task_start_date"]) if pd.notna(a.get("task_start_date")) else None
                t_end = str(a["task_end_date"]) if pd.notna(a.get("task_end_date")) else None

                # Determine effective date range
                eff_start = c_start or t_start
                eff_end = c_end or t_end

                if not eff_start or not eff_end:
                    # Fallback to project date bounds
                    b_tuple = proj_bounds.get(p_id) or proj_bounds.get(str(p_id))
                    if b_tuple and b_tuple[0] and b_tuple[1]:
                        eff_start = eff_start or b_tuple[0]
                        eff_end = eff_end or b_tuple[1]
                    else:
                        today_str = datetime.date.today().isoformat()
                        eff_start = eff_start or today_str
                        eff_end = eff_end or today_str

                assignments_payload.append({
                    "id": a_id,
                    "project_id": p_id,
                    "project_name": p_name,
                    "task_id": t_id,
                    "task_name": t_name,
                    "fte_assigned": fte,
                    "start_date": eff_start,
                    "end_date": eff_end,
                    "is_custom_period": bool(c_start or c_end),
                    "notes": str(a.get("notes", "")),
                })

        # 4. Deduplicate Project-Level and Task-Level Assignments per Project
        # Map: project_id -> { date -> fte } for project level
        project_level_usage: Dict[int, Dict[str, float]] = {}
        # Map: project_id -> { date -> fte } for task level
        task_level_usage: Dict[int, Dict[str, float]] = {}

        for a in assignments_payload:
            p_id = int(a["project_id"])
            t_id = a["task_id"]
            s_date = a["start_date"]
            e_date = a["end_date"]
            fte_val = float(a["fte_assigned"])

            if t_id is None:
                p_map = project_level_usage.setdefault(p_id, {})
                cls._accumulate_daily_usage(p_map, s_date, e_date, fte_val)
            else:
                t_map = task_level_usage.setdefault(p_id, {})
                cls._accumulate_daily_usage(t_map, s_date, e_date, fte_val)

        # Build deduplicated daily usage across all projects:
        # On each date: demand = max(f_proj, f_task)
        all_pids = set(project_level_usage.keys()).union(set(task_level_usage.keys()))
        all_dates: Set[str] = set()
        for p_id in all_pids:
            all_dates.update(project_level_usage.get(p_id, {}).keys())
            all_dates.update(task_level_usage.get(p_id, {}).keys())

        daily_usage: Dict[str, float] = {}
        for d_str in sorted(all_dates):
            day_total = 0.0
            for p_id in all_pids:
                f_proj = project_level_usage.get(p_id, {}).get(d_str, 0.0)
                f_task = task_level_usage.get(p_id, {}).get(d_str, 0.0)
                day_total += max(f_proj, f_task)
            daily_usage[d_str] = round(day_total, 3)

        # Deduplicated scalar total: for each project, max of project-level scalar and task-level scalar
        total_scalar_assigned = 0.0
        for p_id in all_pids:
            p_scalar = sum(
                a["fte_assigned"]
                for a in assignments_payload
                if int(a["project_id"]) == p_id and a["task_id"] is None
            )
            t_scalar = sum(
                a["fte_assigned"]
                for a in assignments_payload
                if int(a["project_id"]) == p_id and a["task_id"] is not None
            )
            total_scalar_assigned += max(p_scalar, t_scalar)

        # 5. Evaluate Daily Overassignments and Peak Usage
        peak_assigned_fte = 0.0
        daily_overassignments: List[DailyOverassignment] = []

        if daily_usage:
            peak_assigned_fte = round(max(daily_usage.values()), 3)

            for d_str in sorted(daily_usage.keys()):
                d_fte = round(daily_usage[d_str], 3)
                if d_fte > (total_capacity_fte + 1e-4):
                    daily_overassignments.append(
                        DailyOverassignment(
                            date=d_str,
                            capacity_fte=total_capacity_fte,
                            assigned_fte=d_fte,
                            excess_fte=round(d_fte - total_capacity_fte, 3),
                        )
                    )

        is_overassigned = peak_assigned_fte > (total_capacity_fte + 1e-4)
        peak_excess = round(peak_assigned_fte - total_capacity_fte, 3) if is_overassigned else 0.0

        # Group daily overassignments into human-readable intervals
        overassignment_intervals = cls._group_date_intervals(daily_overassignments)

        return PoolCapacityDetail(
            pool_id=pool_id,
            pool_name=pool_name,
            total_capacity_fte=total_capacity_fte,
            peak_assigned_fte=peak_assigned_fte,
            total_assigned_fte_scalar=round(total_scalar_assigned, 3),
            is_overassigned=is_overassigned,
            peak_excess_fte=peak_excess,
            contributing_functions=contributions,
            assignments=assignments_payload,
            daily_overassignments=daily_overassignments,
            overassignment_intervals=overassignment_intervals,
            daily_usage=daily_usage,
            defined_capacity_fte=defined_capacity_fte,
            assigned_capacity_fte=assigned_capacity_fte,
        )

    @classmethod
    def calculate_project_pool_status(
        cls,
        project_id: int,
        pool_id: int,
        org_repo: OrganizationRepository,
        pool_repo: ResourcePoolRepository,
        milestone_repo: Optional[MilestoneRepository] = None,
    ) -> Dict[str, Any]:
        """Evaluates whether a specific project overassigns a given resource pool on a daily basis.

        Deduplicates project-level and task-level assignments on that project:
        daily_demand = max(project_level_fte, sum_of_task_level_fte).

        Args:
            project_id: Project ID.
            pool_id: Resource pool ID.
            org_repo: Organization repository.
            pool_repo: Resource pool repository.
            milestone_repo: Optional milestone repository.

        Returns:
            Dict[str, Any]: Status summary including pool capacity, project peak assigned, and overassignment.
        """
        pool_detail = cls.calculate_pool_capacity(pool_id, org_repo, pool_repo, milestone_repo)

        # Filter assignments strictly belonging to this project
        project_assignments = [a for a in pool_detail.assignments if int(a["project_id"]) == project_id]

        proj_daily: Dict[str, float] = {}
        task_daily: Dict[str, float] = {}
        for a in project_assignments:
            if a["task_id"] is None:
                cls._accumulate_daily_usage(proj_daily, a["start_date"], a["end_date"], a["fte_assigned"])
            else:
                cls._accumulate_daily_usage(task_daily, a["start_date"], a["end_date"], a["fte_assigned"])

        all_proj_dates = set(proj_daily.keys()).union(set(task_daily.keys()))
        daily_project_usage: Dict[str, float] = {}
        for d in sorted(all_proj_dates):
            daily_project_usage[d] = round(max(proj_daily.get(d, 0.0), task_daily.get(d, 0.0)), 3)

        project_peak_assigned = round(max(daily_project_usage.values()), 3) if daily_project_usage else 0.0
        is_project_overassigned = project_peak_assigned > (pool_detail.total_capacity_fte + 1e-4)
        project_excess = round(project_peak_assigned - pool_detail.total_capacity_fte, 3) if is_project_overassigned else 0.0

        return {
            "pool_id": pool_id,
            "pool_name": pool_detail.pool_name,
            "pool_capacity_fte": pool_detail.total_capacity_fte,
            "project_peak_assigned_fte": project_peak_assigned,
            "is_overassigned": is_project_overassigned,
            "excess_fte": project_excess,
            "assignments_count": len(project_assignments),
        }

    @classmethod
    def get_portfolio_pools_summary(
        cls,
        org_repo: OrganizationRepository,
        pool_repo: ResourcePoolRepository,
        milestone_repo: Optional[MilestoneRepository] = None,
    ) -> List[PoolCapacityDetail]:
        """Calculates capacity and daily overassignment status for all pools in the portfolio.

        Args:
            org_repo: Organization repository.
            pool_repo: Resource pool repository.
            milestone_repo: Optional milestone repository.

        Returns:
            List[PoolCapacityDetail]: Overview list for each resource pool.
        """
        df_pools = pool_repo.get_all_pools()
        if df_pools.empty:
            return []

        summaries: List[PoolCapacityDetail] = []
        for _, row in df_pools.iterrows():
            pid = int(row["id"])
            detail = cls.calculate_pool_capacity(pid, org_repo, pool_repo, milestone_repo)
            summaries.append(detail)

        return summaries

    # =========================================================================
    # Internal Helpers
    # =========================================================================
    @staticmethod
    def _accumulate_daily_usage(
        daily_map: Dict[str, float],
        start_str: str,
        end_str: str,
        fte: float,
    ) -> None:
        """Accumulates FTE into daily map for each calendar date between start and end inclusive.

        Args:
            daily_map: Dictionary mapping YYYY-MM-DD to cumulative FTE.
            start_str: Start date string (YYYY-MM-DD).
            end_str: End date string (YYYY-MM-DD).
            fte: FTE amount to add.
        """
        try:
            d_start = datetime.date.fromisoformat(start_str.strip()[:10])
            d_end = datetime.date.fromisoformat(end_str.strip()[:10])
        except (ValueError, TypeError):
            return

        if d_end < d_start:
            d_end = d_start

        # Cap span to 25 years max for memory and boundary safety
        curr = d_start
        delta = datetime.timedelta(days=1)
        max_days = 365 * 25
        count = 0
        while curr <= d_end and count < max_days:
            k = curr.isoformat()
            daily_map[k] = daily_map.get(k, 0.0) + fte
            curr += delta
            count += 1

    @staticmethod
    def _group_date_intervals(daily_overassignments: List[DailyOverassignment]) -> List[str]:
        """Groups consecutive daily overassignment records into human-readable interval strings.

        Args:
            daily_overassignments: List of DailyOverassignment instances.

        Returns:
            List[str]: Formatted interval strings (e.g. '2026-02-16 to 2026-03-01 (+1.50 FTE)').
        """
        if not daily_overassignments:
            return []

        intervals: List[str] = []
        start_d = daily_overassignments[0].date
        prev_d = start_d
        max_excess = daily_overassignments[0].excess_fte

        delta = datetime.timedelta(days=1)

        for rec in daily_overassignments[1:]:
            try:
                curr_date = datetime.date.fromisoformat(rec.date)
                prev_date = datetime.date.fromisoformat(prev_d)
            except ValueError:
                continue

            if curr_date == prev_date + delta:
                prev_d = rec.date
                max_excess = max(max_excess, rec.excess_fte)
            else:
                if start_d == prev_d:
                    intervals.append(f"{start_d} (+{max_excess:.2f} FTE)")
                else:
                    intervals.append(f"{start_d} to {prev_d} (+{max_excess:.2f} FTE)")
                start_d = rec.date
                prev_d = rec.date
                max_excess = rec.excess_fte

        if start_d == prev_d:
            intervals.append(f"{start_d} (+{max_excess:.2f} FTE)")
        else:
            intervals.append(f"{start_d} to {prev_d} (+{max_excess:.2f} FTE)")

        return intervals

    @classmethod
    def calculate_pool_scope_daily_usage(
        cls,
        assignments: List[Dict[str, Any]],
        project_ids: List[Union[int, str]],
    ) -> Dict[str, float]:
        """Calculates deduplicated daily usage for a pool restricted to a given list of project IDs.

        Args:
            assignments: List of assignment dicts with project_id, task_id, start_date, end_date, fte_assigned.
            project_ids: Filter list of project IDs.

        Returns:
            Dict[str, float]: Deduplicated daily usage mapping date_str -> fte.
        """
        pids_set = {int(p) for p in project_ids if str(p).isdigit()}
        if not pids_set:
            return {}

        project_level_usage: Dict[int, Dict[str, float]] = {}
        task_level_usage: Dict[int, Dict[str, float]] = {}

        for a in assignments:
            p_id = int(a["project_id"])
            if p_id not in pids_set:
                continue
            t_id = a.get("task_id")
            s_date = a["start_date"]
            e_date = a["end_date"]
            fte_val = float(a["fte_assigned"])

            if t_id is None:
                p_map = project_level_usage.setdefault(p_id, {})
                cls._accumulate_daily_usage(p_map, s_date, e_date, fte_val)
            else:
                t_map = task_level_usage.setdefault(p_id, {})
                cls._accumulate_daily_usage(t_map, s_date, e_date, fte_val)

        all_pids = set(project_level_usage.keys()).union(set(task_level_usage.keys()))
        all_dates: Set[str] = set()
        for p_id in all_pids:
            all_dates.update(project_level_usage.get(p_id, {}).keys())
            all_dates.update(task_level_usage.get(p_id, {}).keys())

        daily_usage: Dict[str, float] = {}
        for d_str in sorted(all_dates):
            day_total = 0.0
            for p_id in all_pids:
                f_proj = project_level_usage.get(p_id, {}).get(d_str, 0.0)
                f_task = task_level_usage.get(p_id, {}).get(d_str, 0.0)
                day_total += max(f_proj, f_task)
            daily_usage[d_str] = round(day_total, 3)

        return daily_usage

    @staticmethod
    def get_projects_consuming_pool_in_period(
        assignments: List[Dict[str, Any]],
        start_date: str,
        end_date: str,
    ) -> List[int]:
        """Identifies all project IDs that consume a pool during a specified date range.

        Args:
            assignments: List of pool assignment records.
            start_date: Period start date (YYYY-MM-DD).
            end_date: Period end date (YYYY-MM-DD).

        Returns:
            List[int]: Unique sorted list of project IDs consuming the pool in that period.
        """
        matching_pids: Set[int] = set()
        s_date = str(start_date).strip()[:10]
        e_date = str(end_date).strip()[:10]
        if not s_date or not e_date:
            return []

        for a in assignments:
            a_start = str(a.get("start_date", "")).strip()[:10]
            a_end = str(a.get("end_date", "")).strip()[:10]
            if not a_start or not a_end:
                continue
            if float(a.get("fte_assigned", 0.0)) <= 0:
                continue
            p_id = int(a["project_id"])
            # Overlap condition: a_start <= e_date and a_end >= s_date
            if a_start <= e_date and a_end >= s_date:
                matching_pids.add(p_id)

        return sorted(list(matching_pids))
