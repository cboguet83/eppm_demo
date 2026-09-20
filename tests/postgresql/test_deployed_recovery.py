"""Opt-in representative PostgreSQL restart and restored-application acceptance."""

from dataclasses import replace
import json
import os
from pathlib import Path
import re
from time import perf_counter
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest

from app.infrastructure.authentication.http import SESSION_COOKIE
from app.presentation.navigation import PAGE_PLANNING
from tests.test_oidc_browser_e2e import BrowserDeployment, deployment, sign_in, wait_for_server
from tests.postgresql.recovery_support import (
    BACKUP, CLEAR_CACHES, GRANT_AND_APPROVE, IMMUTABILITY, RESTORE, SEED, SNAPSHOT, WARM, operator_json,
)

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page

pytestmark = pytest.mark.skipif(os.environ.get('EPPM_RUN_OIDC_E2E') != '1',
                                reason='Requires the opt-in isolated Keycloak/PostgreSQL deployment')


def _cookie(context: 'BrowserContext') -> str:
    return next(cookie['value'] for cookie in context.cookies() if cookie['name'] == SESSION_COOKIE)


def _pending_reference(page: 'Page') -> int:
    reference = page.get_by_text(re.compile(r'Application user reference: \d+')).first.inner_text()
    return int(re.search(r'\d+', reference).group())


def _probe_values(data: dict[str, object], context: 'BrowserContext', snapshot: int) -> dict[str, str]:
    return {'RECOVERY_COOKIE': _cookie(context), 'RECOVERY_PROJECT': str(data['project']),
            'RECOVERY_POOL': str(data['pool']), 'RECOVERY_SNAPSHOT': str(snapshot)}


def _planning_page(page: 'Page', server: BrowserDeployment, data: dict[str, object]) -> None:
    from playwright.sync_api import expect

    page.goto(server.origin + '/?' + urlencode({'nav': PAGE_PLANNING}))
    projects = page.locator('.st-key-ms_multi_projects').get_by_role('combobox')
    projects.click()
    projects.fill('Recovery retained project')
    page.get_by_role('option', name=re.compile('Recovery retained project')).click()
    projects.press('Tab')
    iframe = page.locator('iframe[title*="interactive_gantt"]')
    expect(iframe).to_be_visible()
    frame = iframe.element_handle().content_frame()
    frame.wait_for_function("pid => typeof projectSummariesData !== 'undefined' && "
                            "projectSummariesData.length === 1 && Number(projectSummariesData[0].id) === pid",
                            arg=data['project'])
    frame.locator('#btn-expand-all').click()
    frame.wait_for_function("task => typeof tasksData !== 'undefined' && tasksData.some(row => Number(row.id) === task)",
                            arg=data['task'])
    assert frame.evaluate("tasksData.some(row => row.name === 'Recovery retained task')")
    assert not page.get_by_test_id('stException').count()


def _assert_browser_access(context: 'BrowserContext', server: BrowserDeployment,
                           data: dict[str, object], snapshot: int, *, scoped: bool) -> None:
    assert context.request.get(server.origin + '/auth/session').status == 200
    task = context.request.get(server.origin + f"/downloads/projects/{data['project']}/template.csv")
    assert task.status == 200 and 'Recovery retained task' in task.text()
    if scoped:
        assert context.request.get(server.origin + f"/downloads/projects/{data['hidden_project']}/template.csv").status == 403
    # Approved Finance is intentionally readable by active accounts independently
    # of project scope; only its editing permission is restricted.
    finance = context.request.get(server.origin + f'/downloads/finance/{snapshot}/budget.csv')
    assert finance.status == 200 and '9007199254740993.01' in finance.text()


def _stable_hashes(snapshot: dict[str, object]) -> dict[str, str]:
    mutable = {'app_session', 'app_oidc_state', 'pool_capacity_cache', 'planning_summary_cache'}
    return {name: value for name, value in snapshot['hashes'].items() if name not in mutable}


def _restored_server(server: BrowserDeployment, name: str) -> BrowserDeployment:
    values = {key: urlunsplit(urlsplit(server.environment[key])._replace(path='/' + name))
              for key in ('DATABASE_URL', 'DATABASE_OPERATOR_URL')}
    return replace(server, environment=server.environment | values)


