"""Real plan history, adoption, lifecycle authorization and immutable storage."""

from copy import deepcopy

import psycopg
import pytest

from app.application.exceptions import PlanningConflictError
from app.application.services.project_plans import ProjectPlanService
from app.domain.access.models import AccessDenied
from app.domain.planning.plans import PlanTask
from app.infrastructure.postgresql.project_plans import PostgresPlanGateway


def service(authorized, user=1):
    return ProjectPlanService(PostgresPlanGateway(authorized.database, authorized.key,
        access=authorized.binding(user).access))


def draft_task(identity=-1, name='Design', start='2027-01-01', end='2027-01-05'):
    return PlanTask(id=identity, task_name=name, phase='General', start_date=start,
                    end_date=end, description='')


def test_plan_save_approve_adopt_baseline_and_soft_delete_are_independent(authorized):
    editor, admin = service(authorized), service(authorized, 4)
    initial = editor.initialize(1)
    assert initial.is_current and initial.status == 'approved' and not initial.is_baseline
    content = deepcopy(initial.content)
    content.tasks.append(draft_task())
    proposed = editor.save(1, initial.id, initial.revision, 'Option A', content)
    assert proposed.status == 'proposed' and not proposed.is_current
    assert authorized.query('SELECT id FROM eppm.current_project_task') == []
    with pytest.raises(ValueError, match='approver'):
        editor.change(1, proposed.id, proposed.revision, 'status', 'approved')
    admin.change(1, proposed.id, proposed.revision, 'status', 'approved')
    approved = admin.list_plans(1)[0]
    admin.change(1, approved.id, approved.revision, 'baseline', 'true')
    approved = admin.list_plans(1)[0]
    admin.change(1, approved.id, approved.revision, 'current', 'true')
    adopted = admin.list_plans(1)[0]
    assert adopted.is_current and not adopted.is_baseline
    assert approved.is_baseline and approved.id != adopted.id
    assert authorized.query('SELECT task_name FROM eppm.current_project_task') == [('Design',)]
    admin.change(1, adopted.id, adopted.revision, 'status', 'deleted')
    old = next(plan for plan in admin.list_plans(1) if plan.id == initial.id)
    admin.change(1, old.id, old.revision, 'current', 'true')
    adopted = next(plan for plan in admin.list_plans(1) if plan.id == adopted.id)
    assert adopted.status == 'deleted' and not adopted.is_current
    deleted = admin.list_plans(1)[0]
    with pytest.raises(ValueError, match='Business Admin'):
        editor.change(1, deleted.id, deleted.revision, 'status', 'proposed')
    admin.change(1, deleted.id, deleted.revision, 'status', 'proposed')
    assert admin.list_plans(1)[0].content == proposed.content


def test_plan_scope_stale_metadata_and_atomic_multi_project_save(authorized):
    admin = service(authorized, 4)
    first, second = admin.initialize(1), admin.initialize(2)
    editor = service(authorized)
    assert service(authorized, 2).list_plans(1) == []
    with pytest.raises(AccessDenied):
        editor.save(2, second.id, second.revision, 'Denied', second.content)
    admin.change(1, first.id, first.revision, 'current', 'false')
    with pytest.raises(PlanningConflictError):
        editor.save(1, first.id, first.revision, 'Stale', first.content)
    current = admin.list_plans(1)[0]
    with pytest.raises(ValueError, match='name'):
        admin.save_many([(1, current.id, current.revision, 'Valid', current.content, 'proposed'),
                         (2, second.id, second.revision, '', second.content, 'proposed')])
    assert len(admin.list_plans(1)) == len(admin.list_plans(2)) == 1


