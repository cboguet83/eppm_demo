"""Deterministic synthetic snapshots for the accepted status and date rules."""

from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import psycopg
import pytest

from app.application.ports.maintenance import SeedRequest
from app.infrastructure.postgresql.bulk_seed import generate_projects
from app.infrastructure.postgresql.pool import OperatorDatabase


GOLDEN = json.loads(Path(__file__).with_name('fixtures').joinpath('bulk_seed_golden.json').read_text(encoding='utf-8'))
QUERIES = {
    'projects': 'SELECT id,name,status,strategic_priority_id,function_id,project_type_id FROM eppm.project ORDER BY id',
    'properties': 'SELECT project_id,param_id,kind,text_value,number_value,date_value FROM eppm.project_property_value ORDER BY project_id,param_id',
    'selections': 'SELECT project_id,param_id,position,value FROM eppm.project_property_value_item ORDER BY project_id,param_id,position',
    'tasks': 'SELECT id,project_id,task_name,phase,start_date,end_date,progress_pct,description FROM eppm.project_task ORDER BY id',
    'dependencies': 'SELECT task_id,predecessor_task_id,predecessor_project_id,link_type,lag_days FROM eppm.task_dependencies ORDER BY id',
}


def canonical(value):
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, date):
        return value.isoformat()
    return value


@pytest.mark.parametrize('case', GOLDEN['cases'], ids=('mixed', 'single', 'maximum', 'empty'))
def test_native_workloads_match_status_mix_snapshots(case, pg_database):
    result = OperatorDatabase(pg_database.operator_url).run(
        lambda c: generate_projects(c, SeedRequest(**case['request']), year=2026, today=date(2026, 9, 14)), write=True)
    assert result == case['summary']
    with psycopg.connect(pg_database.operator_url) as connection:
        for name, query in QUERIES.items():
            rows = [[canonical(value) for value in row] for row in connection.execute(query)]
            actual = {'count': len(rows), 'sha256': sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()}
            assert actual == case['expected'][name], name
