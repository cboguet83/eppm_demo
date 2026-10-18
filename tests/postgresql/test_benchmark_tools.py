"""Native diagnostic isolation and real planning/dialog rendering contracts."""

import json
from io import StringIO
import os
import sys

import psycopg
from psycopg import sql
import pytest
from streamlit.testing.v1 import AppTest

from app.application.exceptions import DatabaseMaintenanceError
from app.main import create_planning_service
from scripts.benchmark_planning import create_app, run_app
from scripts.benchmark_runtime import isolated_benchmark
from scripts.benchmark_task_pool_dialog import modal_app
from tests.postgresql.business import business


def snapshot(setup):
    """Hash every source table and inspect sequences without exposing record data."""
    with psycopg.connect(setup.operator_url) as connection:
        tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='eppm' ORDER BY tablename").fetchall()
        values = {name: connection.execute(sql.SQL(
            "SELECT md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY row_to_json(t)::text),'')) FROM eppm.{} t"
        ).format(sql.Identifier(name))).fetchone()[0] for name, in tables}
        for name, in connection.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='eppm'").fetchall():
            values[name] = connection.execute(sql.SQL('SELECT last_value, is_called FROM eppm.{}').format(sql.Identifier(name))).fetchone()
        return values


def copies(setup):
    with psycopg.connect(setup.operator_url) as connection:
        return {row[0] for row in connection.execute("SELECT datname FROM pg_database WHERE datname LIKE 'eppm_benchmark_%'")}


def test_planning_events_and_modal_reruns_use_only_the_restricted_restored_copy(business, pg_database, clients):
    before, databases = snapshot(pg_database), copies(pg_database)
    with isolated_benchmark(pg_database.operator_url, pg_database.runtime_url, tools=clients) as context:
        assert context.counts() == (2, 2, 1)
        assert context.project_ids(1) == [1]
        assert context.project_ids(0) == [1, 2]
        assert context.task_id() == 10
        assert context.task_id(20) == 20
        assert context.name in copies(pg_database) - databases
        with pytest.raises(ValueError, match='No matching task'):
            context.task_id(9999)
        with pytest.raises(ValueError, match='nonnegative'):
            context.project_ids(-1)
        with pytest.raises(ValueError, match='positive'):
            context.task_id(0)
        service = create_planning_service(context.resources, access=context.access)
        app = create_app(context, projects=0, profile=True, capture=True)
        run_app(app)
        assert app.session_state['benchmark_counts'] == (2, 2, 1)
        assert 'function calls' in app.session_state['benchmark_profile']
        assert app.session_state['benchmark_seconds'] > 0
        json.dumps(app.session_state['benchmark_payload'])
        app.session_state['benchmark_event'] = {
            'action': 'load_project_tasks', 'project_ids': [1],
            'scope_token': app.session_state['planning_chart_snapshot']['token'], 'nonce': 'load',
        }
        run_app(app)
        app.session_state['benchmark_event'] = {
            'action': 'toggle_edit', 'enabled': True, 'nonce': 'enable-edit',
        }
        run_app(app)
        app.session_state['benchmark_event'] = {'action': 'update_progress', 'id': 10, 'progress': 63, 'nonce': 'edit'}
        run_app(app)
        assert service.get_milestone_by_id(10)['progress_pct'] == 63
        modal = AppTest.from_function(modal_app, args=(context, 10), default_timeout=30)
        run_app(modal)
        modal.number_input(key='ni_assign_task_fte').set_value(1.5)
        run_app(modal)
        modal.radio(key='rb_assign_task_period_mode').set_value('custom')
        run_app(modal)
        assert modal.session_state['benchmark_modal_seconds'] > 0
        assert snapshot(pg_database) == before
    assert copies(pg_database) == databases
    assert snapshot(pg_database) == before


def test_render_failure_still_closes_the_pool_and_drops_only_its_copy(business, pg_database, clients):
    before, databases = snapshot(pg_database), copies(pg_database)
    with pytest.raises(RuntimeError, match='diagnostic failure'):
        with isolated_benchmark(pg_database.operator_url, pg_database.runtime_url, tools=clients):
            raise RuntimeError('diagnostic failure')
    assert copies(pg_database) == databases
    assert snapshot(pg_database) == before


