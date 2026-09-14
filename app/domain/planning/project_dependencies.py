"""Project-owned dependency inputs and warning-only date evaluation."""

from datetime import date
from typing import NotRequired, TypedDict


class _ProjectDependencyValues(TypedDict):
    """The editable endpoint and scheduling fields shared by link contracts."""

    predecessor_project_id: int | None
    predecessor_task_id: int | None
    link_type: str
    lag_days: int


class ProjectDependencyInput(_ProjectDependencyValues):
    """One incoming project link; an ID identifies an existing edited link."""

    id: NotRequired[int]


class ProjectDependency(_ProjectDependencyValues):
    """Authorized display record with both endpoint dates and labels."""

    id: int
    project_id: int
    predecessor_owner_id: int
    predecessor_project_name: str
    predecessor_task_name: str | None
    pred_start_date: str | None
    pred_end_date: str | None
    start_date: str | None
    end_date: str | None
    is_violated: NotRequired[bool]
    is_evaluable: NotRequired[bool]
    violation_text: NotRequired[str | None]


class ProjectDependencyPanel(TypedDict):
    """An authorized snapshot and source token for a project dependency form."""

    project_id: int
    revision: str
    dependencies: list[ProjectDependency]


def positive_identity(value: object) -> int:
    """Validate numeric identities received at the component boundary."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError('Invalid dependency identity.')
    try:
        identity = int(value)
    except ValueError as error:
        raise ValueError('Invalid dependency identity.') from error
    if not 1 <= identity <= 2**63 - 1:
        raise ValueError('Invalid dependency identity.')
    return identity


def normalize_project_dependency(project_id: int, values: ProjectDependencyInput) -> ProjectDependencyInput:
    """Validate one project or external-step predecessor without changing dates."""
    project = values.get('predecessor_project_id')
    task = values.get('predecessor_task_id')
    if (project is None) == (task is None):
        raise ValueError('Choose one predecessor project or step.')
    project = positive_identity(project) if project is not None else None
    task = positive_identity(task) if task is not None else None
    if project == project_id:
        raise ValueError('A project cannot depend on itself.')
    kind = values.get('link_type', 'FS')
    lag = values.get('lag_days', 0)
    if kind not in ('FS', 'FF', 'SS', 'SF'):
        raise ValueError('Choose FS, FF, SS or SF.')
    if type(lag) is not int or not -(2**31) <= lag < 2**31:
        raise ValueError('Lag must be a whole number of calendar days.')
    result = ProjectDependencyInput(predecessor_project_id=project, predecessor_task_id=task, link_type=kind, lag_days=lag)
    if values.get('id') is not None:
        result['id'] = positive_identity(values['id'])
    return result


def evaluate_project_dependencies(rows: list[ProjectDependency]) -> list[ProjectDependency]:
    """Evaluate each link once using project bounds, never shifting schedules.

    FS/SS constrain successor start; FF/SF constrain its end. Calendar-day
    subtraction supports negative and large lags without date overflow. Missing
    dates are explicitly unevaluable. Cycles require no recursive evaluation.
    """
    result = []
    for original in rows:
        row = original.copy()
        kind = row['link_type']
        successor = row['end_date' if kind in ('FF', 'SF') else 'start_date']
        predecessor = row['pred_start_date' if kind in ('SS', 'SF') else 'pred_end_date']
        row.update(is_evaluable=bool(successor and predecessor), is_violated=False, violation_text=None)
        if successor and predecessor:
            row['is_violated'] = (date.fromisoformat(successor) - date.fromisoformat(predecessor)).days < row['lag_days']
            if row['is_violated']:
                label = row['predecessor_task_name'] or row['predecessor_project_name']
                row['violation_text'] = f"{kind} with '{label}' ({row['lag_days']:+d}d offset): project {'end' if kind in ('FF', 'SF') else 'start'} is too early."
        result.append(row)
    return result
