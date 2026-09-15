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
    assert authorized.query('SELECT id FROM eppm.project_task') == []
    with pytest.raises(ValueError, match='approver'):
        editor.change(1, proposed.id, proposed.revision, 'status', 'approved')
    admin.change(1, proposed.id, proposed.revision, 'status', 'approved')
    approved = admin.list_plans(1)[0]
    admin.change(1, approved.id, approved.revision, 'baseline', 'true')
    approved = admin.list_plans(1)[0]
    admin.change(1, approved.id, approved.revision, 'current', 'true')
    adopted = admin.list_plans(1)[0]
    assert adopted.is_current and adopted.is_baseline
    assert authorized.query('SELECT task_name FROM eppm.project_task') == [('Design',)]
    with pytest.raises(ValueError, match='designation'):
        admin.change(1, adopted.id, adopted.revision, 'status', 'deleted')
    old = next(plan for plan in admin.list_plans(1) if plan.id == initial.id)
    admin.change(1, old.id, old.revision, 'current', 'true')
    adopted = next(plan for plan in admin.list_plans(1) if plan.id == adopted.id)
    assert adopted.is_baseline and not adopted.is_current
    admin.change(1, adopted.id, adopted.revision, 'baseline', 'false')
    adopted = admin.list_plans(1)[0]
    admin.change(1, adopted.id, adopted.revision, 'status', 'deleted')
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
    admin.change(1, first.id, first.revision, 'baseline', 'true')
    with pytest.raises(PlanningConflictError):
        editor.save(1, first.id, first.revision, 'Stale', first.content)
    current = admin.list_plans(1)[0]
    with pytest.raises(ValueError, match='name'):
        admin.save_many([(1, current.id, current.revision, 'Valid', current.content, 'proposed'),
                         (2, second.id, second.revision, '', second.content, 'proposed')])
    assert len(admin.list_plans(1)) == len(admin.list_plans(2)) == 1


def test_runtime_cannot_rewrite_saved_plan_contents(authorized):
    plan = service(authorized).initialize(1)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.database.run(lambda connection: connection.execute(
            "UPDATE eppm.project_plan SET content='{}' WHERE id=%s", (plan.id,)),
            write=True, bind=authorized.binding(1))
