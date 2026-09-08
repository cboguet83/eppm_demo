"""Compatibility facade for callers of the original dataframe repository.

New code calls ProjectTypeService. This adapter keeps the existing dataframe
results, database-path constructor, SQLite exception types, and connection-owned
schema operations while delegating business behavior to the migrated feature.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

import pandas as pd

from app.application.exceptions import ProjectTypeConflictError, ProjectTypeStorageError
from app.domain.projects.project_types import PropertyValue, make_applicability


@contextmanager
def _legacy_errors() -> Iterator[None]:
    """Preserve SQLite exceptions expected by existing repository callers."""
    try:
        yield
    except ProjectTypeConflictError as exc:
        raise sqlite3.IntegrityError(str(exc.__cause__ or exc)) from exc
    except ProjectTypeStorageError as exc:
        if isinstance(exc.__cause__, sqlite3.DatabaseError):
            raise exc.__cause__ from None
        raise


class ProjectTypeRepository:
    """Adapt the former repository API to the new application service."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain the old constructor and expose the composed service."""
        from app.main import create_project_type_service

        self.db_path = db_path
        self.service = create_project_type_service(db_path)

    def get_all_types(self) -> pd.DataFrame:
        """Return the legacy type dataframe, including the integer General flag."""
        with _legacy_errors():
            return pd.DataFrame([
                {**asdict(item), "is_general": int(item.is_general)}
                for item in self.service.get_all_types()
            ], columns=["id", "name", "description", "is_general"])

    def create_type(self, name: str, description: str = "") -> int:
        """Create a type through the shared use case."""
        with _legacy_errors():
            return self.service.create_type(name, description)

    def update_type(self, type_id: int, name: str, description: str = "") -> None:
        """Update a type through the shared use case."""
        with _legacy_errors():
            self.service.update_type(type_id, name, description)

    def delete_type(self, type_id: int) -> None:
        """Apply domain deletion guards and remove a type."""
        with _legacy_errors():
            self.service.delete_type(type_id)

    def get_template(self, type_id: int) -> pd.DataFrame:
        """Return the effective template using the legacy dataframe shape."""
        with _legacy_errors():
            return pd.DataFrame(self.service.get_template(type_id))

    def get_applicability(self, param_id: str) -> tuple[bool, list[int]]:
        """Return the former all-types flag and selected-ID list."""
        with _legacy_errors():
            scope = self.service.get_applicability(param_id)
            return scope.applies_to_all, list(scope.type_ids)

    @staticmethod
    def set_applicability_on_connection(
        conn: sqlite3.Connection, param_id: str, applies_to_all: bool, type_ids: list[int],
    ) -> None:
        """Join a schema operation's transaction without committing or closing it."""
        from app.infrastructure.repositories.project_types import SqliteProjectTypeStore

        scope = make_applicability(applies_to_all, type_ids)
        SqliteProjectTypeStore(conn).set_applicability(param_id, scope)

    def set_applicability(
        self, param_id: str, applies_to_all: bool, type_ids: list[int] | None = None,
    ) -> None:
        """Replace scope through the shared use case."""
        with _legacy_errors():
            self.service.set_applicability(param_id, applies_to_all, type_ids)

    def save_rule(
        self, type_id: int, param_id: str, mandatory_override: bool | None = None,
        *, has_default: bool = False, default_value: PropertyValue = None,
    ) -> None:
        """Save required/default settings through the shared use case."""
        with _legacy_errors():
            self.service.save_rule(
                type_id, param_id, mandatory_override,
                has_default=has_default, default_value=default_value,
            )
