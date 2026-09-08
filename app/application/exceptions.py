"""Application errors, independent of persistence and presentation."""


class ProjectTypeConflictError(ValueError):
    """A project-type change conflicts with persisted data or constraints."""


class ProjectTypeStorageError(RuntimeError):
    """Project-type storage is unavailable or failed to complete an operation."""


class ProjectConflictError(ValueError):
    """A project write conflicts with a reference or database constraint."""


class ProjectStorageError(RuntimeError):
    """Project or portfolio storage is unavailable."""


class SchemaConflictError(ValueError):
    """A schema edit conflicts with a name, order, ID, or existing reference."""


class SchemaStorageError(RuntimeError):
    """Schema storage is unavailable or could not complete an operation."""


class OrganizationConflictError(ValueError):
    """An organization change conflicts with a reference or unique value."""


class OrganizationStorageError(RuntimeError):
    """Organization storage is unavailable or failed to complete an operation."""
