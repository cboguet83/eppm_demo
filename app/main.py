"""Composition root for application dependencies and Streamlit startup."""

from app.application.services.project_types import ProjectTypeService


def create_project_type_service(db_path: str | None = None) -> ProjectTypeService:
    """Connect project-type use cases to the SQLite persistence adapter.

    Args:
        db_path: Database used by the calling screen; None uses configured settings.

    Returns:
        A service ready for use without opening a database at construction.
    """
    from app.infrastructure.repositories.project_types import SqliteProjectTypeGateway

    return ProjectTypeService(SqliteProjectTypeGateway(db_path))


def main() -> None:
    """Run the transitional UI shell with the existing CLI and seeding behavior."""
    import runpy

    runpy.run_module("app.presentation.legacy_shell", run_name="__main__")


if __name__ == "__main__":
    main()
