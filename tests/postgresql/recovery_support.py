"""Operator inspection and restricted-service probes for deployed recovery tests."""

from dataclasses import replace
import json
from textwrap import indent

from tests.test_oidc_browser_e2e import BrowserDeployment


def operator_json(server: BrowserDeployment, source: str, *, stage: str,
                  variables: dict[str, str] | None = None) -> dict[str, object]:
    """Execute a fictional fixture probe without exposing credentials on failure.

    Args:
        server: The test's separately provisioned Compose deployment.
        source: Trusted test-owned Python; it prints one JSON result.
        stage: Safe diagnostic label identifying the requested operation.
        variables: Private values forwarded by environment-variable name only.
    """
    private = variables or {}
    runner = replace(server, environment=server.environment | private)
    guarded = ('import json, traceback\ntry:\n' + indent(source, '    ')
               + '\nexcept Exception as error:\n'
               '    print(json.dumps({"operator_failure": type(error).__name__, '
               '"source_line": traceback.extract_tb(error.__traceback__)[-1].lineno}))\n')
    output = runner.command('run', '--rm', '-T', '--no-deps', '--entrypoint', 'python',
                            '-e', 'DATABASE_OPERATOR_URL',
                            *(part for name in private for part in ('-e', name)),
                            'app', '-c', guarded)
    result = json.loads(output)
    if 'operator_failure' in result:
        raise RuntimeError(f"Recovery stage {stage} failed: {result['operator_failure']} at line {result['source_line']}")
    return result


SNAPSHOT = '''
import os
import psycopg
from psycopg import sql

with psycopg.connect(os.environ['DATABASE_OPERATOR_URL']) as connection:
    tables = [row[0] for row in connection.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='eppm' ORDER BY tablename")]
    hashes, counts, sequences = {}, {}, {}
    for name in tables:
        count, digest = connection.execute(sql.SQL(
            "SELECT count(*), md5(coalesce(string_agg(to_jsonb(t)::text, '' ORDER BY to_jsonb(t)::text), '')) FROM eppm.{} t"
        ).format(sql.Identifier(name))).fetchone()
        counts[name], hashes[name] = count, digest
    for name, in connection.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='eppm' ORDER BY sequencename").fetchall():
        sequences[name] = list(connection.execute(sql.SQL('SELECT last_value, is_called FROM eppm.{}').format(sql.Identifier(name))).fetchone())
print(json.dumps({'hashes': hashes, 'counts': counts, 'sequences': sequences}))
'''


SEED = '''
import os
import psycopg
from app.application.ports.maintenance import SeedRequest
from app.operator_services import create_maintenance_service

summary = create_maintenance_service().seed_projects(
    SeedRequest(projects=10001, min_tasks=0, max_tasks=15, clean_first=True, random_seed=42))
with psycopg.connect(os.environ['DATABASE_OPERATOR_URL']) as connection:
    project, task, pool = connection.execute(
        'SELECT t.project_id,t.id,a.pool_id FROM eppm.project_task t '
        'JOIN eppm.resource_pool_assignment a ON a.project_id=t.project_id '
        'AND (a.task_id=t.id OR a.task_id IS NULL) ORDER BY t.id,a.id LIMIT 1').fetchone()
    hidden = connection.execute('SELECT id FROM eppm.project WHERE id<>%s ORDER BY id LIMIT 1', (project,)).fetchone()[0]
    connection.execute('UPDATE eppm.project SET name=%s WHERE id=%s', ('Recovery retained project', project))
    connection.execute("INSERT INTO eppm.project_financial_transaction(project_id,fiscal_year,amount,currency,exchange_rate,amount_base_currency,financial_record_type,spending_type,wbs) VALUES (%s,2026,9007199254740993.01,'EUR',1,9007199254740993.01,'COMMITMENT','CAPEX','RECOVERY'),(%s,2026,.01,'EUR',1,.01,'ACTUAL','CAPEX','RECOVERY')", (project, project))
    connection.execute('UPDATE eppm.project_task SET task_name=%s WHERE id=%s', ('Recovery retained task', task))
    wbs = connection.execute("INSERT INTO eppm.wbs(code,description) VALUES ('RECOVERY','Approved recovery allocation') RETURNING id").fetchone()[0]
    connection.execute('INSERT INTO eppm.project_wbs(project_id,wbs_id,percentage) VALUES (%s,%s,37)', (project, wbs))
print(json.dumps({'summary': summary, 'project': project, 'task': task, 'pool': pool, 'hidden_project': hidden}))
'''


