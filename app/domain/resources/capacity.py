"""Pure capacity calculation with explicit source records and effective date."""

from datetime import date
from decimal import Decimal

from app.domain.resources.inputs import CapacityInputs, CapacityStaffing
from app.domain.resources.models import (
    CapacityAssignment,
    PoolCapacityDetail,
    PoolResourceContribution,
)
from app.domain.resources.scheduling import relative_period
from app.domain.resources.timeline import demand_timeline
from app.domain.resources.capacity_rules import (
    accumulate_daily_usage,
    calculate_daily_overassignments,
    group_date_intervals,
)

type ResourceKey = tuple[str, int]
type ResourceSource = tuple[str, float]


def _team_resources(
    inputs: CapacityInputs,
    occupants: dict[int, list[int]],
) -> tuple[dict[ResourceKey, ResourceSource], dict[ResourceKey, int]]:
    """Resolve only explicit function/team memberships without I/O."""
    functions = {function.function_id: function for function in inputs.functions}
    teams = {team.team_id: team for team in inputs.teams}
    resources: dict[ResourceKey, ResourceSource] = {}
    occurrences: dict[ResourceKey, int] = {}
    for mapping in inputs.mappings:
        if mapping.target_type != "team":
            continue
        team = teams.get(mapping.target_id)
        members = list(inputs.team_functions.get(mapping.target_id, []))
        name = team.team_name if team else f"Team #{mapping.target_id}"
        for fid in set(members) & functions.keys():
            keys = [("employee", eid) for eid in occupants.get(fid, [])] or [("function", fid)]
            for key in keys:
                occurrences[key] = occurrences.get(key, 0) + 1
                if key not in resources or mapping.allocation_pct > resources[key][1]:
                    resources[key] = (name, mapping.allocation_pct)
    return resources, occurrences


def _direct_resources(
    inputs: CapacityInputs,
    occupants: dict[int, list[int]],
) -> tuple[dict[ResourceKey, ResourceSource], dict[ResourceKey, int]]:
    """Apply employee mappings after function mappings to preserve precedence."""
    resources: dict[ResourceKey, ResourceSource] = {}
    occurrences: dict[ResourceKey, int] = {}
    employees = {employee.employee_id for employee in inputs.employees}
    for kind in ("function", "employee"):
        for mapping in inputs.mappings:
            if mapping.target_type != kind:
                continue
            if kind == "employee" and mapping.target_id not in employees:
                continue
            keys = [(kind, mapping.target_id)]
            if kind == "function" and occupants.get(mapping.target_id):
                keys = [("employee", eid) for eid in occupants[mapping.target_id]]
            for key in keys:
                occurrences[key] = occurrences.get(key, 0) + 1
                resources[key] = (f"Direct {kind.title()} Mapping", mapping.allocation_pct)
    return resources, occurrences


def resource_contributions(inputs: CapacityInputs) -> list[PoolResourceContribution]:
    """Count each employee once, falling back to vacant legacy functions."""
    functions = {function.function_id: function for function in inputs.functions}
    employees = {employee.employee_id: employee for employee in inputs.employees}
    occupants: dict[int, list[int]] = {}
    for employee in inputs.employees:
        if employee.function_id is not None:
            occupants.setdefault(employee.function_id, []).append(employee.employee_id)
    teams, team_counts = _team_resources(inputs, occupants)
    direct, direct_counts = _direct_resources(inputs, occupants)
    result: list[PoolResourceContribution] = []
    for kind, identity in sorted(teams.keys() | direct.keys()):
        key = (kind, identity)
        employee = employees.get(identity) if kind == "employee" else None
        function_id = (employee.function_id or 0) if employee else identity
        function = functions.get(function_id)
        if employee is None and function is None:
            continue
        percentage = employee.occupation_percentage if employee else function.fte_percentage
        nominal = (percentage if percentage is not None else 100.0) / 100.0
        source, allocation = direct[key] if key in direct else teams[key]
        result.append(
            PoolResourceContribution(
                function_id=function_id,
                function_name=function.name if function else "Unassigned function",
                nominal_fte=nominal,
                effective_allocation_pct=allocation,
                effective_fte=round(nominal * (allocation / 100.0), 3),
                source_type="direct" if key in direct else "team",
                source_name=source,
                is_deduplicated=(key in direct and key in teams)
                or direct_counts.get(key, 0) > 1
                or team_counts.get(key, 0) > 1,
                employee_id=employee.employee_id if employee else None,
                employee_name=(
                    f"{employee.firstname.strip()} {employee.lastname.strip()}".strip()
                    if employee
                    else None
                ),
                resource_type=kind,
            )
        )
    return result


def _calendar_capacity(
    inputs: CapacityInputs,
    contributions: list[PoolResourceContribution],
    base: float,
) -> dict[str, float]:
    """Apply inclusive employee overrides as sparse changes to normal capacity."""
    by_employee = {
        item.employee_id: item for item in contributions if item.employee_id is not None
    }
    employees = {employee.employee_id: employee for employee in inputs.employees}
    deltas: dict[str, float] = {}
    for exception in inputs.exceptions:
        contribution = by_employee.get(exception.employee_id)
        employee = employees.get(exception.employee_id)
        if contribution is None or employee is None:
            continue
        change = (
            (exception.occupation_percentage - employee.occupation_percentage)
            / 100.0
            * (contribution.effective_allocation_pct / 100.0)
        )
        accumulate_daily_usage(
            deltas, exception.start_date.isoformat(), exception.end_date.isoformat(), change
        )
    return {day: round(base + delta, 3) for day, delta in deltas.items()}


