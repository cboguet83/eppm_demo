"""Task and dependency use cases with atomic writes and pure scheduling rules."""

from app.application.ports.planning import (
    ExternalTask,
    PlanningGateway,
    PlanningStore,
    PlanningTaskBundle,
    ProjectSummary,
    TaskChoice,
    TaskRow,
)
from app.domain.planning.csv_import import parse_csv
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
        with self._gateway.transaction(write=True) as store:
            task_id = store.create_task(project_id, values)
            _replace_dependencies(store, task_id, dependencies, predecessor_id)
            return task_id

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
        with self._gateway.transaction(write=True) as store:
            if not store.update_task(milestone_id, values):
                return False
            _replace_dependencies(store, milestone_id, dependencies, predecessor_id)
            return True

    def save_task_dependencies(self, task_id: int, dependencies: list[DependencyInput]) -> None:
        """Replace incoming links atomically, preserving existing normalization defaults."""
        with self._gateway.transaction(write=True) as store:
            if store.get_milestone_by_id(task_id) is None:
                raise ValueError("The task no longer exists.")
            _replace_dependencies(store, task_id, dependencies, None)

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
        with self._gateway.transaction(write=True) as store:
            store.insert_dependency(task_id, dependency)

    def update_dates(self, milestone_id: int, start_date: str, end_date: str) -> bool:
        """Validate a drag command before changing the schedule."""
        start, end = normalize_dates(start_date, end_date)
        with self._gateway.transaction(write=True) as store:
            return store.update_dates(milestone_id, start, end)

    def update_progress(self, milestone_id: int, progress_pct: int) -> bool:
        """Retain the established progress clamp at the authoritative boundary."""
        progress = normalize_progress(progress_pct)
        with self._gateway.transaction(write=True) as store:
            return store.update_progress(milestone_id, progress)

    def bulk_create_milestones(self, rows: list[TaskInput]) -> int:
        """Validate the entire import and insert all rows in one transaction."""
        if not rows:
            return 0
        prepared = [TaskInput(**normalize_task(row), project_id=row["project_id"]) for row in rows]
        with self._gateway.transaction(write=True) as store:
            return store.bulk_create_milestones(prepared)

    def import_csv(self, project_id: int, content: str) -> int:
        """Parse CSV text and atomically import it into the selected project."""
        return self.bulk_create_milestones(
            [TaskInput(**row, project_id=project_id) for row in parse_csv(content)]
        )

    def delete_milestone(self, milestone_id: int) -> bool:
        """Delete the task and clean its incoming/outgoing links atomically."""
        with self._gateway.transaction(write=True) as store:
            return store.delete_milestone(milestone_id)

    def get_milestones_by_project(self, project_id: int) -> list[TaskRow]:
        """Read one project's tasks with predecessor labels."""
        with self._gateway.transaction() as store:
            return store.get_milestones_by_project(project_id)

    def search_task_choices(self, search: str = "", *, limit: int = 50) -> list[TaskChoice]:
        """Search a bounded selector page."""
        with self._gateway.transaction() as store:
            return store.search_task_choices(search, limit=limit)

    def get_all_milestones(self) -> list[TaskRow]:
        """Read all tasks for explicit administration/export callers."""
        with self._gateway.transaction() as store:
            return store.get_all_milestones()

    def get_dependencies_for_project(self, project_id: int) -> list[DependencySchedule]:
        """Read incoming links for one project."""
        with self._gateway.transaction() as store:
            return store.get_dependencies_for_project(project_id)

    def get_task_dependencies(self, task_id: int) -> list[DependencySchedule]:
        """Read one task's enriched incoming links."""
        with self._gateway.transaction() as store:
            return store.get_task_dependencies(task_id)

    def get_project_date_bounds(self, project_id: int) -> tuple[str | None, str | None]:
        """Read the earliest start and latest finish in a project."""
        with self._gateway.transaction() as store:
            return store.get_project_date_bounds(project_id)

    def get_all_project_date_bounds(self) -> ProjectBounds:
        """Read project bounds in one aggregate query."""
        with self._gateway.transaction() as store:
            return store.get_all_project_date_bounds()

    def get_all_external_tasks_map(
        self,
        exclude_project_ids: list[int] | None = None,
    ) -> dict[str, list[ExternalTask]]:
        """Read external predecessor summaries for explicit export callers."""
        with self._gateway.transaction() as store:
            return store.get_all_external_tasks_map(exclude_project_ids)

    def get_milestones_for_projects(self, project_ids: list[int]) -> list[TaskRow]:
        """Batch only the projects requested by planning."""
        with self._gateway.transaction() as store:
            return store.get_milestones_for_projects(project_ids)

    def get_dependencies_for_projects(self, project_ids: list[int]) -> list[DependencySchedule]:
        """Batch incoming links for the requested projects."""
        with self._gateway.transaction() as store:
            return store.get_dependencies_for_projects(project_ids)

    def get_milestone_by_id(self, milestone_id: int) -> TaskRow | None:
        """Read one task, returning None when it was deleted."""
        with self._gateway.transaction() as store:
            return store.get_milestone_by_id(milestone_id)

    def ensure_indexes(self) -> None:
        """Prepare the existing planning projection and its lookup indexes."""
        with self._gateway.transaction(write=True) as store:
            store.ensure_indexes()

    def get_project_summaries(self, project_ids: list[int]) -> list[ProjectSummary]:
        """Read or refresh derived headers without publishing over a concurrent edit."""
        with self._gateway.transaction(write=True) as store:
            return store.get_project_summaries(project_ids)

    def affected_task_projects(self, task_id: int) -> tuple[set[int], set[int]]:
        """Find the edited project, dependent projects, and pools requiring refresh."""
        with self._gateway.transaction() as store:
            return store.affected_task_projects(task_id)

    def consuming_pool_ids(self, project_ids: list[int]) -> list[int]:
        """Find pools with positive demand from the requested portfolio projects."""
        with self._gateway.transaction() as store:
            return store.consuming_pool_ids(project_ids)

    def read_task_bundle(self, project_ids: list[int]) -> PlanningTaskBundle:
        """Load tasks, dependencies, tags, and pool assignments from one snapshot."""
        with self._gateway.transaction() as store:
            return store.read_task_bundle(project_ids)