@pytest.mark.parametrize('failed_tool', ['pg_dump', 'pg_restore'])
def test_failed_archive_client_preserves_source_and_leaves_no_copy(business, pg_database, clients, monkeypatch, failed_tool):
    before, databases = snapshot(pg_database), copies(pg_database)
    native_run = clients.run

    def fail_restore(tool, arguments, **kwargs):
        if tool == failed_tool and (tool == 'pg_dump' or '--dbname' in arguments):
            raise DatabaseMaintenanceError('Archive client failed')
        return native_run(tool, arguments, **kwargs)

    monkeypatch.setattr(clients, 'run', fail_restore)
    with pytest.raises(DatabaseMaintenanceError, match='Archive client failed'):
        with isolated_benchmark(pg_database.operator_url, pg_database.runtime_url, tools=clients):
            pytest.fail('A failed restore cannot yield a runtime')
    assert copies(pg_database) == databases
    assert snapshot(pg_database) == before


def test_gantt_browser_driver_consumes_native_session_payloads_and_cleans_up(business, pg_database):
    import asyncio
    from pathlib import Path
    import subprocess
    from playwright.async_api import async_playwright

    async def executable() -> str:
        if configured := os.environ.get('EPPM_BENCHMARK_BROWSER'):
            path = Path(configured)
            if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
                raise ValueError('EPPM_BENCHMARK_BROWSER must be an absolute executable file')
            return str(path)
        async with async_playwright() as playwright:
            path = playwright.chromium.executable_path
            # Let the driver's initialization task finish before stopping it;
            # reading this local property does not itself yield to the loop.
            await asyncio.sleep(0)
            return path

    before, databases = snapshot(pg_database), copies(pg_database)
    environment = os.environ | {'DATABASE_OPERATOR_URL': pg_database.operator_url,
                                'DATABASE_URL': pg_database.runtime_url,
                                'EPPM_BENCHMARK_PYTHON': sys.executable}
    command = ['node', 'scripts/benchmark_gantt.cjs', asyncio.run(executable()),
               '--database', '--all-projects', '--expanded', '--move-task']
    if container := os.environ.get('POSTGRES_TEST_CLIENT_CONTAINER'):
        command.append('--client-container=' + container)
    result = subprocess.run(command, env=environment, cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr[-3000:]
    report = json.loads(result.stdout)
    assert report['source'] == 'isolated PostgreSQL restore'
    assert report['projects'] == 2 and report['pools'] == 1
    assert report['serverTimings'][0]['seconds'] > 0
    assert any(item['action'] == 'update_task_full' for item in report['serverTimings'])
    assert copies(pg_database) == databases
    assert snapshot(pg_database) == before


@pytest.mark.parametrize(('operator', 'runtime'), [
    ('', ''),
    ('postgresql://operator@localhost/source', 'postgresql://operator@localhost/source'),
    ('postgresql://operator@localhost/source', 'postgresql://runtime@localhost/another'),
    ('postgresql://operator@localhost/source', 'postgresql://runtime@other/source'),
    ('postgresql://operator@localhost/source?dbname=other', 'postgresql://runtime@localhost/source'),
    ('postgresql://operator@localhost/postgres', 'postgresql://runtime@localhost/postgres'),
])
def test_invalid_source_coordinates_fail_before_any_copy_or_business_work(operator, runtime):
    with pytest.raises(ValueError):
        with isolated_benchmark(operator, runtime):
            pytest.fail('Unsafe source coordinates must not yield a runtime')


@pytest.mark.parametrize('module', ['benchmark_planning', 'benchmark_planning_session', 'benchmark_task_pool_dialog'])
def test_operator_cli_outputs_native_results_and_removes_its_copy(module, business, pg_database, clients, monkeypatch, capsys):
    from importlib import import_module

    before, databases = snapshot(pg_database), copies(pg_database)
    monkeypatch.setenv('DATABASE_OPERATOR_URL', pg_database.operator_url)
    monkeypatch.setenv('DATABASE_URL', pg_database.runtime_url)
    arguments = [module]
    if container := os.environ.get('POSTGRES_TEST_CLIENT_CONTAINER'):
        arguments.extend(['--client-container', container])
    if module == 'benchmark_planning':
        arguments.extend(['--projects', '1', '--dump-payload', '--no-profile'])
    monkeypatch.setattr(sys, 'argv', arguments)
    monkeypatch.setattr(sys, 'stdin', StringIO(
        '{"action":"toggle_edit","enabled":true,"nonce":"enable-edit"}\n'
        '{"action":"update_progress","id":10,"progress":47,"nonce":"cli"}\n'
    ))
    import_module('scripts.' + module).main()
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records
    if module == 'benchmark_planning_session':
        assert len(records) == 3 and all(
            row['server_seconds'] > 0 for row in records
        )
    elif module == 'benchmark_task_pool_dialog':
        assert records[0]['tasks'] == 2 and records[0]['pools'] == 1
        assert records[0]['period_refresh_total_seconds'] > 0
    assert copies(pg_database) == databases
    assert snapshot(pg_database) == before
