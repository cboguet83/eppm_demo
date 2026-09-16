"""Python-owned plan lifecycle, immutable saves and current-plan adoption."""

from copy import deepcopy
from dataclasses import replace

from app.application.exceptions import PlanningConflictError
from app.application.ports.planning import TaskChoice
from app.application.ports.project_plans import PlanGateway, PlanStore
from app.domain.access.models import AccessDenied
from app.domain.planning.plans import PlanContent, ProjectPlan, PlanTask, normalize_content, validate_status_change


class ProjectPlanService:
    """Manage complete project plans through one injected transaction boundary."""

    def __init__(self, gateway: PlanGateway) -> None:
        self._gateway = gateway

    def list_plans(self, project_id: int) -> list[ProjectPlan]:
        """Read accessible plan versions including archived history."""
        return self._gateway.run(lambda store: store.list_plans(project_id))

    def baseline_tasks(self, project_ids: list[int]) -> dict[int, list[PlanTask]]:
        """Read only baseline task lanes for the visible portfolio selection."""
        return self._gateway.run(lambda store: store.baseline_tasks(project_ids))

    def baseline_projects(self) -> list[int]:
        """List visible projects with a baseline, even when its chart lane is hidden."""
        return self._gateway.run(lambda store: store.baseline_projects())

    def current_content(self, project_id: int) -> PlanContent:
        """Read live tasks, dependencies, assignments and tags for the working schedule."""
        def operation(store: PlanStore) -> PlanContent:
            content = store.current_context([project_id], []).get(project_id)
            if content is None:
                raise AccessDenied()
            return content
        return self._gateway.run(operation)

    def baseline_current(self, project_id: int) -> ProjectPlan:
        """Freeze the live schedule on an explicit baseline action, never on drag."""
        def operation(store: PlanStore) -> ProjectPlan:
            store.lock_project(project_id)
            _, approver, admin = store.permissions(project_id)
            if not (approver or admin):
                raise AccessDenied()
            current = next((plan for plan in store.list_plans(project_id) if plan.is_current), None)
            if current is None:
                raise ValueError('Activate a plan before setting the baseline.')
            content = store.snapshot(project_id)
            previous = next((plan for plan in store.list_plans(project_id) if plan.is_baseline), None)
            if previous is not None and previous.content == content:
                return previous
            saved = store.insert(project_id, 'Current schedule baseline', 'approved', current.id, content)
            store.metadata(saved, 'baseline', 'true')
            return next(plan for plan in store.list_plans(project_id) if plan.id == saved.id)
        return self._gateway.run(operation, write=True)

    def dependency_context(self, contents: list[PlanContent]) -> dict[int, PlanContent]:
        """Batch-load only external predecessor projects' current schedules."""
        projects = {dep['predecessor_project_id'] for content in contents for dep in content.dependencies
                    if dep['predecessor_project_id'] is not None}
        tasks = {dep['predecessor_task_id'] for content in contents for dep in content.dependencies
                 if dep['predecessor_task_id'] is not None}
        return self._gateway.run(lambda store: store.current_context(list(projects), list(tasks)))

    def tag_choices(self) -> dict[int, str]:
        """Read existing tag names for plan task editing without catalog write rights."""
        return self._gateway.run(lambda store: store.tag_choices())

    def task_choices(self) -> list[TaskChoice]:
        """Read active dependency choices addressed by stable task identities."""
        return self._gateway.run(lambda store: store.task_choices())

    def versioned_projects(self) -> list[int]:
        """Return visible projects whose schedules are edited through new plans."""
        return self._gateway.run(lambda store: store.versioned_projects())

    def initialize(self, project_id: int) -> ProjectPlan:
        """Capture a newly created project's initial current plan exactly once."""
        def operation(store: PlanStore) -> ProjectPlan:
            store.lock_project(project_id)
            plans = store.list_plans(project_id)
            if plans:
                current = next((plan for plan in plans if plan.is_current), None)
                if current is None:
                    raise ValueError('Activate an existing plan before editing the schedule.')
                return current
            editor, _, admin = store.permissions(project_id)
            if not (editor or admin):
                raise AccessDenied()
            return store.insert(project_id, 'Initial plan', 'approved', None,
                                store.snapshot(project_id), current=True)
        return self._gateway.run(operation, write=True)

    def save(self, project_id: int, source_id: int, revision: int, name: str,
             content: PlanContent | None = None, status: str = 'proposed') -> ProjectPlan:
        """Save a revision, copying the source schedule and allocations by default."""
        return self.save_many([(project_id, source_id, revision, name, content, status)])[0]

    def save_many(self, drafts: list[tuple[int, int, int, str, PlanContent | None, str]]) -> list[ProjectPlan]:
        """Save all changed projects in one transaction, or keep every draft unsaved."""
        if len({item[0] for item in drafts}) != len(drafts):
            raise ValueError('Only one draft per project can be saved together.')
        def operation(store: PlanStore) -> list[ProjectPlan]:
            for project_id in sorted(item[0] for item in drafts):
                store.lock_project(project_id)
            result = []
            for project_id, source_id, revision, name, content, status in drafts:
                editor, _, admin = store.permissions(project_id)
                if not (editor or admin):
                    raise AccessDenied()
                if not isinstance(name, str) or not name.strip():
                    raise ValueError('Plan name is required.')
                if status not in {'draft', 'proposed'}:
                    raise ValueError('Save a new plan as Draft or Proposed before approval.')
                source = self._find(store, project_id, source_id, revision)
                if source.status == 'deleted':
                    raise ValueError('Restore the Deleted plan before copying it.')
                content = deepcopy(source.content if content is None else content)
                removed = {task['id'] for task in source.content.tasks} - {task['id'] for task in content.tasks}
                content = replace(content,
                    assignments=[row for row in content.assignments if row.task_id not in removed],
                    dependencies=[row for row in content.dependencies if row['task_id'] not in removed
                                  and row['predecessor_task_id'] not in removed],
                    task_tags={identity: tags for identity, tags in content.task_tags.items() if identity not in removed})
                normalized = normalize_content(project_id, content)
                store.validate_references(project_id, normalized)
                normalized = store.reserve_identities(normalized)
                result.append(store.insert(project_id, name.strip(), status, source.id, normalized))
            return result
        return self._gateway.run(operation, write=True)

    @staticmethod
    def _find(store: PlanStore, project_id: int, plan_id: int, revision: int) -> ProjectPlan:
        plan = next((row for row in store.list_plans(project_id) if row.id == plan_id), None)
        if plan is None:
            raise AccessDenied()
        if plan.revision != revision:
            raise PlanningConflictError('The plan changed. Reload before saving your changes.')
        return plan

    def change(self, project_id: int, plan_id: int, revision: int, action: str, value: str) -> None:
        """Audit an authorized status/current/baseline change without copying content."""
        def operation(store: PlanStore) -> None:
            store.lock_project(project_id)
            plan = self._find(store, project_id, plan_id, revision)
            editor, approver, admin = store.permissions(project_id)
            if action == 'status':
                validate_status_change(plan, value, editor=editor, approver=approver, admin=admin)
            elif action in {'current', 'baseline'}:
                if not (approver or admin):
                    raise AccessDenied()
                if plan.status != 'approved':
                    raise ValueError('Only Approved plans can be current or baseline.')
                if value not in {'true', 'false'}:
                    raise ValueError('Invalid plan designation.')
                if action == 'current' and value == 'true':
                    store.validate_references(project_id, plan.content)
                if action == 'baseline' and value == 'true' and plan.is_current:
                    plan = store.insert(project_id, plan.name + ' baseline', 'approved', plan.id, plan.content)
                elif action == 'current' and value == 'true' and plan.is_frozen:
                    plan = store.insert(project_id, plan.name + ' working copy', 'approved', plan.id, plan.content)
            else:
                raise ValueError('Unknown plan action.')
            store.metadata(plan, action, value)
            if action == 'current' and value == 'true':
                store.publish(plan)
        self._gateway.run(operation, write=True)
