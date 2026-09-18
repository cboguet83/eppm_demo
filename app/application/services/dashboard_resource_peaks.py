"""Individual quarterly pool peaks, independent of the portfolio peak date."""

from copy import deepcopy

from app.application.ports.dashboard import PoolResourceSeries
from app.domain.dashboard import quarter_bounds


def individual_pool_peaks(pools: list[PoolResourceSeries], days: list[list],
                          staffing: list[list], year: int) -> list[PoolResourceSeries]:
    """Reduce aggregate-only database rows; no project or employee records enter here.

    The JSON boundary carries heterogeneous arrays: pool ID, ISO day, demand and
    capacity, or pool ID, nominal capacity and a sparse daily capacity calendar.
    Earliest dates win equal peaks. Displayed capacities use the period minimum,
    retaining inclusive calendar overrides and baseline days without overrides.
    """
    result = {pool['pool_id']: deepcopy(pool) for pool in pools}
    for pool in result.values():
        for metric in ('allocation', 'overallocation', 'available'):
            pool[metric] = dict.fromkeys(pool[metric], 0.0)
    for identity, day, demand, capacity in days:
        pool = result[identity]
        quarter = f'{day[:4]}-Q{(int(day[5:7])-1)//3+1}'
        demand, capacity = round(float(demand), 3), round(float(capacity), 3)
        if demand > pool['allocation'][quarter]:
            pool['allocation'][quarter] = demand
            pool['available'][quarter] = round(capacity - demand, 3)
        pool['overallocation'][quarter] = max(pool['overallocation'][quarter], round(demand-capacity, 3), 0)
    for identity, base, calendar in staffing:
        pool = result[identity]
        pool['capacity'] = {}
        for quarter in pool['allocation']:
            first, last = quarter_bounds(quarter, year)
            values = [float(value) for day, value in calendar.items() if first.isoformat() <= day <= last.isoformat()]
            if len(values) < (last-first).days + 1:
                values.append(float(base))
            pool['capacity'][quarter] = round(min(values, default=float(base)), 3)
    return list(result.values())
