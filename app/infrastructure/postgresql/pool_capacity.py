"""Batched native capacity snapshots with database-enforced staffing privacy."""

from dataclasses import replace

from app.application.services.business_access import BusinessAccess
from app.domain.resources.inputs import CapacityInputs, CapacityStaffing
from app.domain.resources.models import PoolCapacityDetail, PoolResourceContribution, ResourcePool
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolGateway, PostgresResourcePoolStore


class PostgresCapacityReader:
    """Read safe staffing aggregates and scoped demand in one native snapshot."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the restricted pool and trusted current actor without opening I/O."""
        self._gateway = PostgresResourcePoolGateway(database, key, access=access)

    def read(self, pool_ids: list[int]) -> dict[int, CapacityInputs]:
        """Read only the requested pool inputs under repeatable-read isolation."""
        pool_ids = list(pool_ids)
        return self._gateway.run(lambda store: read_capacity_inputs(store, pool_ids))

    def visible_details(self, details: list[PoolCapacityDetail]) -> list[PoolCapacityDetail]:
        """Recheck access before returning any individual staffing contributions."""
        def operation(store: PostgresResourcePoolStore) -> list[PoolCapacityDetail]:
            shared = store.connection.execute("SELECT eppm.has_global_permission('business.manage')").fetchone()[0]
            return details if shared else [replace(detail, contributing_resources=[]) for detail in details]
        return self._gateway.run(operation)


def read_capacity_inputs(store: PostgresResourcePoolStore, pool_ids: list[int]) -> dict[int, CapacityInputs]:
    """Collect safe staffing and visible demand on an already authorized connection.

    The bounded staffing function supplies aggregates to project readers and
    individual contributions only to shared administrators. Raw employee and
    calendar records never cross this adapter boundary, including for admins.
    """
    pools = {
        identity: ResourcePool(name, id=identity, capacity_fte=capacity, pool_type_id=pool_type_id)
        for identity, name, capacity, pool_type_id in store.connection.execute(
            'SELECT id,name,capacity_fte,pool_type_id FROM eppm.resource_pool WHERE id=ANY(%s::bigint[])', (pool_ids,),
        )
    }
    inputs = {
        pool_id: CapacityInputs(pool_id, pool=pools.get(pool_id), staffing=CapacityStaffing())
        for pool_id in pool_ids
    }
    for identity, assigned, has_resources, days, people in store.connection.execute(
        'SELECT * FROM eppm.pool_staffing(%s::bigint[])', (pool_ids,),
    ):
        inputs[identity].staffing = CapacityStaffing(
            assigned, has_resources, days, [PoolResourceContribution(**row) for row in people],
        )
    assignments = store.get_assignments(pool_ids=pool_ids)
    for exception in store.capacity_exceptions(pool_ids):
        inputs[exception.pool_id].capacity_exceptions.append(exception)
    project_ids = sorted({assignment['project_id'] for assignment in assignments})
    bounds = {
        project_id: (start, end) for project_id, start, end in store.connection.execute(
            "SELECT project_id,to_char(min(start_date),'YYYY-MM-DD'),to_char(max(end_date),'YYYY-MM-DD') "
            'FROM eppm.project_task WHERE project_id=ANY(%s::bigint[]) GROUP BY project_id', (project_ids,),
        )
    }
    for values in inputs.values():
        values.project_bounds = bounds
    for assignment in assignments:
        inputs[assignment['pool_id']].assignments.append(assignment)
    return inputs
