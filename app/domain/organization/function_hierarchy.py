"""Validate primary reporting hierarchies independently of presentation and SQL."""

from app.domain.organization.models import OrgFunction


def validate_function_hierarchy(functions: list[OrgFunction]) -> None:
    """Reject missing parents, primary cycles and live links to deleted managers."""
    records = {item.function_id: item for item in functions}
    for item in functions:
        for identity in (item.manager_function_id, item.dual_manager_function_id):
            if identity is None:
                continue
            if identity == item.function_id or identity not in records:
                raise ValueError('A manager must be another existing function.')
            if not item.deleted_flag and records[identity].deleted_flag:
                raise ValueError('An active function cannot report to a deleted function.')
    visited: set[int] = set()
    for identity in records:
        path: set[int] = set()
        while identity is not None and identity not in visited:
            if identity in path:
                raise ValueError('The function hierarchy contains a cycle.')
            path.add(identity)
            identity = records[identity].manager_function_id
        visited.update(path)
