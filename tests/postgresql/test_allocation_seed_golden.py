"""Independent legacy golden reports and mutations checked with native rows only."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.domain.resources.allocation_generation import AllocationGenerationRequest
from app.infrastructure.postgresql.allocation_seed import apply_allocation_plan, prepare_allocation_plan
from tests.postgresql.test_allocation_seed import allocations


GOLDEN = json.loads((Path(__file__).parent / 'fixtures' / 'allocation_seed_golden.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', GOLDEN['cases'], ids=lambda case: case['name'])
def test_native_report_and_all_mutations_match_independent_synthetic_baseline(allocations, case):
    def change(connection):
        if case['name'] == 'zero_mappings':
            connection.execute('UPDATE eppm.resource_pool_mapping SET allocation_pct=0')
        elif case['name'] == 'empty_pools':
            connection.execute('DELETE FROM eppm.resource_pool_mapping')
            connection.execute('UPDATE eppm.resource_pool SET capacity_fte=NULL')
    allocations.database.run(change, write=True)
    request = AllocationGenerationRequest(**case['request'])
    plan = allocations.database.run(lambda c: prepare_allocation_plan(c, request, today=date(2026, 6, 1)))
    report = plan.report()
    report.pop('fingerprint')
    allocations.database.run(lambda c: apply_allocation_plan(c, plan), write=True)
    def persisted(connection):
        return {
            'assignments': connection.execute('SELECT pool_id,project_id,task_id,fte_assigned,start_date,end_date,notes '
                                             'FROM eppm.resource_pool_assignment ORDER BY id').fetchall(),
            'mappings': connection.execute('SELECT pool_id,target_type,target_id,allocation_pct FROM eppm.resource_pool_mapping '
                                          'ORDER BY pool_id,target_type,target_id').fetchall(),
            'capacities': connection.execute('SELECT id,capacity_fte FROM eppm.resource_pool ORDER BY id').fetchall(),
        }
    data = json.dumps({'report': report, **allocations.database.run(persisted)},
                      sort_keys=True, separators=(',', ':'), default=str).encode()
    assert sha256(data).hexdigest() == case['sha256']
