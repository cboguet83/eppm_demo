"""Validate primary reporting hierarchies independently of presentation and SQL."""

from app.domain.organization.models import OrgFunction


class FunctionHierarchyError(ValueError):
    """Identify the function and relationship responsible for invalid ancestry."""

    def __init__(self, function: OrgFunction, field: str, reason: str) -> None:
        """Keep a stable identity for callers that map records to import rows."""
        self.function_id = function.function_id
        super().__init__(f'Function "{function.name}" (ID {function.function_id}), {field}: {reason}')


def validate_function_hierarchy(functions: list[OrgFunction]) -> None:
    """Reject missing parents, primary cycles and live links to deleted managers."""
    records = {item.function_id: item for item in functions}
    for item in functions:
        for field in ('manager_function_id', 'dual_manager_function_id'):
            identity = getattr(item, field)
            if identity is None:
                continue
            if identity == item.function_id or identity not in records:
                raise FunctionHierarchyError(item, field, f'A manager must be another existing function; received ID {identity}.')
            if not item.deleted_flag and records[identity].deleted_flag:
                parent = records[identity]
                raise FunctionHierarchyError(item, field,
                    f'An active function cannot report to a deleted function: "{parent.name}" (ID {identity}).')
    visited: set[int] = set()
    for identity in records:
        path: set[int] = set()
        while identity is not None and identity not in visited:
            if identity in path:
                raise FunctionHierarchyError(records[identity], 'manager_function_id',
                    'The function hierarchy contains a cycle. Check the primary manager links.')
            path.add(identity)
            identity = records[identity].manager_function_id
        visited.update(path)