RUNTIME = '''
import os
from app.application.services.business_access import BusinessAccess
from app.runtime import RuntimeResources
from app.security import create_access_service
from app.shared.config.authentication import AuthenticationConfig

resources = RuntimeResources.from_environment(os.environ)
resources.database.open()
service = create_access_service(resources, AuthenticationConfig.from_environment(os.environ))
actor = service.actor(os.environ['RECOVERY_COOKIE'])
access = BusinessAccess(actor, service.policy)
'''


GRANT_AND_APPROVE = RUNTIME + '''
from app.main import create_finance_service
try:
    service.grant(actor, actor.user_id, 'business_admin', {'kind': 'all'})
    viewer = int(os.environ['RECOVERY_VIEWER'])
    project = int(os.environ['RECOVERY_PROJECT'])
    service.set_status(actor, viewer, 'active')
    service.grant(actor, viewer, 'project_viewer', {'kind': 'projects', 'project_ids': [project]})
    snapshot = create_finance_service(resources, access=access).save(
        [{'code': 'RECOVERY', 'amounts': {'2026': '9007199254740993.01', '2027': '0.01'}}],
        base_id=None, name='Approved recovery truth', status='Approved', year=2026)
    print(json.dumps({'snapshot': snapshot, 'administrator': actor.user_id, 'viewer': viewer}))
finally:
    resources.database.close()
'''


WARM = RUNTIME + '''
from dataclasses import asdict
from app.infrastructure.postgresql.authorization import ActorBinding
from app.main import create_planning_service, create_pool_capacity_service, create_finance_service
try:
    project, pool = int(os.environ['RECOVERY_PROJECT']), int(os.environ['RECOVERY_POOL'])
    planning = create_planning_service(resources, access=access).get_project_summaries([project])
    capacity = create_pool_capacity_service(resources, access=access).get_summaries([pool])
    finance = create_finance_service(resources, access=access).view(int(os.environ['RECOVERY_SNAPSHOT'])).selected
    money = resources.database.run(lambda connection: connection.execute(
        "SELECT sum(amount_base_currency) FILTER(WHERE financial_record_type='COMMITMENT')::text,sum(amount_base_currency) FILTER(WHERE financial_record_type='ACTUAL')::text FROM eppm.project_financial_transaction WHERE project_id=%s", (project,)
    ).fetchone(), bind=ActorBinding(access, resources.key))
    print(json.dumps({'planning': planning, 'capacity': [asdict(row) for row in capacity],
                      'finance': asdict(finance), 'money': money}, default=str, sort_keys=True))
finally:
    resources.database.close()
'''


BACKUP = '''
import os
from pathlib import Path
from app.infrastructure.postgresql.backup import PostgresBackup
archive = PostgresBackup(os.environ['DATABASE_OPERATOR_URL'], Path('/app/data/recovery-archives')).create('deployed-recovery')
print(json.dumps({'archive': str(archive)}))
'''


RESTORE = '''
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from app.infrastructure.postgresql.backup import restore_database

name = os.environ['RECOVERY_DATABASE']
assert name.startswith('eppm_recovery_') and len(name) == len('eppm_recovery_') + 32
int(name.removeprefix('eppm_recovery_'), 16)
original = os.environ['DATABASE_OPERATOR_URL']
target = urlunsplit(urlsplit(original)._replace(path='/' + name))
with psycopg.connect(make_conninfo(original, dbname='postgres'), autocommit=True) as connection:
    connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
restore_database(Path(os.environ['RECOVERY_ARCHIVE']), target)
print(json.dumps({'database': name}))
'''


CLEAR_CACHES = '''
import os
import psycopg
with psycopg.connect(os.environ['DATABASE_OPERATOR_URL']) as connection:
    connection.execute('DELETE FROM eppm.pool_capacity_cache')
    connection.execute('DELETE FROM eppm.planning_summary_cache')
print(json.dumps({'cleared': True}))
'''


IMMUTABILITY = RUNTIME + '''
import psycopg
from app.infrastructure.postgresql.authorization import ActorBinding
try:
    try:
        resources.database.run(lambda connection: connection.execute(
            'UPDATE eppm.finance_snapshot SET name=%s WHERE id=%s',
            ('Tampered restored plan', int(os.environ['RECOVERY_SNAPSHOT']))),
            write=True, bind=ActorBinding(access, resources.key))
    except psycopg.errors.CheckViolation:
        finance_immutable = True
    else:
        finance_immutable = False
    with psycopg.connect(os.environ['DATABASE_OPERATOR_URL']) as connection:
        try:
            with connection.transaction():
                connection.execute("UPDATE eppm.app_security_audit SET action='tampered'")
        except psycopg.errors.CheckViolation:
            audit_immutable = True
        else:
            audit_immutable = False
    print(json.dumps({'finance_immutable': finance_immutable, 'audit_immutable': audit_immutable}))
finally:
    resources.database.close()
'''
