"""Real PostgreSQL scheduling, scope isolation and atomic schedule replacement."""

from tests.postgresql.plan_fixtures import seed_test_plans
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier, Event

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from app.application.exceptions import PlanningConflictError, PlanningStorageError
from app.application.services.planning import PlanningService
from app.domain.access.models import AccessDenied
from app.domain.planning.constraints import evaluate_constraints
from app.domain.planning.schedule_template import parse_template
from app.infrastructure.postgresql.planning import PostgresPlanningGateway


HEADER = 'step_number,task_name,start_date,end_date,progress_pct,preceding_step,dependency_type,dependency_lag\n'
TEMPLATE = HEADER + '1,New first,2026-01-01,2026-01-02,0,,,\n2,New second,2026-01-03,2026-01-04,50,1,FS,0\n'


def gateway(authorized, user_id=4):
    return PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(user_id).access)


def service(authorized, user_id=4):
    return PlanningService(gateway(authorized, user_id))


def create(planning, project_id=1, name='Task', **changes):
    values = dict(task_name=name, phase='Build', start_date='2026-01-01', end_date='2026-01-05', progress_pct=0)
    values.update(changes)
    return planning.create_milestone(project_id, **values)


@pytest.fixture
def schedule(authorized):
    planning = service(authorized)
    for project_id in (1, 2, 3):
        assert create(planning, project_id, f'Task {project_id}') == project_id
    return planning


