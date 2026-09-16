"""Real CSV revisions preserve cross-plan identity without rewriting saved tasks."""

import csv
import io

import pytest

from app.application.services.planning import PlanningService
from app.domain.planning.plans import PlanContent
from app.domain.planning.schedule_template import export_template, parse_template, template_content
from app.infrastructure.postgresql.planning import PostgresPlanningGateway
from tests.postgresql.test_project_plans import service, draft_task


def test_active_and_alternative_exports_reimport_as_matching_task_rows(authorized):
    plans = service(authorized, 4)
    source = plans.import_revision(1, 'Original', PlanContent(tasks=[draft_task(-1), draft_task(-2, 'Build')],
        dependencies=[dict(task_id=-2, predecessor_task_id=-1, predecessor_project_id=None, link_type='FS', lag_days=2)]), status='approved')
    plans.change(1, source.id, source.revision, 'current', 'true')
    planning = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    rows = list(csv.DictReader(io.StringIO(planning.export_project_template(1))))
    stable = [task['id'] for task in source.content.tasks]
    assert [int(row['task_correlation_id']) for row in rows] == stable
    physical = [task['id'] for task in planning.get_milestones_by_project(1)]
    assert physical != stable
    rows[0]['task_name'] = 'Renamed through CSV'
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    imported = plans.import_revision(1, 'Revision', template_content(parse_template(output.getvalue())))
    assert [task['id'] for task in imported.content.tasks] == stable
    assert imported.content.dependencies == source.content.dependencies
    _, comparison = plans.comparison(1, imported.id)
    assert [task['id'] for task in comparison] == physical
    assert next(plan for plan in plans.list_plans(1) if plan.id == source.id).content == source.content
    again = template_content(parse_template(export_template(imported.content.tasks, imported.content.dependencies)))
    assert [task['id'] for task in again.tasks] == stable


def test_import_rejects_unknown_and_other_project_correlation_ids_atomically(authorized):
    plans = service(authorized, 4)
    foreign = plans.import_revision(2, 'Other project', PlanContent(tasks=[draft_task()]))
    before = plans.list_plans(1)
    for identity in [foreign.content.tasks[0]['id'], 9223372036854775807]:
        content = template_content(parse_template(f'step_number,task_correlation_id,task_name,start_date,end_date\n'
                                                 f'1,{identity},Task,2027-01-01,2027-01-02\n'))
        with pytest.raises(ValueError, match='does not belong'):
            plans.import_revision(1, 'Invalid', content)
        assert plans.list_plans(1) == before
