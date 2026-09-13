"""Real native/HTTP source comparisons keep unrelated edits out of task refreshes."""

import psycopg
import pytest

from app.application.exceptions import PlanningStorageError
from app.application.services.business_access import BusinessAccess
from app.main import create_planning_workspace
from app.presentation.components import planning_transport
from tests.postgresql.test_planning_http import task_browser as task_browser, post_batch
from tests.postgresql.test_session_transport import transport as transport


def workspace_for(fixture):
    _, service, _, actor, _, resources, _, _ = fixture
    return create_planning_workspace(resources, access=BusinessAccess(actor, service.policy))


def source_request(fixture):
    captured = workspace_for(fixture).sources.capture([1])
    return {str(pid): token for pid, token in captured.tokens.items()}


@pytest.mark.parametrize('during', [False, True])
def test_unrelated_visible_edits_do_not_require_a_task_refresh(pg_database, task_browser, monkeypatch, during):
    _, service, admin, actor, _, _, _, _ = task_browser
    service.grant(admin, actor.user_id, 'project_viewer', {'kind': 'projects', 'project_ids': [2]})
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute('DELETE FROM eppm.task_dependencies')
    sources = source_request(task_browser)
    original = planning_transport.build_task_payload

    def update():
        with psycopg.connect(pg_database.operator_url) as connection:
            connection.execute("UPDATE eppm.project SET name='Unrelated edit' WHERE id=2")

    def build_then_edit(*args, **kwargs):
        result = original(*args, **kwargs)
        update()
        return result

    if during:
        monkeypatch.setattr(planning_transport, 'build_task_payload', build_then_edit)
    else:
        update()
    response = post_batch(task_browser, source_tokens=sources)
    assert response.status_code == 200
    assert [task['id'] for task in response.json()['tasks']] == ['10']


@pytest.mark.parametrize('change', ['task', 'predecessor', 'pool', 'pool_consumer', 'assignment', 'catalog', 'membership', 'revoke'])
@pytest.mark.parametrize('during', [False, True])
def test_changed_task_sources_or_authority_reject_the_batch(pg_database, task_browser, monkeypatch, change, during):
    _, service, admin, actor, _, _, _, assignment = task_browser
    service.grant(admin, actor.user_id, 'project_viewer', {'kind': 'projects', 'project_ids': [2]})
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Shared',1)")
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES(1,1,10,0.6),(1,2,20,0.6)")
        if change in {'pool', 'pool_consumer'}:
            connection.execute('DELETE FROM eppm.task_dependencies')
    if change == 'membership':
        service.grant(admin, actor.user_id, 'project_viewer', {'kind': 'all'})
    sources = source_request(task_browser)
    original = planning_transport.build_task_payload

    def update():
        if change == 'revoke':
            service.revoke(admin, assignment)
            return
        with psycopg.connect(pg_database.operator_url) as connection:
            statements = {
                'task': 'UPDATE eppm.project_task SET progress_pct=40 WHERE id=10',
                'predecessor': "UPDATE eppm.project_task SET end_date='2026-01-10' WHERE id=20",
                'pool': 'UPDATE eppm.resource_pool SET capacity_fte=2 WHERE id=1',
                'pool_consumer': 'UPDATE eppm.resource_pool_assignment SET fte_assigned=0.2 WHERE project_id=2',
                'assignment': 'DELETE FROM eppm.resource_pool_assignment WHERE project_id=1',
                'catalog': 'UPDATE eppm.catalog_cache_revision SET revision=revision+1',
                'membership': "INSERT INTO eppm.project(id,name) VALUES(3,'New visible project')",
            }
            connection.execute(statements[change])

    def build_then_edit(*args, **kwargs):
        result = original(*args, **kwargs)
        update()
        return result

    if during:
        monkeypatch.setattr(planning_transport, 'build_task_payload', build_then_edit)
    else:
        update()
    response = post_batch(task_browser, source_tokens=sources)
    assert response.status_code == (403 if change == 'revoke' else 409)
    assert 'tasks' not in response.json()


def test_hidden_sources_do_not_change_tokens_and_native_keys_match_chart_capture(pg_database, task_browser):
    workspace = workspace_for(task_browser)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Shared',1)")
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES(1,1,10,0.6),(1,2,20,0.6)")
    expected = workspace.sources.capture([1]).tokens
    assert workspace.sources.read([1]) == expected
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("UPDATE eppm.project_task SET end_date='2026-01-10' WHERE id=20")
        connection.execute('UPDATE eppm.resource_pool_assignment SET fte_assigned=0.2 WHERE project_id=2')
    assert workspace.sources.read([1]) == expected
    assert post_batch(task_browser, source_tokens={str(k): v for k, v in expected.items()}).status_code == 200


@pytest.mark.parametrize('sources', [{}, [], {'1': 'bad'}, {'1': 'a' * 64, '2': 'b' * 64}, {'01': 'a' * 64}])
def test_source_tokens_must_match_exactly_the_requested_projects(task_browser, sources):
    assert post_batch(task_browser, source_tokens=sources).status_code == 400


@pytest.mark.parametrize('ids', [[2], [999], [1, 2]])
def test_source_tokens_never_authorize_hidden_or_missing_projects(task_browser, ids):
    assert post_batch(task_browser, project_ids=ids, source_tokens={str(pid): 'a' * 64 for pid in ids}).status_code == 403


def test_missing_revision_metadata_fails_closed_and_translates_storage_errors(pg_database, task_browser):
    sources = source_request(task_browser)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute('DELETE FROM eppm.project_cache_revision WHERE project_id=1')
    assert post_batch(task_browser, source_tokens=sources).status_code == 503
    with pytest.raises(PlanningStorageError, match='Planning data could not be accessed'):
        workspace_for(task_browser).sources.capture([1])
