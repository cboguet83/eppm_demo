"""CSV revisions retain history and remain inactive under scoped permissions."""

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.domain.access.models import AccessDenied
from app.domain.planning.plans import PlanContent
from tests.postgresql.test_project_plans import service, draft_task


def test_editor_imports_inactive_draft_and_preserves_previous_revision(authorized):
    plans = service(authorized)
    previous = plans.initialize(1)
    saved = plans.import_revision(1, 'Imported', PlanContent(tasks=[draft_task()]))
    assert not saved.is_current and saved.status == 'draft'
    with pytest.raises(ValueError, match='remain inactive'):
        plans.import_revision(1, 'Cannot activate', PlanContent(), active=True)
    history = plans.list_plans(1)
    assert sum(plan.is_current for plan in history) == 1
    assert next(plan for plan in history if plan.id == previous.id).content == previous.content
    with pytest.raises(AccessDenied):
        plans.import_revision(1, 'Unauthorized approval', PlanContent(), status='approved')
    with pytest.raises(ValueError, match='version name'):
        plans.import_revision(1, ' ', PlanContent())
    assert len(plans.list_plans(1)) == len(history)


@pytest.mark.parametrize('user', [3, 4])
def test_privileged_import_can_choose_status_without_replacing_active_plan(authorized, user):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('''INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES(3,'project_approver',%s,900,'test')''', (Jsonb({'kind': 'projects', 'project_ids': [1]}),))
    plans = service(authorized, user)
    previous = next(plan for plan in plans.list_plans(1) if plan.is_current)
    saved = plans.import_revision(1, 'Approved import', PlanContent(tasks=[draft_task()]),
                                  status='approved', active=False)
    assert saved.status == 'approved' and not saved.is_current
    assert next(plan for plan in plans.list_plans(1) if plan.is_current).id == previous.id


def test_import_creates_first_plan_when_project_has_none(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.project_plan WHERE project_id=1')
    saved = service(authorized).import_revision(1, 'First import', PlanContent(tasks=[draft_task()]))
    assert saved.version == 1 and not saved.is_current and saved.status == 'draft'
    assert len(saved.content.tasks) == 1


def test_invalid_or_out_of_scope_import_preserves_current_selection(authorized):
    plans = service(authorized)
    before = plans.list_plans(1)
    with pytest.raises(AccessDenied):
        service(authorized, 2).import_revision(1, 'Forbidden', PlanContent())
    with pytest.raises(ValueError):
        plans.import_revision(1, 'Invalid dates', PlanContent(tasks=[
            draft_task(start='2027-02-01', end='2027-01-01')]))
    assert plans.list_plans(1) == before
