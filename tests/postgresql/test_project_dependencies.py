"""Real project links preserve steps, enforce scope and invalidate scoped caches."""

import psycopg
import pytest

from app.application.exceptions import PlanningConflictError
from app.application.services.planning import PlanningService
from app.infrastructure.postgresql.planning import PostgresPlanningGateway


def service(authorized, user_id=1):
    return PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(user_id).access))


@pytest.fixture
def links(authorized):
    with psycopg.connect(authorized.setup.operator_url) as c:
        c.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (1,1,'Successor','2026-01-10','2026-01-20',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(2,2,'Predecessor','2026-01-01','2026-01-15',(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current)),(3,3,'Hidden','2026-02-01','2026-02-20',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
        c.execute("SELECT setval(pg_get_serial_sequence('eppm.project_task','id'),3)")
    return authorized


def link(project=2, task=None, kind='FS', lag=0):
    return dict(predecessor_project_id=project, predecessor_task_id=task, link_type=kind, lag_days=lag)


def test_project_link_save_only_changes_dependencies_and_accepts_read_only_predecessor(links):
    planning = service(links)
    before = links.query('SELECT id,project_id,task_name,start_date,end_date,phase,progress_pct,description FROM eppm.project_task ORDER BY id')
    panel = planning.get_project_dependency_panel(1)
    saved = planning.save_project_dependencies(1, [link(), link(None, 2, 'FF', -3)], [], panel['revision'])
    assert len(saved['dependencies']) == 2
    assert saved['dependencies'][0]['is_violated']
    assert not saved['dependencies'][1]['is_violated']
    assert links.query('SELECT id,project_id,task_name,start_date,end_date,phase,progress_pct,description FROM eppm.project_task ORDER BY id') == before
    assert links.query('SELECT * FROM eppm.task_dependencies') == []
    identity = saved['dependencies'][0]['id']
    updated = planning.save_project_dependencies(1, [link(kind='SS') | {'id': identity}], [], saved['revision'])
    assert not updated['dependencies'][0]['is_violated']
    assert len(planning.save_project_dependencies(1, [], [identity], updated['revision'])['dependencies']) == 1


def test_stale_predecessor_dates_reject_save_and_hidden_links_are_preserved(links):
    planning = service(links)
    with psycopg.connect(links.setup.operator_url) as c:
        c.execute('INSERT INTO eppm.project_dependency(project_id,predecessor_project_id,project_plan_id) VALUES (1,3,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))')
    panel = planning.get_project_dependency_panel(1)
    assert panel['dependencies'] == []
    panel = planning.save_project_dependencies(1, [link()], [], panel['revision'])
    with psycopg.connect(links.setup.operator_url) as c:
        c.execute("UPDATE eppm.project_task SET end_date='2026-01-18' WHERE id=2")
    with pytest.raises(PlanningConflictError, match='changed'):
        planning.save_project_dependencies(1, [], [panel['dependencies'][0]['id']], panel['revision'])
    with psycopg.connect(links.setup.operator_url) as c:
        assert c.execute('SELECT count(*) FROM eppm.project_dependency').fetchone() == (2,)


@pytest.mark.parametrize('values', [link(3), link(None, 3), link(1), link(None, 1)])
def test_invisible_and_self_predecessors_fail_without_mutation(links, values):
    planning = service(links)
    panel = planning.get_project_dependency_panel(1)
    with pytest.raises(ValueError):
        planning.save_project_dependencies(1, [values], [], panel['revision'])
    assert planning.get_project_dependency_panel(1) == panel


@pytest.mark.parametrize('sql', [
    'INSERT INTO eppm.project_dependency(project_id,predecessor_project_id,project_plan_id) VALUES (2,1,(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current))',
    'INSERT INTO eppm.project_dependency(project_id,predecessor_project_id,project_plan_id) VALUES (1,3,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))',
    'INSERT INTO eppm.project_dependency(project_id,predecessor_task_id,project_plan_id) VALUES (1,1,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))',
])
def test_native_constraints_and_authorization_reject_direct_invalid_writes(links, sql):
    with pytest.raises(psycopg.Error):
        links.query(sql, write=True)


def test_failed_batch_rolls_back_earlier_changes_and_cascade_preserves_whole_project_links(links):
    planning = service(links)
    panel = planning.save_project_dependencies(1, [link(), link(None, 2)], [], planning.get_project_dependency_panel(1)['revision'])
    identity = panel['dependencies'][0]['id']
    with pytest.raises(PlanningConflictError):
        planning.save_project_dependencies(1, [link(kind='SS') | {'id': 9999}], [identity], panel['revision'])
    assert planning.get_project_dependency_panel(1) == panel
    links.query('DELETE FROM eppm.project_task WHERE id=2', user_id=4, write=True)
    remaining = planning.get_project_dependency_panel(1)['dependencies']
    assert len(remaining) == 1 and not remaining[0]['is_evaluable']
    links.query('DELETE FROM eppm.project WHERE id=2', user_id=4, write=True)
    assert planning.get_project_dependency_panel(1)['dependencies'] == []


def test_project_summaries_tokens_filters_and_affected_owners_follow_project_links(links):
    planning = service(links)
    panel = planning.save_project_dependencies(1, [link()], [], planning.get_project_dependency_panel(1)['revision'])
    assert planning.get_project_summaries([1])[0]['hasViolations']
    assert planning.related_project_ids(1, 'predecessors') == [1, 2]
    assert planning.related_project_ids(2, 'all') == [1, 2]
    assert planning.affected_task_projects(2)[0] == {1, 2}
    with psycopg.connect(links.setup.operator_url) as c:
        c.execute("UPDATE eppm.project_task SET end_date='2026-01-09' WHERE id=2")
        c.execute('INSERT INTO eppm.project_dependency(project_id,predecessor_project_id,project_plan_id) VALUES (2,1,(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current)),(2,3,(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current)),(3,1,(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))')
    summary = planning.get_project_summaries([1])[0]
    assert not summary['hasViolations'] and len(summary['projectDependencies']) == 1
    assert planning.get_project_dependency_panel(1)['revision'] != panel['revision']
    assert planning.related_project_ids(1, 'all') == [1, 2]  # cycle terminates; hidden node cannot bridge
    assert service(links, 4).related_project_ids(1, 'all') == [1, 2, 3]


def test_inaccessible_link_ids_cannot_be_updated_or_deleted_and_revocation_rejects_save(links):
    planning = service(links)
    with psycopg.connect(links.setup.operator_url) as c:
        identity = c.execute('INSERT INTO eppm.project_dependency(project_id,predecessor_project_id,project_plan_id) VALUES (1,3,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)) RETURNING id').fetchone()[0]
    panel = planning.get_project_dependency_panel(1)
    for upserts, deletes in [([link() | {'id': identity}], []), ([], [identity])]:
        with pytest.raises(ValueError):
            planning.save_project_dependencies(1, upserts, deletes, panel['revision'])
    with psycopg.connect(links.setup.operator_url) as c:
        c.execute("DELETE FROM eppm.app_role_assignment WHERE user_id=1 AND role='project_editor'")
    with pytest.raises(ValueError):
        planning.save_project_dependencies(1, [link()], [], panel['revision'])


def test_second_editor_stale_save_cannot_overwrite_committed_changes(links):
    planning = service(links)
    first = planning.get_project_dependency_panel(1)
    second = planning.get_project_dependency_panel(1)
    saved = planning.save_project_dependencies(1, [link()], [], first['revision'])
    with pytest.raises(PlanningConflictError):
        planning.save_project_dependencies(1, [link(kind='SS')], [], second['revision'])
    assert planning.get_project_dependency_panel(1) == saved


def test_schedule_replacement_keeps_whole_project_links_and_removes_deleted_step_links(links):
    planning = service(links, 4)
    planning.save_project_dependencies(1, [link(), link(None, 2)], [], planning.get_project_dependency_panel(1)['revision'])
    before = planning.export_project_template(2)
    planning.replace_project_template(2, before)
    remaining = planning.get_project_dependency_panel(1)['dependencies']
    assert len(remaining) == 1 and remaining[0]['predecessor_project_id'] == 2
    planning.delete_milestone(1)
    links.query('DELETE FROM eppm.project WHERE id=1', user_id=4, write=True)
    assert links.query('SELECT * FROM eppm.project_dependency', user_id=4) == []


def test_concurrent_saves_recheck_revision_after_serialization_retry(links, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, local
    from app.infrastructure.postgresql.planning import PostgresPlanningStore

    planning = service(links)
    revision = planning.get_project_dependency_panel(1)['revision']
    barrier, state = Barrier(2), local()
    original = PostgresPlanningStore.project_dependency_revision

    def synchronized_revision(store, project_id):
        token = original(store, project_id)
        if not getattr(state, 'checked', False):
            state.checked = True
            barrier.wait(timeout=10)
        return token

    monkeypatch.setattr(PostgresPlanningStore, 'project_dependency_revision', synchronized_revision)

    def save(kind):
        try:
            planning.save_project_dependencies(1, [link(kind=kind)], [], revision)
            return 'saved'
        except PlanningConflictError:
            return 'stale'

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(save, ['FS', 'SS'])) == ['saved', 'stale']
    assert len(links.query('SELECT * FROM eppm.project_dependency')) == 1


@pytest.mark.parametrize('kind,gap', [('FS', -5), ('FF', 5), ('SS', 9), ('SF', 19)])
@pytest.mark.parametrize('step', [False, True])
def test_native_project_and_step_endpoints_apply_every_link_type_at_exact_lag_boundaries(links, kind, gap, step):
    planning = service(links)
    predecessor = link(None, 2, kind, gap) if step else link(2, None, kind, gap)
    saved = planning.save_project_dependencies(1, [predecessor], [], planning.get_project_dependency_panel(1)['revision'])
    assert saved['dependencies'][0]['is_evaluable'] and not saved['dependencies'][0]['is_violated']
    predecessor.update(id=saved['dependencies'][0]['id'], lag_days=gap + 1)
    changed = planning.save_project_dependencies(1, [predecessor], [], saved['revision'])
    assert changed['dependencies'][0]['is_violated']


def test_changed_successor_bounds_and_step_membership_refresh_project_warnings(links):
    planning = service(links, 4)
    saved = planning.save_project_dependencies(1, [link(kind='SS')], [], planning.get_project_dependency_panel(1)['revision'])
    assert not planning.get_project_summaries([1])[0]['hasViolations']
    planning.create_milestone(1, 'Earlier start', 'General', '2025-12-01', '2025-12-02', 0)
    assert planning.get_project_summaries([1])[0]['hasViolations']
    with psycopg.connect(links.setup.operator_url) as c:
        c.execute('UPDATE eppm.project_task SET project_id=3,project_plan_id=(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current) WHERE task_name=%s', ('Earlier start',))
    assert not planning.get_project_summaries([1])[0]['hasViolations']
    with pytest.raises(PlanningConflictError):
        planning.save_project_dependencies(1, [], [], saved['revision'])