def snapshot(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        return {table: connection.execute(sql.SQL('SELECT * FROM eppm.{} ORDER BY 1,2').format(sql.Identifier(table))).fetchall()
                for table in ('project_task', 'task_dependencies', 'resource_pool_assignment', 'task_tag')}


def decorate(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(name,capacity_fte) VALUES ('Shared',2),('Zero',1),('Private',1)")
        connection.execute('INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,project_plan_id) VALUES (1,1,1,0.5,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(1,1,NULL,0.25,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(2,1,1,0,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(3,3,3,1,(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))')
        connection.execute("INSERT INTO eppm.tag_dictionnary(tag) VALUES ('Visible'),('Private')")
        connection.execute('INSERT INTO eppm.task_tag(task_id,tag_id) VALUES (1,1),(3,2)')
        connection.execute('INSERT INTO eppm.project_tag(project_id,tag_id) VALUES (1,1),(3,2)')


def test_task_normalization_native_dates_and_complete_mutations(schedule, authorized):
    identity = create(schedule, name='  Milestone  ', phase=None, start_date=' 2026-01-07 ', end_date='2026-01-07',
                      progress_pct=120, description=' Notes ', predecessor_id=2)
    row = schedule.get_milestone_by_id(identity)
    assert (row['task_name'], row['phase'], row['description'], row['progress_pct']) == ('Milestone', 'General', 'Notes', 100)
    assert row['start_date'] == row['end_date'] == '2026-01-07'
    assert schedule.get_task_dependencies(identity)[0]['predecessor_task_id'] == 2
    assert authorized.query('SELECT start_date FROM eppm.project_task WHERE id=%s', (identity,)) == [(date(2026, 1, 7),)]
    assert schedule.update_dates(identity, '2026-01-08', '2026-01-10')
    assert schedule.update_progress(identity, -9)
    assert schedule.update_milestone(identity, 'Changed', 'Build', '2026-01-08', '2026-01-09', 45,
        dependencies=[{'predecessor_project_id': 2, 'link_type': 'bad', 'lag_days': 'bad'}, {'predecessor_task_id': identity}])
    links = schedule.get_task_dependencies(identity)
    assert len(links) == 1 and (links[0]['link_type'], links[0]['lag_days']) == ('FS', 0)
    assert schedule.get_milestone_by_id(identity)['predecessor_id'] is None
    assert not schedule.update_dates(999, '2026-01-01', '2026-01-02')
    assert not schedule.update_milestone(999, 'Missing', 'Build', '2026-01-01', '2026-01-02', 0)
    with pytest.raises(ValueError, match='no longer exists'):
        schedule.save_task_dependencies(999, [])
    before = snapshot(authorized)
    for action in (
        lambda: schedule.update_dates(identity, '2026-02-01', '2026-01-02'),
        lambda: create(schedule, name=' '),
        lambda: schedule.save_task_dependencies(identity, ['invalid']),
    ):
        with pytest.raises(ValueError):
            action()
        assert snapshot(authorized) == before


def test_hidden_predecessors_do_not_leak_into_reads_totals_metadata_or_warning_flags(schedule, authorized):
    decorate(authorized)
    schedule.update_milestone(1, 'Visible', 'Build', '2026-01-01', '2026-01-05', 0, predecessor_id=3)
    schedule.add_dependency(1, predecessor_project_id=3)
    schedule.add_dependency(1, predecessor_task_id=2, link_type='SS')
    reader = service(authorized, 1)
    assert reader.get_milestone_by_id(1)['predecessor_id'] is None
    assert reader.get_milestones_by_project(1)[0]['predecessor_name'] is None
    assert reader.get_milestone_by_id(3) is None and reader.get_milestones_by_project(3) == []
    assert [row['id'] for row in reader.get_all_milestones()] == [1, 2]
    assert [row['id'] for row in reader.get_milestones_for_projects([3, 1])] == [1]
    assert reader.get_totals() == dict(projects=2, tasks=2, dependencies=1, pools=2)
    assert len(reader.get_dependencies_for_projects([1, 3])) == 1
    assert reader.get_dependencies_for_projects([]) == reader.get_milestones_for_projects([]) == []
    assert reader.get_task_dependencies(3) == []
    assert reader.get_project_date_bounds(3) == (None, None)
    assert set(reader.get_all_project_date_bounds()) == {1, 2, '1', '2'}
    assert set(reader.get_all_external_tasks_map()) == {'1', '2'}
    assert set(reader.get_all_external_tasks_map([1])) == {'2'}
    assert reader.affected_task_projects(3) == (set(), set())
    assert reader.affected_task_projects(1) == ({1}, {1, 2})
    assert reader.consuming_pool_ids([1, 3]) == [1]
    assert reader.consuming_pool_ids([]) == []
    bundle = reader.read_task_bundle([3, 1])
    assert [row['id'] for row in bundle.tasks] == [1]
    assert bundle.project_names == {1: 'Editable'} and bundle.project_bounds == {'1': ('2026-01-01', '2026-01-05')}
    assert set(bundle.tags) == set(bundle.pools) == set(bundle.project_tags) == set(bundle.project_pools) == {1}
    assert bundle.tags[1][0]['tag_id'] == bundle.project_tags[1][0]['tag_id'] == 1
    assert not reader.get_project_summaries([1])[0]['hasViolations']
    assert schedule.get_project_summaries([1])[0]['hasViolations']
    assert reader.get_project_summaries([3]) == reader.get_project_summaries([]) == []
    with pytest.raises(AccessDenied):
        service(authorized, 3).get_totals()
    assert service(authorized, 2).read_task_bundle([1, 2]).project_names == {}
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query('SELECT predecessor_id FROM eppm.project_task')


def test_selectors_use_literal_search_exact_ids_and_bounded_visible_results(schedule, authorized):
    for name in ('100%_Done', 'plain', 'École'):
        create(schedule, name=name)
    reader = service(authorized, 1)
    assert [row['id'] for row in reader.search_task_choices('#2')] == [2]
    assert reader.search_task_choices('#3') == []
    assert [row['task_name'] for row in reader.search_task_choices('%_')] == ['100%_Done']
    assert [row['task_name'] for row in reader.search_task_choices('PLAIN')] == ['plain']
    assert reader.search_task_choices('école') == []
    assert len(reader.search_task_choices('Read only')) == 1
    rows = [dict(project_id=1, task_name=f'Batch {index}', start_date='2026-02-01', end_date='2026-02-02') for index in range(110)]
    assert reader.bulk_create_milestones(rows) == 110
    assert len(reader.search_task_choices(limit=1000)) == 100 and len(reader.search_task_choices(limit=0)) == 1


def test_recursive_scopes_stop_at_cycles_and_hidden_project_boundaries(schedule, authorized):
    schedule.add_dependency(1, predecessor_project_id=2)
    schedule.add_dependency(2, predecessor_task_id=1)
    schedule.add_dependency(3, predecessor_task_id=2)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        fourth = connection.execute("INSERT INTO eppm.project(name) VALUES ('Beyond hidden') RETURNING id").fetchone()[0]
        seed_test_plans(connection)
        from app.infrastructure.postgresql.seed_plan import ensure_operator_plan
        ensure_operator_plan(connection, fourth)
        connection.execute("""INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES (1,'project_viewer',%s,900,'test setup')""", (Jsonb({'kind': 'projects', 'project_ids': [fourth]}),))
    task = create(schedule, fourth)
    # A legacy primary edge is also traversed, without adding a modern link.
    authorized.query('UPDATE eppm.project_task SET predecessor_id=3 WHERE id=%s', (task,), user_id=4, write=True)
    assert schedule.related_project_ids(1, 'this') == [1]
    assert schedule.related_project_ids(1, 'predecessors') == [1, 2]
    assert schedule.related_project_ids(task, 'predecessors') == [1, 2, 3, fourth]
    assert schedule.related_project_ids(1, 'all') == [1, 2, 3, fourth]
    assert schedule.related_project_ids([], 'all') == []
    reader = service(authorized, 1)
    assert reader.related_project_ids([1, 2, 3, fourth], 'this') == [1, 2, fourth]
    assert reader.related_project_ids(1, 'all') == reader.related_project_ids(1, 'predecessors') == [1, 2]
    assert reader.related_project_ids(fourth, 'predecessors') == [fourth]
    assert reader.related_project_ids(3, 'all') == []
    assert schedule.affected_task_projects(2) == ({1, 2, 3}, set())


def test_endpoint_edit_permissions_and_hidden_foreign_keys_prevent_destructive_partial_saves(schedule, authorized):
    reader = service(authorized, 1)
    before = snapshot(authorized)
    for action in (
        lambda: reader.add_dependency(1, predecessor_task_id=2),
        lambda: reader.update_dates(2, '2026-01-10', '2026-01-11'),
        lambda: create(reader, 3),
        lambda: reader.bulk_create_milestones([dict(project_id=1, task_name='Rollback', start_date='2026-01-01', end_date='2026-01-02'),
                                              dict(project_id=2, task_name='Denied', start_date='2026-01-01', end_date='2026-01-02')]),
    ):
        with pytest.raises(AccessDenied):
            action()
        assert snapshot(authorized) == before
    schedule.add_dependency(3, predecessor_task_id=1)
    before = snapshot(authorized)
    with pytest.raises(PlanningConflictError):
        reader.delete_milestone(1)
    with pytest.raises(PlanningConflictError):
        reader.replace_project_template(1, TEMPLATE)
    assert snapshot(authorized) == before
    assert reader.update_progress(1, 25)
    assert schedule.delete_milestone(1)
    assert schedule.get_task_dependencies(3) == []


@pytest.mark.parametrize('link_type', ['FS', 'FF', 'SS', 'SF'])
@pytest.mark.parametrize('lag', [-2, 0, 2])
@pytest.mark.parametrize('whole_project', [False, True])
def test_sql_summary_matches_domain_rules_for_all_link_types_and_signed_lags(schedule, link_type, lag, whole_project):
    schedule.update_dates(1, '2026-01-02', '2026-01-04')
    schedule.update_progress(1, 40)
    endpoint = {'predecessor_project_id': 2} if whole_project else {'predecessor_task_id': 2}
    schedule.add_dependency(1, **endpoint, link_type=link_type, lag_days=lag)
    bundle = schedule.read_task_bundle([1])
    evaluated, warnings = evaluate_constraints(bundle.tasks, bundle.dependencies, bundle.project_bounds)
    summary, = schedule.get_project_summaries([1])
    assert summary == dict(id=1, name='Editable', start='2026-01-02', end='2026-01-04', taskCount=1,
                           progress=40.0, hasViolations=evaluated[0]['is_violated'])
    assert summary['hasViolations'] == bool(warnings[1])


def test_summary_empty_dates_task_endpoint_precedence_and_full_template_lag_range(schedule, authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        empty = connection.execute("INSERT INTO eppm.project(name) VALUES ('Empty') RETURNING id").fetchone()[0]
        seed_test_plans(connection)
    assert schedule.get_project_summaries([empty]) == [dict(id=empty, name='Empty', start=None, end=None,
                                                           taskCount=0, progress=0.0, hasViolations=False)]
    schedule.update_dates(3, '2027-01-01', '2027-01-02')
    schedule.add_dependency(1, predecessor_task_id=2, predecessor_project_id=3, link_type='SS')
    assert not schedule.get_project_summaries([1])[0]['hasViolations']
    schedule.save_task_dependencies(1, [{'predecessor_project_id': empty}])
    assert not schedule.get_project_summaries([1])[0]['hasViolations']
    for lag in (-(2**63), 2**63 - 1):
        content = TEMPLATE.replace('1,FS,0', f'1,FS,{lag}')
        assert schedule.replace_project_template(1, content) == 2
        assert schedule.get_project_summaries([1])[0]['hasViolations'] == (lag > 0)
        assert parse_template(schedule.export_project_template(1))[1].dependencies[0].lag_days == lag


class GatedGateway(PostgresPlanningGateway):
    def __init__(self, authorized, barrier, attempts, index):
        super().__init__(authorized.database, authorized.key, access=authorized.binding(4).access)
        self.barrier, self.attempts, self.index = barrier, attempts, index

    def run(self, operation, **options):
        def callback(store):
            self.attempts[self.index] += 1
            if self.attempts[self.index] == 1:
                self.barrier.wait(timeout=10)
            return operation(store)
        return super().run(callback, **options)


def test_concurrent_replacements_replay_entire_templates_without_mixing_fresh_task_identities(schedule, authorized):
    decorate(authorized)
    barrier, attempts = Barrier(2), [0, 0]
    def save(index):
        actor_service = PlanningService(GatedGateway(authorized, barrier, attempts, index))
        return actor_service.replace_project_template(1, TEMPLATE.replace('New', f'Writer {index}'))
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(save, range(2))) == [2, 2]
    assert sum(attempts) >= 3
    tasks = schedule.get_milestones_by_project(1)
    assert len(tasks) == 2 and tasks[0]['task_name'].split()[:2] == tasks[1]['task_name'].split()[:2]
    link, = schedule.get_dependencies_for_project(1)
    assert (link['task_id'], link['predecessor_task_id']) == (tasks[1]['id'], tasks[0]['id'])
    assert authorized.query('SELECT id FROM eppm.resource_pool_assignment WHERE project_id=1') == []


def test_concurrent_date_and_progress_commands_keep_both_changes(schedule, authorized):
    barrier, attempts = Barrier(2), [0, 0]
    def save(index):
        actor_service = PlanningService(GatedGateway(authorized, barrier, attempts, index))
        return actor_service.update_dates(1, '2026-02-01', '2026-02-07') if index == 0 else actor_service.update_progress(1, 75)
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert all(executor.map(save, range(2)))
    row = schedule.get_milestone_by_id(1)
    assert (row['start_date'], row['end_date'], row['progress_pct']) == ('2026-02-01', '2026-02-07', 75)
    assert sum(attempts) >= 3


def test_read_bundle_and_headers_share_repeatable_read_snapshot_during_replacement(schedule, authorized):
    decorate(authorized)
    schedule.add_dependency(1, predecessor_task_id=2)
    ready, changed = Event(), Event()
    def read():
        def operation(store):
            tasks = store.get_milestones_by_project(1)
            assert store.connection.execute('SHOW transaction_isolation').fetchone()[0] == 'repeatable read'
            ready.set()
            assert changed.wait(timeout=10)
            return tasks, store.read_task_bundle([1]), store.get_project_summaries([1])
        return gateway(authorized).run(operation)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(read)
        assert ready.wait(timeout=10)
        try:
            schedule.replace_project_template(1, TEMPLATE)
        finally:
            changed.set()
        tasks, bundle, headers = future.result()
    assert tasks == bundle.tasks and tasks[0]['id'] == 1
    assert len(bundle.dependencies) == 1 and bundle.tags[1] and bundle.pools[1] and bundle.project_pools[1]
    assert headers[0]['taskCount'] == 1
    assert len(schedule.read_task_bundle([1]).tasks) == 2


@pytest.mark.parametrize('kind', ['create', 'update', 'dependencies', 'bulk'])
def test_known_rollback_replays_with_original_nested_command_inputs(schedule, authorized, kind):
    submitted = [{'predecessor_task_id': 2, 'link_type': 'SS', 'lag_days': -2}]
    rows = [dict(project_id=1, task_name='Kept', start_date='2026-01-01', end_date='2026-01-05')]
    attempts = []
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('CREATE SEQUENCE eppm.schedule_attempt')
        connection.execute('GRANT USAGE ON SEQUENCE eppm.schedule_attempt TO eppm_runtime')
        connection.execute("""CREATE FUNCTION eppm.retry_schedule_once() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF nextval('eppm.schedule_attempt')=1 THEN RAISE EXCEPTION 'Known rollback' USING ERRCODE='40001'; END IF;
            RETURN NEW; END $$""")
        table = 'project_task' if kind == 'bulk' else 'task_dependencies'
        connection.execute(sql.SQL('CREATE TRIGGER retry_schedule_once BEFORE INSERT ON eppm.{} '
                                   'FOR EACH ROW EXECUTE FUNCTION eppm.retry_schedule_once()').format(sql.Identifier(table)))
    class ChangedInputGateway(PostgresPlanningGateway):
        def run(self, operation, **options):
            def callback(store):
                attempts.append(1)
                if len(attempts) == 2:
                    submitted[0]['predecessor_task_id'] = 999
                    rows[0]['task_name'] = 'Changed outside callback'
                    rows.append(dict(rows[0]))
                return operation(store)
            return super().run(callback, **options)
    actor_service = PlanningService(ChangedInputGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    if kind == 'bulk':
        assert actor_service.bulk_create_milestones(rows) == 1
        assert [row['task_name'] for row in schedule.get_milestones_by_project(1)] == ['Task 1', 'Kept']
    else:
        identity = 1
        if kind == 'create':
            identity = create(actor_service, name='Kept', dependencies=submitted)
        elif kind == 'update':
            assert actor_service.update_milestone(1, 'Kept', 'Build', '2026-01-01', '2026-01-05', 25, dependencies=submitted)
        else:
            actor_service.save_task_dependencies(1, submitted)
        link, = schedule.get_task_dependencies(identity)
        assert (link['predecessor_task_id'], link['link_type'], link['lag_days']) == (2, 'SS', -2)
    assert len(attempts) == 2


def test_storage_outage_is_safe_and_does_not_expose_credentials(schedule, authorized, caplog):
    authorized.database.close()
    with pytest.raises(PlanningStorageError, match='could not be accessed') as failure:
        schedule.get_totals()
    assert 'postgresql://' not in str(failure.value) + caplog.text


def test_external_template_references_are_revalidated_and_hidden_links_are_never_exported(schedule, authorized):
    content = TEMPLATE.replace('1,FS,0', '1;task:2;project:3,FS;SS;FF,0;-2;3')
    assert len(schedule.validate_project_template(1, content)) == 2
    assert schedule.replace_project_template(1, content) == 2
    exported = schedule.export_project_template(1)
    assert {dependency.kind for step in parse_template(exported) for dependency in step.dependencies} == {'step', 'task', 'project'}
    reader = service(authorized, 1)
    assert 'project:3' not in reader.export_project_template(1)
    before = snapshot(authorized)
    with pytest.raises(ValueError, match='Predecessor project'):
        reader.validate_project_template(1, content)
    assert snapshot(authorized) == before
    with pytest.raises(ValueError, match='no longer exists'):
        schedule.export_project_template(999)
    with pytest.raises(ValueError, match='no longer exists'):
        gateway(authorized).run(lambda store: PlanningService._validate_template_references(store, 999, parse_template(content)))


def test_date_style_nullable_legacy_fields_and_csv_keep_existing_boundary_formats(schedule, authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project_task SET phase=NULL,description=NULL,progress_pct=NULL WHERE id=1')
    def read(store):
        store.connection.execute("SET LOCAL DateStyle='SQL, DMY'")
        return store.get_milestone_by_id(1), store.get_project_summaries([1])
    task, summaries = gateway(authorized).run(read)
    assert (task['start_date'], task['end_date']) == ('2026-01-01', '2026-01-05')
    assert task['phase'] is task['description'] is task['progress_pct'] is None
    assert summaries[0]['progress'] == 0.0
    assert schedule.update_milestone(1, 'Edited', task['phase'], task['start_date'], task['end_date'], 0, description=task['description'])
    assert schedule.get_milestone_by_id(1)['phase'] == 'General'
    assert schedule.import_csv(1, 'task_name,start_date,end_date,progress_pct\nImported,2026-02-01,2026-02-02,101\n') == 1
    assert schedule.get_milestones_by_project(1)[-1]['progress_pct'] == 100


def test_editing_visible_links_preserves_hidden_links_and_protects_primary_predecessor(schedule, authorized):
    schedule.update_milestone(1, 'Visible', 'Build', '2026-01-01', '2026-01-05', 0, predecessor_id=3)
    other = create(schedule, name='Local')
    reader = service(authorized, 1)
    reader.save_task_dependencies(1, [{'predecessor_task_id': other}])
    assert {row['predecessor_task_id'] for row in schedule.get_task_dependencies(1)} == {3, other}
    assert {row['predecessor_task_id'] for row in reader.get_task_dependencies(1)} == {other}
    assert reader.update_dates(1, '2026-02-01', '2026-02-05')
    before = snapshot(authorized)
    with pytest.raises(AccessDenied):
        reader.update_milestone(1, 'Denied', 'Build', '2026-02-01', '2026-02-05', 0, predecessor_id=None)
    assert snapshot(authorized) == before
    assert schedule.get_milestone_by_id(1)['predecessor_id'] == 3


def test_replacement_cleans_related_links_tags_and_allocations_and_round_trips_template(schedule, authorized):
    decorate(authorized)
    schedule.add_dependency(1, predecessor_task_id=2)
    schedule.add_dependency(2, predecessor_project_id=1)
    schedule.update_milestone(3, 'Consumer', 'Build', '2026-01-01', '2026-01-05', 0, predecessor_id=1)
    assert len(schedule.validate_project_template(1, TEMPLATE)) == 2
    assert schedule.replace_project_template(1, TEMPLATE) == 2
    tasks = schedule.get_milestones_by_project(1)
    assert [row['task_name'] for row in tasks] == ['New first', 'New second']
    assert schedule.get_task_dependencies(tasks[1]['id'])[0]['predecessor_task_id'] == tasks[0]['id']
    assert schedule.get_task_dependencies(2) == schedule.get_task_dependencies(3) == []
    assert schedule.get_milestone_by_id(3)['predecessor_id'] is None
    assert authorized.query('SELECT id FROM eppm.resource_pool_assignment WHERE project_id=1') == []
    assert authorized.query('SELECT task_id FROM eppm.task_tag') == []
    exported = schedule.export_project_template(1)
    assert schedule.replace_project_template(1, exported) == 2
    assert schedule.export_project_template(1) == exported
    assert 'New first' in schedule.export_schedule(1)
    assert schedule.get_milestone_by_id(tasks[0]['id']) is None
    for reference in ('task:1', 'project:1', 'task:999', 'project:999'):
        before = snapshot(authorized)
        with pytest.raises(ValueError):
            schedule.replace_project_template(1, TEMPLATE.replace('1,FS,0', f'{reference},FS,0'))
        assert snapshot(authorized) == before
    assert len(parse_template(schedule.export_project_template(1))) == 2


@pytest.mark.parametrize('kind', ['replacement', 'create', 'update'])
def test_late_dependency_failure_rolls_back_complete_schedule_operation(schedule, authorized, kind):
    decorate(authorized)
    schedule.add_dependency(1, predecessor_task_id=2)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_schedule_link() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Rejected link' USING ERRCODE='23514'; END $$""")
        connection.execute('CREATE TRIGGER reject_schedule_link BEFORE INSERT ON eppm.task_dependencies '
                           'FOR EACH ROW EXECUTE FUNCTION eppm.reject_schedule_link()')
    before = snapshot(authorized)
    with pytest.raises(PlanningConflictError):
        if kind == 'replacement':
            schedule.replace_project_template(1, TEMPLATE)
        elif kind == 'create':
            create(schedule, name='Rolled back', dependencies=[{'predecessor_task_id': 2}])
        else:
            schedule.update_milestone(1, 'Rolled back', 'Build', '2026-01-02', '2026-01-05', 100,
                                      dependencies=[{'predecessor_task_id': 3}])
    assert snapshot(authorized) == before