def test_runtime_cannot_rewrite_saved_plan_contents(authorized):
    plans = service(authorized, 4)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(project_plan_id,project_id,task_name,start_date,end_date) VALUES(1,1,'Frozen','2027-01-01','2027-01-02')")
    plan = plans.baseline_current(1)
    assert authorized.query('UPDATE eppm.project_task SET task_name=%s WHERE project_plan_id=%s RETURNING id',
        ('Changed', plan.id), write=True) == []
    with pytest.raises(psycopg.errors.UndefinedColumn):
        authorized.database.run(lambda connection: connection.execute(
            "UPDATE eppm.project_plan SET content='{}' WHERE id=%s", (plan.id,)),
            write=True, bind=authorized.binding(1))


def test_scoped_approver_can_adopt_but_cannot_edit_plan_contents(authorized):
    from psycopg.types.json import Jsonb
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('''INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES(3,'project_approver',%s,900,'test')''', (Jsonb({'kind': 'projects', 'project_ids': [1]}),))
    editor, approver = service(authorized), service(authorized, 3)
    first = editor.initialize(1)
    content = deepcopy(first.content)
    content.tasks.append(draft_task())
    plan = editor.save(1, first.id, first.revision, 'Proposal', content)
    with pytest.raises(AccessDenied):
        approver.save(1, plan.id, plan.revision, 'Unauthorized edit', plan.content)
    approver.change(1, plan.id, plan.revision, 'status', 'approved')
    approved = approver.list_plans(1)[0]
    approver.change(1, approved.id, approved.revision, 'current', 'true')
    assert authorized.query('SELECT task_name FROM eppm.project_task') == [('Design',)]