def resolve_assignments(inputs: CapacityInputs, today: date) -> list[CapacityAssignment]:
    """Resolve custom, task, project, and finally today's dates in that order."""
    result: list[CapacityAssignment] = []
    for row in inputs.assignments:
        pid, tid = int(row["project_id"]), row.get("task_id")
        start = row.get("custom_start_date") or row.get("task_start_date")
        end = row.get("custom_end_date") or row.get("task_end_date")
        bounds = inputs.project_bounds.get(pid)
        if not start or not end:
            if bounds and bounds[0] and bounds[1]:
                start, end = start or bounds[0], end or bounds[1]
            else:
                start, end = start or today.isoformat(), end or today.isoformat()
        if row.get("schedule_anchor"):
            start, end = relative_period(
                start, end, row["schedule_anchor"], row["offset_days"], row["duration_days"],
            )
        result.append(
            CapacityAssignment(
                id=int(row["id"]),
                project_id=pid,
                project_name=row.get("project_name", f"Project #{pid}"),
                task_id=int(tid) if tid is not None else None,
                task_name=(
                    row["task_name"] if row.get("task_name") is not None else "— Project Level"
                ),
                fte_assigned=float(row["fte_assigned"]),
                start_date=start,
                end_date=end,
                is_custom_period=bool(row.get("custom_start_date") or row.get("custom_end_date")),
                notes=str(row.get("notes", "")),
            )
        )
        if row.get("schedule_anchor"):
            result[-1].update(schedule_anchor=row["schedule_anchor"],
                              offset_days=row["offset_days"], duration_days=row["duration_days"])
    return result


def calculate_staffing(inputs: CapacityInputs) -> CapacityStaffing:
    """Aggregate explicit staffing inputs with the established rounding order."""
    contributions = resource_contributions(inputs)
    assigned = 0.0
    for contribution in contributions:
        assigned += contribution.effective_fte
    assigned = round(assigned, 3)
    return CapacityStaffing(
        assigned, bool(contributions), _calendar_capacity(inputs, contributions, assigned), contributions,
    )


def calculate_capacity(inputs: CapacityInputs, today: date) -> PoolCapacityDetail:
    """Combine staffing aggregates and scoped demand without storage or UI.

    A reader can supply safe pool-level staffing without disclosing employee
    records. Explicit domain snapshots retain the same pure staffing calculation.
    Person details do not determine whether assigned capacity takes precedence.
    """
    staffing = inputs.staffing if inputs.staffing is not None else calculate_staffing(inputs)
    assigned = staffing.assigned_capacity_fte
    daily_capacity = staffing.daily_assigned_capacity
    defined = inputs.pool.capacity_fte if inputs.pool else None
    theoretical = round(float(defined), 3) if defined is not None else assigned
    effective = assigned if staffing.has_assigned_resources else theoretical
    effective_calendar = dict(daily_capacity) if staffing.has_assigned_resources else {}
    reductions: dict[str, Decimal] = {}
    for exception in inputs.capacity_exceptions:
        first, last = date.fromisoformat(exception.start_date), date.fromisoformat(exception.end_date)
        for ordinal in range(first.toordinal(), last.toordinal() + 1):
            day = date.fromordinal(ordinal).isoformat()
            reductions[day] = reductions.get(day, Decimal(0)) + Decimal(str(exception.reduction_fte))
    for day, reduction in reductions.items():
        effective_calendar[day] = round(max(0.0, float(Decimal(str(effective_calendar.get(day, effective))) - reduction)), 3)
    assignments = resolve_assignments(inputs, today)
    daily_usage = demand_timeline(assignments)
    scalar: dict[int, list[float]] = {}
    for assignment in assignments:
        values = scalar.setdefault(assignment["project_id"], [0.0, 0.0])
        values[int(assignment["task_id"] is not None)] += assignment["fte_assigned"]
    overassignments = calculate_daily_overassignments(
        daily_usage,
        effective,
        effective_calendar,
    )
    return PoolCapacityDetail(
        pool_id=inputs.pool_id,
        pool_name=inputs.pool.name if inputs.pool else f"Pool #{inputs.pool_id}",
        total_capacity_fte=theoretical,
        assigned_capacity_fte=assigned,
        defined_capacity_fte=defined,
        effective_capacity_fte=effective,
        has_assigned_resources=staffing.has_assigned_resources,
        contributing_resources=staffing.contributing_resources,
        daily_assigned_capacity=daily_capacity,
        daily_effective_capacity=effective_calendar,
        assignments=assignments,
        daily_usage=daily_usage,
        peak_assigned_fte=round(max(daily_usage.values(), default=0.0), 3),
        total_assigned_fte_scalar=round(sum(max(values) for values in scalar.values()), 3),
        is_overassigned=bool(overassignments),
        daily_overassignments=overassignments,
        peak_excess_fte=round(max((item.excess_fte for item in overassignments), default=0.0), 3),
        overassignment_intervals=group_date_intervals(overassignments),
    )
