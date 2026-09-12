"""Task and dependency use cases with atomic writes and pure scheduling rules."""

from copy import deepcopy

from app.domain.access.models import Permission


from app.application.ports.planning import (
    ExternalTask,
    PlanningGateway,
    PlanningStore,
    PlanningTaskBundle,
    PlanningTotals,
    ProjectSummary,
    TaskChoice,
    TaskRow,
)
from app.domain.planning.csv_import import parse_csv
from app.domain.planning.csv_export import export_schedule
from app.domain.planning.schedule_template import TemplateStep, export_template, parse_template
from app.domain.planning.records import (
    DependencyInput,
    DependencySchedule,
    ProjectBounds,
    TaskInput,
    TaskValues,
)
from app.domain.planning.rules import (
    normalize_dates,
    normalize_dependency,
    normalize_progress,
    normalize_task,
)


def _replace_dependencies(
    store: PlanningStore,
    task_id: int,
    dependencies: list[DependencyInput] | None,
    predecessor_id: int | None,
) -> None:
    if dependencies is None:
        if predecessor_id is None:
            return
        dependencies = [DependencyInput(predecessor_task_id=predecessor_id)]
    if not isinstance(dependencies, list):
        raise ValueError("Invalid dependency selection.")
    normalized = [
        item for dep in dependencies if (item := normalize_dependency(task_id, dep)) is not None
    ]
    store.replace_dependencies(task_id, normalized)