def test_progress_survives_plan_removal_and_reintroduction_of_task(authorized):
    admin = service(authorized, 4)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date,progress_pct,project_plan_id) VALUES (1,'Task','2027-01-01','2027-01-02',65,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
    first = admin.initialize(1)
    empty = deepcopy(first.content)
    empty.tasks = []
    removed = admin.save(1, first.id, first.revision, 'Without task', empty)
    admin.change(1, removed.id, removed.revision, 'status', 'approved')
    removed = admin.list_plans(1)[0]
    admin.change(1, removed.id, removed.revision, 'current', 'true')
    first = next(row for row in admin.list_plans(1) if row.id == first.id)
    admin.change(1, first.id, first.revision, 'current', 'true')
    assert authorized.query('SELECT progress_pct FROM eppm.project_task') == [(65,)]


def test_plan_copy_preserves_hidden_dependencies_without_disclosing_endpoints(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (1,1,'Visible','2027-01-01','2027-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(2,3,'Hidden','2027-01-01','2027-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
        connection.execute('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES(1,2)')
        connection.execute("SELECT setval('eppm.project_task_id_seq',2)")
    admin, editor = service(authorized, 4), service(authorized)
    first = admin.initialize(1)
    visible = editor.list_plans(1)[0]
    assert visible.content.dependencies == []
    copied = editor.save(1, visible.id, visible.revision, 'Edited copy', visible.content)
    assert copied.content.dependencies == []
    assert admin.list_plans(1)[0].content.dependencies == first.content.dependencies
    changed = deepcopy(copied.content)
    changed.tasks[0]['task_name'] = 'Alternative edit with hidden predecessor'
    editor.update_alternative(1, copied.id, copied.revision, changed)
    assert admin.list_plans(1)[0].content.dependencies == first.content.dependencies


def test_current_menu_edits_preserve_saved_plan_and_baseline(authorized):
    from app.infrastructure.postgresql.planning import PostgresPlanningGateway
    from app.application.services.planning import PlanningService
    plans = service(authorized, 4)
    active = plans.initialize(1)
    initial = plans.baseline_current(1)
    planning = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key,
        access=authorized.binding(4).access))
    task_id = planning.create_milestone(1, 'New task', 'General', '2027-01-01', '2027-01-02', 0)
    assert planning.update_milestone(task_id, 'Edited task', 'General', '2027-01-02', '2027-01-03', 25)
    assert plans.current_content(1).tasks[0]['task_name'] == 'Edited task'
    saved = plans.list_plans(1)
    assert len(saved) == 2 and saved[0].is_baseline
    assert saved[0].content == initial.content
    assert saved[0].revision == initial.revision
    with pytest.raises(PlanningConflictError):
        plans.save(1, active.id, active.revision, 'Stale draft', active.content)
    assert planning.delete_milestone(task_id)
    assert plans.current_content(1).tasks == []
    assert authorized.query('SELECT id FROM eppm.current_project_task') == []


def test_current_tags_and_allocations_remain_editable_with_baseline(authorized):
    from dataclasses import replace
    from app.domain.resources.models import PoolAssignment
    from app.domain.tags.models import TaskTag
    from tests.postgresql.test_resource_pools import service as pool_service
    from tests.postgresql.test_tags import service as tag_service

    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date,project_plan_id) VALUES (1,'Task','2027-01-01','2027-01-05',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
        connection.execute("INSERT INTO eppm.resource_pool(name,capacity_fte) VALUES('Delivery',5)")
    plans = service(authorized, 4)
    baseline = plans.baseline_current(1)
    tags, pools = tag_service(authorized, 1), pool_service(authorized, 1)
    tag_id = tags.create_task_tag(TaskTag(task_id=1, free_tag='Original'))
    assert tags.update_task_tag(TaskTag(id=tag_id, task_id=1, free_tag='Changed'))
    allocation = PoolAssignment(pool_id=1, project_id=1, task_id=1, fte_assigned=1)
    allocation_id = pools.create_assignment(allocation)
    assert pools.update_assignment(replace(allocation, id=allocation_id, fte_assigned=2))
    working = plans.current_content(1)
    assert working.task_tags[1][0]['free_tag'] == 'Changed'
    assert working.assignments[0].fte_assigned == 2
    assert plans.list_plans(1)[0].content == baseline.content
    assert tags.delete_task_tag(tag_id)
    assert pools.delete_assignment(allocation_id)
    assert plans.current_content(1).task_tags == {}
    assert plans.current_content(1).assignments == []
    assert len(plans.list_plans(1)) == 2


def test_removed_cross_project_predecessor_remains_an_unresolved_plan_link(authorized):
    from app.domain.planning.plan_comparison import dependency_warnings
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (10,1,'Predecessor','2027-01-01','2027-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(20,2,'Consumer','2027-01-03','2027-01-04',(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current))")
        connection.execute('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES(20,10)')
        connection.execute('UPDATE eppm.project_task SET predecessor_id=10 WHERE id=20')
    admin = service(authorized, 4)
    first, consumer = admin.initialize(1), admin.initialize(2)
    empty = deepcopy(first.content)
    empty.tasks = []
    removed = admin.save(1, first.id, first.revision, 'Task removed', empty)
    admin.change(1, removed.id, removed.revision, 'status', 'approved')
    removed = admin.list_plans(1)[0]
    admin.change(1, removed.id, removed.revision, 'current', 'true')
    visible = admin.list_plans(2)[0]
    assert visible.content.dependencies == consumer.content.dependencies
    context = admin.dependency_context([visible.content])
    assert 'unavailable' in dependency_warnings(context | {2: visible.content})[2][0]
    old = next(row for row in admin.list_plans(1) if row.id == first.id)
    admin.change(1, old.id, old.revision, 'current', 'true')
    assert dependency_warnings(admin.dependency_context([visible.content]) | {2: visible.content})[2] == []


def test_initial_plan_captures_legacy_primary_link_and_free_text_tag(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (10,1,'First','2027-01-01','2027-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(20,1,'Second','2027-01-03','2027-01-04',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
        connection.execute('UPDATE eppm.project_task SET predecessor_id=10 WHERE id=20')
        connection.execute("INSERT INTO eppm.task_tag(task_id,free_tag) VALUES(20,'Critical')")
    plans = service(authorized, 4)
    first = plans.initialize(1)
    assert first.content.dependencies[0]['predecessor_task_id'] == 10
    assert first.content.task_tags[20] == [{'tag_id': None, 'free_tag': 'Critical'}]
    copied = plans.save(1, first.id, first.revision, 'Retained', first.content)
    assert copied.content == first.content


def test_project_creation_includes_initial_plan_in_the_project_transaction(authorized):
    from app.domain.projects.project import Project
    from app.infrastructure.postgresql.projects import PostgresProjectGateway
    gateway = PostgresProjectGateway(authorized.database, authorized.key, access=authorized.binding(4).access)
    identity = gateway.run(lambda store: store.insert(Project(name='New project')), write=True)
    plans = service(authorized, 4).list_plans(identity)
    assert len(plans) == 1 and plans[0].is_current and plans[0].status == 'approved'
    assert not plans[0].is_baseline and plans[0].content.tasks == []


def test_plan_assignments_remap_new_tasks_and_publish_only_on_adoption(authorized):
    from app.domain.resources.models import PoolAssignment
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(name,capacity_fte) VALUES('Delivery',5)")
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    content = deepcopy(initial.content)
    content.tasks.append(draft_task())
    content.assignments.append(PoolAssignment(1, 1, 2, task_id=-1,
        schedule_anchor='start', offset_days=2, duration_days=3))
    alternative = plans.save(1, initial.id, initial.revision, 'Resourced option', content)
    assert alternative.content.assignments[0].task_id == alternative.content.tasks[0]['id'] > 0
    assert authorized.query('SELECT id FROM eppm.current_resource_pool_assignment') == []
    plans.change(1, alternative.id, alternative.revision, 'status', 'approved')
    approved = plans.list_plans(1)[0]
    plans.change(1, approved.id, approved.revision, 'current', 'true')
    assert authorized.query('SELECT fte_assigned,schedule_anchor,offset_days,duration_days FROM eppm.current_resource_pool_assignment') == [(2, 'start', 2, 3)]
    previous = next(row for row in plans.list_plans(1) if row.id == initial.id)
    plans.change(1, previous.id, previous.revision, 'current', 'true')
    assert authorized.query('SELECT id FROM eppm.current_resource_pool_assignment') == []
    assert plans.list_plans(1)[0].content.assignments == alternative.content.assignments


def test_activation_preserves_another_projects_protected_primary_reference(authorized):
    from psycopg.types.json import Jsonb
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('''INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES(3,'project_approver',%s,900,'test')''', (Jsonb({'kind': 'projects', 'project_ids': [1]}),))
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (10,1,'First','2027-01-01','2027-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(20,3,'Protected','2027-01-03','2027-01-04',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
        connection.execute('UPDATE eppm.project_task SET predecessor_id=10 WHERE id=20')
    editor, approver = service(authorized), service(authorized, 3)
    initial = editor.initialize(1)
    content = deepcopy(initial.content)
    content.tasks = []
    alternative = editor.save(1, initial.id, initial.revision, 'Without predecessor', content)
    approver.change(1, alternative.id, alternative.revision, 'status', 'approved')
    approved = approver.list_plans(1)[0]
    approver.change(1, approved.id, approved.revision, 'current', 'true')
    assert next(row for row in approver.list_plans(1) if row.is_current).id == approved.id
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT predecessor_id FROM eppm.project_task WHERE id=20').fetchone() == (10,)


def test_direct_link_updates_and_deletions_keep_predecessor_edit_scope(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (10,1,'Editable','2027-01-01','2027-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(20,2,'Read only','2027-01-03','2027-01-04',(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current))")
        connection.execute('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES(10,20)')
    assert authorized.query("UPDATE eppm.task_dependencies SET link_type='SS' WHERE task_id=10 RETURNING id", write=True) == []
    assert authorized.query('DELETE FROM eppm.task_dependencies WHERE task_id=10 RETURNING id', write=True) == []
    assert authorized.query('SELECT link_type FROM eppm.task_dependencies WHERE task_id=10') == [('FS',)]