def test_representative_deployed_restart_and_restore_preserve_truth_access_and_rebuild_caches(
    deployment: BrowserDeployment,
) -> None:
    """Recover the real application with 10,001 projects and verified identities."""
    from playwright.sync_api import expect, sync_playwright

    started = perf_counter()
    data = operator_json(deployment, SEED, stage='representative seed')
    assert data['summary']['projects_created'] == 10001
    expect.set_options(timeout=60000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get('EPPM_BROWSER_CHANNEL'))
        administrator = browser.new_context()
        viewer = browser.new_context()
        try:
            admin_page, viewer_page = administrator.new_page(), viewer.new_page()
            admin_page.set_default_timeout(60000)
            viewer_page.set_default_timeout(60000)
            sign_in(admin_page, deployment, 'alex.admin', 'KEYCLOAK_ALEX_PASSWORD')
            admin_id = _pending_reference(admin_page)
            sign_in(viewer_page, deployment, 'robin.viewer', 'KEYCLOAK_ROBIN_PASSWORD')
            viewer_id = _pending_reference(viewer_page)
            deployment.operator('-m', 'scripts.access_admin', 'bootstrap-admin', '--user-id', str(admin_id))
            approved = operator_json(deployment, GRANT_AND_APPROVE, stage='grants and approved plan', variables={
                'RECOVERY_COOKIE': _cookie(administrator), 'RECOVERY_VIEWER': str(viewer_id),
                'RECOVERY_PROJECT': str(data['project']),
            })
            snapshot_id = approved['snapshot']
            values = _probe_values(data, administrator, snapshot_id)
            expected = operator_json(deployment, WARM, stage='source cache calculation', variables=values)
            assert expected['money'] == ['9007199254740993.01', '0.01']
            _planning_page(admin_page, deployment, data)
            _assert_browser_access(administrator, deployment, data, snapshot_id, scoped=False)
            _assert_browser_access(viewer, deployment, data, snapshot_id, scoped=True)

            # Freeze the source before comparing every stored row and sequence.
            deployment.command('stop', 'app')
            before = operator_json(deployment, SNAPSHOT, stage='source snapshot')
            assert before['counts']['project'] == 10001
            assert before['counts']['project_task'] == 73929
            assert before['counts']['resource_pool_assignment'] == 10201
            assert before['counts']['app_user'] == 2
            assert before['counts']['app_role_assignment'] == 3
            assert before['counts']['app_security_audit'] > 0
            assert before['counts']['pool_capacity_cache'] > 0
            assert before['counts']['planning_summary_cache'] > 0
            archive = operator_json(deployment, BACKUP, stage='native archive')['archive']

            deployment.command('restart', 'postgres')
            deployment.command('up', '-d', '--no-deps', '--no-build', '--wait', 'postgres')
            assert operator_json(deployment, SNAPSHOT, stage='database restart comparison') == before
            deployment.command('up', '-d', '--no-deps', '--no-build', 'app')
            wait_for_server(deployment.origin + '/_stcore/health')
            _assert_browser_access(administrator, deployment, data, snapshot_id, scoped=False)
            _assert_browser_access(viewer, deployment, data, snapshot_id, scoped=True)
            _planning_page(admin_page, deployment, data)
            assert operator_json(deployment, WARM, stage='restarted runtime calculation', variables=values) == expected
            deployment.command('stop', 'app')
            after_restart = operator_json(deployment, SNAPSHOT, stage='stable restarted records')
            assert _stable_hashes(after_restart) == _stable_hashes(before)

            name = 'eppm_recovery_' + uuid4().hex
            operator_json(deployment, RESTORE, stage='restore into new database', variables={
                'RECOVERY_DATABASE': name, 'RECOVERY_ARCHIVE': archive,
            })
            restored = _restored_server(deployment, name)
            assert operator_json(restored, SNAPSHOT, stage='complete restored snapshot') == before
            operator_json(restored, CLEAR_CACHES, stage='clear replaceable restored caches')
            cold = operator_json(restored, SNAPSHOT, stage='cold restored cache counts')
            assert cold['counts']['pool_capacity_cache'] == cold['counts']['planning_summary_cache'] == 0
            restored.command('up', '-d', '--no-deps', '--no-build', '--force-recreate', 'app')
            wait_for_server(restored.origin + '/_stcore/health')
            _assert_browser_access(administrator, restored, data, snapshot_id, scoped=False)
            _assert_browser_access(viewer, restored, data, snapshot_id, scoped=True)
            _planning_page(admin_page, restored, data)
            rebuilt_by_app = operator_json(restored, SNAPSHOT, stage='deployed cache rebuild')
            assert rebuilt_by_app['counts']['planning_summary_cache'] > 0
            assert rebuilt_by_app['counts']['pool_capacity_cache'] > 0
            assert operator_json(restored, WARM, stage='restored calculation parity', variables=values) == expected
            assert operator_json(restored, IMMUTABILITY, stage='restored history protection', variables=values) == {
                'finance_immutable': True, 'audit_immutable': True,
            }
            restored.command('stop', 'app')
            final = operator_json(restored, SNAPSHOT, stage='stable restored records')
            assert _stable_hashes(final) == _stable_hashes(before)
            assert final['sequences'] == before['sequences']
            assert _stable_hashes(operator_json(deployment, SNAPSHOT, stage='source preserved after restore')) == _stable_hashes(before)
            report = {
                'scope': 'Real OIDC/deployed PostgreSQL restart and full restore; not a load test',
                'image': deployment.environment['EPPM_APP_IMAGE'],
                'elapsed_seconds': round(perf_counter() - started, 3),
                'seed': {'projects': 10001, 'min_tasks': 0, 'max_tasks': 15, 'random_seed': 42},
                'counts': before['counts'],
                'all_table_hashes_equal_after_restart_and_restore': True,
                'all_sequences_preserved': True,
                'stable_business_accounts_grants_audit_equal_after_browser_use': True,
                'existing_real_oidc_sessions_and_scoped_http_access_survive': True,
                'approved_finance_and_audit_remain_immutable': True,
                'planning_and_capacity_caches_rebuilt_by_deployed_application': True,
                'rebuilt_service_results_equal_original': True,
                'ordinary_application_database_or_volumes_modified': False,
            }
            report_path = Path(__file__).resolve().parents[2] / '.local/postgresql-deployed-recovery-results.json'
            report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        finally:
            administrator.close()
            viewer.close()
            browser.close()
