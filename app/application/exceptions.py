"""Persistence-boundary errors suitable for application callers."""


class ProjectTypeConflictError(ValueError):
    """A project-type change conflicts with persisted data or constraints."""


class ProjectTypeStorageError(RuntimeError):
    """Project-type storage is unavailable or failed to complete an operation."""
