"""Weighted function memberships with employee deduplication inside each pool."""

from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.models import PoolResourceContribution


def contributions(inputs: CapacityInputs) -> list[PoolResourceContribution]:
    """Add direct shares to indirect shares of globally remaining capacity."""
    if inputs.pool is not None and inputs.pool.deleted_flag:
        return []
    functions = {item.function_id: item for item in inputs.functions if not item.deleted_flag}
    teams = {item.team_id: item for item in inputs.teams if not item.deleted_flag}
    # Keep one mapping per function: direct function mappings override team paths.
    mapped: dict[int, tuple[float, str, str, int]] = {}
    occurrences: dict[int, int] = {}
    for kind in ('team', 'function'):
        for mapping in inputs.mappings:
            if mapping.target_type != kind:
                continue
            if kind == 'team' and mapping.target_id not in teams:
                continue
            ids = inputs.team_functions.get(mapping.target_id, []) if kind == 'team' else [mapping.target_id]
            for identity in set(ids) & functions.keys():
                occurrences[identity] = occurrences.get(identity, 0) + 1
                current = mapped.get(identity)
                if kind == 'function' or current is None or mapping.allocation_pct > current[0]:
                    mapped[identity] = (mapping.allocation_pct,
                        teams[mapping.target_id].team_name if kind == 'team' else 'Direct Function Mapping',
                        'team' if kind == 'team' else 'direct', mapping.id or 0)
    direct = {item.target_id: item.allocation_pct for item in inputs.mappings if item.target_type == 'employee'}
    totals = inputs.direct_employee_totals if inputs.direct_employee_totals is not None else direct
    result = []
    occupied: set[int] = set()
    for person in inputs.employees:
        if person.deleted_flag:
            continue
        shares = {row.function_id: row.allocation_pct for row in person.assignments() if row.function_id in functions}
        occupied.update(shares)
        selected = shares.keys() & mapped.keys()
        if not selected and person.employee_id not in direct:
            continue
        remaining = max(0, 100 - totals.get(person.employee_id, 0)) / 100
        percent = remaining * sum(shares[identity] * mapped[identity][0] / 100 for identity in selected)
        source = ', '.join(sorted({mapped[identity][1] for identity in selected}))
        source_type = 'direct' if any(mapped[identity][2] == 'direct' for identity in selected) else 'team'
        if person.employee_id in direct:
            percent += direct[person.employee_id]
            source = 'Direct Employee Mapping' + (f'; remaining capacity via {source}' if selected else '')
            source_type = 'direct'
        labels = selected or shares.keys()
        nominal = person.occupation_percentage / 100
        result.append(PoolResourceContribution(
            function_id=next(iter(labels)) if len(labels) == 1 else 0,
            function_name=', '.join(sorted(functions[identity].name for identity in labels)) or 'Unassigned function',
            nominal_fte=nominal, effective_allocation_pct=percent, effective_fte=round(nominal * (percent / 100), 3),
            source_type=source_type, source_name=source,
            is_deduplicated=(bool(selected) and person.employee_id in direct)
                or any(occurrences[identity] > 1 for identity in selected),
            employee_id=person.employee_id, employee_name=f'{person.firstname.strip()} {person.lastname.strip()}'.strip(),
            resource_type='employee'))
    for identity, (percent, source, kind, _) in mapped.items():
        if identity not in occupied and kind == 'direct':
            function = functions[identity]
            nominal = (function.fte_percentage if function.fte_percentage is not None else 100) / 100
            result.append(PoolResourceContribution(identity, function.name, nominal, percent,
                round(nominal * (percent / 100), 3), kind, source, occurrences[identity] > 1))
    return sorted(result, key=lambda item: (item.resource_type, item.resource_id))