class PlanningService:
    """Validate task commands and keep task/dependency changes in one transaction."""

    def __init__(self, gateway: PlanningGateway) -> None:
        """Inject storage without opening a connection."""
        self._gateway = gateway

    def get_totals(self) -> PlanningTotals:
        """Read totals after filtering projects, tasks, links and allocation owners."""
        return self._gateway.run(lambda store: store.get_totals())

    def create_milestone(
        self,
        project_id: int,
        task_name: str,
        phase: str,
        start_date: str,
        end_date: str,
        progress_pct: int,
        predecessor_id: int | None = None,
        dependencies: list[DependencyInput] | None = None,
        description: str | None = None,
    ) -> int:
        """Create a task and its initial predecessors atomically."""
        dependencies = deepcopy(dependencies)
        values = normalize_task(
            TaskValues(
                task_name=task_name,
                phase=phase,
                start_date=start_date,
                end_date=end_date,
                progress_pct=progress_pct,
                predecessor_id=predecessor_id,
                description=description or "",
            )
        )
        def operation(store: PlanningStore) -> int:
            task_id = store.create_task(project_id, values)
            _replace_dependencies(store, task_id, dependencies, predecessor_id)
            return task_id
        return self._gateway.run(operation, write=True, permission=Permission.EDIT, project_ids=[project_id])

    def export_schedule(self, project_id: int) -> str:
        """Export the project's chronological schedule with consecutive step numbers."""
        return self._gateway.run(lambda store: export_schedule(store.get_milestones_by_project(project_id)))

    def export_project_template(self, project_id: int) -> str:
        """Read a consistent editable task/dependency template for one project."""
        def operation(store: PlanningStore) -> str:
            if not store.project_exists(project_id):
                raise ValueError("The selected project no longer exists.")
            return export_template(store.get_milestones_by_project(project_id), store.get_dependencies_for_project(project_id))
        return self._gateway.run(operation)

    @staticmethod
    def _validate_template_references(store: PlanningStore, project_id: int, steps: list[TemplateStep]) -> None:
        """Reject stale external references before deleting any existing schedule data."""
        if not store.project_exists(project_id):
            raise ValueError("The selected project no longer exists.")
        task_ids = {dep.identity for step in steps for dep in step.dependencies if dep.kind == "task"}
        project_ids = {dep.identity for step in steps for dep in step.dependencies if dep.kind == "project"}
        valid_tasks, valid_projects = store.valid_template_references(project_id, task_ids, project_ids)
        for step in steps:
            for dep in step.dependencies:
                if dep.kind == "task" and dep.identity not in valid_tasks:
                    raise ValueError(f"Step {step.number}: External task {dep.identity} is missing or belongs to this project; use a step reference for local tasks.")
                if dep.kind == "project" and dep.identity not in valid_projects:
                    raise ValueError(f"Step {step.number}: Predecessor project {dep.identity} is missing or refers to this project.")

    def validate_project_template(self, project_id: int, content: str, *, date_format: str = "YYYY-MM-DD") -> list[TemplateStep]:
        """Preview a fully validated replacement without changing stored data."""
        steps = parse_template(content, date_format=date_format)
        def operation(store: PlanningStore) -> None:
            self._validate_template_references(store, project_id, steps)
        self._gateway.run(operation, permission=Permission.EDIT, project_ids=[project_id])
        return steps

    def replace_project_template(self, project_id: int, content: str, *, date_format: str = "YYYY-MM-DD") -> int:
        """Validate first, then replace tasks, links and allocations atomically."""
        steps = parse_template(content, date_format=date_format)
        def operation(store: PlanningStore) -> None:
            self._validate_template_references(store, project_id, steps)
            store.clear_project_schedule(project_id)
            identities = {step.number: store.create_task(project_id, step.values) for step in steps}
            for step in steps:
                for dep in step.dependencies:
                    values = DependencyInput(link_type=dep.link_type, lag_days=dep.lag_days)
                    if dep.kind == "project":
                        values["predecessor_project_id"] = dep.identity
                    else:
                        values["predecessor_task_id"] = identities[dep.identity] if dep.kind == "step" else dep.identity
                    store.insert_dependency(identities[step.number], values)
        self._gateway.run(operation, write=True, permission=Permission.EDIT, project_ids=[project_id])
        return len(steps)

    def related_project_ids(self, project_id: int | list[int], scope: str = "this") -> list[int]:
        """Return this project, its predecessor closure, or its full dependency closure."""
        project_id = list(project_id) if isinstance(project_id, list) else project_id
        if scope not in {"this", "predecessors", "all"}:
            raise ValueError("Unknown project filter scope.")
        return self._gateway.run(lambda store: store.related_project_ids(project_id, scope))

    def update_milestone(
        self,
        milestone_id: int,
        task_name: str,
        phase: str,
        start_date: str,
        end_date: str,
        progress_pct: int,
        predecessor_id: int | None = None,
        dependencies: list[DependencyInput] | None = None,
        description: str | None = None,
    ) -> bool:
        """Update task details and requested predecessors together, or change neither."""
        dependencies = deepcopy(dependencies)
        values = normalize_task(
            TaskValues(
                task_name=task_name,
                phase=phase,
                start_date=start_date,
                end_date=end_date,
                progress_pct=progress_pct,
                predecessor_id=predecessor_id,
                description=description or "",
            ),
            task_id=milestone_id,
        )
        def operation(store: PlanningStore) -> bool:
            if not store.update_task(milestone_id, values):
                return False
            _replace_dependencies(store, milestone_id, dependencies, predecessor_id)
            return True
        return self._gateway.run(operation, write=True)

    def save_task_dependencies(self, task_id: int, dependencies: list[DependencyInput]) -> None:
        """Replace incoming links atomically, preserving existing normalization defaults."""
        dependencies = deepcopy(dependencies)
        def operation(store: PlanningStore) -> None:
            if store.get_milestone_by_id(task_id) is None:
                raise ValueError("The task no longer exists.")
            _replace_dependencies(store, task_id, dependencies, None)
        self._gateway.run(operation, write=True)

    def add_dependency(
        self,
        task_id: int,
        predecessor_task_id: int | None = None,
        predecessor_project_id: int | None = None,
        link_type: str = "FS",
        lag_days: int = 0,
    ) -> None:
        """Add a normalized predecessor; empty or self links retain their no-op behavior."""
        dependency = normalize_dependency(
            task_id,
            DependencyInput(
                predecessor_task_id=predecessor_task_id,
                predecessor_project_id=predecessor_project_id,
                link_type=link_type,
                lag_days=lag_days,
            ),
        )
        if dependency is None:
            return
        def operation(store: PlanningStore) -> None:
            store.insert_dependency(task_id, dependency)
        self._gateway.run(operation, write=True)

    def update_dates(self, milestone_id: int, start_date: str, end_date: str) -> bool:
        """Validate a drag command before changing the schedule."""
        start, end = normalize_dates(start_date, end_date)
        return self._gateway.run(lambda store: store.update_dates(milestone_id, start, end), write=True)

    def update_progress(self, milestone_id: int, progress_pct: int) -> bool:
        """Retain the established progress clamp at the authoritative boundary."""
        progress = normalize_progress(progress_pct)
        return self._gateway.run(lambda store: store.update_progress(milestone_id, progress), write=True)

    def bulk_create_milestones(self, rows: list[TaskInput]) -> int:
        """Validate the entire import and insert all rows in one transaction."""
        if not rows:
            return 0
        prepared = [TaskInput(**normalize_task(row), project_id=row["project_id"]) for row in rows]
        return self._gateway.run(lambda store: store.bulk_create_milestones(prepared), write=True)

    def import_csv(self, project_id: int, content: str) -> int:
        """Parse CSV text and atomically import it into the selected project."""
        return self.bulk_create_milestones(
            [TaskInput(**row, project_id=project_id) for row in parse_csv(content)]
        )

    def delete_milestone(self, milestone_id: int) -> bool:
        """Delete the task and clean its incoming/outgoing links atomically."""
        return self._gateway.run(lambda store: store.delete_milestone(milestone_id), write=True)

    def get_milestones_by_project(self, project_id: int) -> list[TaskRow]:
        """Read one project's tasks with predecessor labels."""
        return self._gateway.run(lambda store: store.get_milestones_by_project(project_id))

    def search_task_choices(self, search: str = "", *, limit: int = 50) -> list[TaskChoice]:
        """Search a bounded selector page."""
        return self._gateway.run(lambda store: store.search_task_choices(search, limit=limit))

    def get_all_milestones(self) -> list[TaskRow]:
        """Read all tasks for explicit administration/export callers."""
        return self._gateway.run(lambda store: store.get_all_milestones())

    def get_dependencies_for_project(self, project_id: int) -> list[DependencySchedule]:
        """Read incoming links for one project."""
        return self._gateway.run(lambda store: store.get_dependencies_for_project(project_id))

    def get_task_dependencies(self, task_id: int) -> list[DependencySchedule]:
        """Read one task's enriched incoming links."""
        return self._gateway.run(lambda store: store.get_task_dependencies(task_id))

    def get_project_date_bounds(self, project_id: int) -> tuple[str | None, str | None]:
        """Read the earliest start and latest finish in a project."""
        return self._gateway.run(lambda store: store.get_project_date_bounds(project_id))

    def get_all_project_date_bounds(self) -> ProjectBounds:
        """Read project bounds in one aggregate query."""
        return self._gateway.run(lambda store: store.get_all_project_date_bounds())

    def get_all_external_tasks_map(
        self,
        exclude_project_ids: list[int] | None = None,
    ) -> dict[str, list[ExternalTask]]:
        """Read external predecessor summaries for explicit export callers."""
        exclude_project_ids = None if exclude_project_ids is None else list(exclude_project_ids)
        return self._gateway.run(lambda store: store.get_all_external_tasks_map(exclude_project_ids))

    def get_milestones_for_projects(self, project_ids: list[int]) -> list[TaskRow]:
        """Batch only the projects requested by planning."""
        project_ids = list(project_ids)
        return self._gateway.run(lambda store: store.get_milestones_for_projects(project_ids))

    def get_dependencies_for_projects(self, project_ids: list[int]) -> list[DependencySchedule]:
        """Batch incoming links for the requested projects."""
        project_ids = list(project_ids)
        return self._gateway.run(lambda store: store.get_dependencies_for_projects(project_ids))

    def get_milestone_by_id(self, milestone_id: int) -> TaskRow | None:
        """Read one task, returning None when it was deleted."""
        return self._gateway.run(lambda store: store.get_milestone_by_id(milestone_id))


    def get_project_summaries(self, project_ids: list[int]) -> list[ProjectSummary]:
        """Read or refresh derived headers without publishing over a concurrent edit."""
        project_ids = list(project_ids)
        return self._gateway.run(lambda store: store.get_project_summaries(project_ids), write=True)

    def affected_task_projects(self, task_id: int) -> tuple[set[int], set[int]]:
        """Find the edited project, dependent projects, and pools requiring refresh."""
        return self._gateway.run(lambda store: store.affected_task_projects(task_id))

    def consuming_pool_ids(self, project_ids: list[int]) -> list[int]:
        """Find pools with positive demand from the requested portfolio projects."""
        project_ids = list(project_ids)
        return self._gateway.run(lambda store: store.consuming_pool_ids(project_ids))

    def read_task_bundle(self, project_ids: list[int]) -> PlanningTaskBundle:
        """Load tasks, dependencies, tags, and pool assignments from one snapshot."""
        project_ids = list(project_ids)
        return self._gateway.run(lambda store: store.read_task_bundle(project_ids))
