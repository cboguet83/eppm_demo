"""Relational plan DTOs and Python lifecycle/comparison rules."""

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import TypedDict

from app.domain.planning.rules import normalize_task
from app.domain.resources.models import PoolAssignment
from app.domain.resources.rules import normalize_assignment
from app.domain.tags.models import TaskTag
from app.domain.tags.rules import normalize_task_tag


class PlanTask(TypedDict):
    """Stable task identity and versioned schedule; progress remains live."""

    id: int
    task_name: str
    phase: str
    start_date: str
    end_date: str
    description: str


class ComparisonTask(PlanTask):
    """Chart row identity paired with the stable identity used for scenario edits."""

    stable_id: int


class PlanDependency(TypedDict):
    """Incoming task/project dependency, addressed by stable endpoint IDs."""

    task_id: int | None
    predecessor_task_id: int | None
    predecessor_project_id: int | None
    link_type: str
    lag_days: int


class PlanTag(TypedDict):
    """Dictionary or free-text task tag, retained with the schedule version."""

    tag_id: int | None
    free_tag: str | None


@dataclass
class PlanContent:
    """Complete editable schedule copy, independent of database models."""

    tasks: list[PlanTask] = field(default_factory=list)
    dependencies: list[PlanDependency] = field(default_factory=list)
    assignments: list[PoolAssignment] = field(default_factory=list)
    task_tags: dict[int, list[PlanTag]] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectPlan:
    """Plan metadata and a detached copy of its current schedule content."""

    id: int
    project_id: int
    version: int
    name: str
    status: str
    source_plan_id: int | None
    is_current: bool
    is_baseline: bool
    revision: int
    author: str
    created_at: datetime
    content: PlanContent
    is_frozen: bool = False


STATUSES = ('draft', 'proposed', 'approved', 'rejected', 'deleted')


def validate_status_change(plan: ProjectPlan, status: str, *, editor: bool,
                           approver: bool, admin: bool) -> None:
    """Enforce lifecycle and designation rules independently of the frontend."""
    if status not in STATUSES:
        raise ValueError('Unknown plan status.')
    if plan.status == 'deleted' and not admin:
        raise ValueError('Only a Business Admin can change a Deleted plan status.')
    if (plan.is_current or plan.is_baseline) and status not in {'approved', 'deleted'}:
        raise ValueError('Move the current/baseline designation before changing status.')
    privileged = status in {'approved', 'rejected'} or plan.status == 'approved'
    if not admin and not (approver if privileged else editor):
        raise ValueError('This plan status change requires an approver.' if privileged
                         else 'Project edit permission is required.')


def normalize_content(project_id: int, content: PlanContent) -> PlanContent:
    """Validate a complete plan before any version is written."""
    tasks: list[PlanTask] = []
    identities: set[int] = set()
    for row in content.tasks:
        identity = row['id']
        if type(identity) is not int or identity == 0 or identity in identities:
            raise ValueError('Every task must have a unique, nonzero identity.')
        identities.add(identity)
        value = normalize_task(row)
        tasks.append(PlanTask(id=identity, **{key: value[key] for key in (
            'task_name', 'phase', 'start_date', 'end_date', 'description')}))
    dependencies = []
    for row in content.dependencies:
        if row['task_id'] is not None and row['task_id'] not in identities:
            raise ValueError('A dependency successor is absent from the plan.')
        if (row['predecessor_task_id'] is None) == (row['predecessor_project_id'] is None):
            raise ValueError('Select exactly one dependency predecessor.')
        if row['link_type'] not in {'FS', 'FF', 'SS', 'SF'} or type(row['lag_days']) is not int:
            raise ValueError('Invalid dependency type or lag.')
        if row['predecessor_task_id'] == row['task_id'] and row['task_id'] is not None:
            raise ValueError('A task cannot depend on itself.')
        if row['predecessor_project_id'] == project_id:
            raise ValueError('Select another project as the predecessor.')
        if row not in dependencies:
            dependencies.append(dict(row))
    assignments = []
    for row in content.assignments:
        if row.task_id is not None and row.task_id not in identities:
            raise ValueError('A resource assignment targets a task absent from the plan.')
        normalized = normalize_assignment(replace(row, project_id=project_id))
        try:
            start = date.fromisoformat(normalized.start_date) if normalized.start_date else None
            end = date.fromisoformat(normalized.end_date) if normalized.end_date else None
        except (TypeError, ValueError) as exc:
            raise ValueError('Assignment dates must use YYYY-MM-DD.') from exc
        if start and end and start > end:
            raise ValueError('Assignment start date cannot follow its stop date.')
        assignments.append(normalized)
    if set(content.task_tags) - identities:
        raise ValueError('A tag targets a task absent from the plan.')
    normalized_tags = {}
    for identity, tags in content.task_tags.items():
        values = []
        for tag in tags:
            # Temporary negative task IDs are remapped only after validation.
            value = normalize_task_tag(TaskTag(task_id=abs(identity), **tag))
            values.append(PlanTag(tag_id=value.tag_id, free_tag=value.free_tag))
        normalized_tags[identity] = values
    return PlanContent(tasks, dependencies, assignments, normalized_tags)


def compare_tasks(reference: PlanContent, alternative: PlanContent) -> list[dict]:
    """Align renamed tasks by identity and retain one-sided additions/removals."""
    before = {row['id']: row for row in reference.tasks}
    after = {row['id']: row for row in alternative.tasks}
    return [{'id': identity, 'reference': before.get(identity), 'alternative': after.get(identity),
             'change': ('added' if identity not in before else 'removed' if identity not in after
                        else 'changed' if before[identity] != after[identity] else 'unchanged')}
            for identity in sorted(before.keys() | after.keys(), key=lambda identity: (
                (after.get(identity) or before[identity])['start_date'], identity))]
