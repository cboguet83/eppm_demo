"""Compatibility entry point for the layered portfolio overload use case."""

from app.main import create_project_overallocation_service


def overallocated_project_ids(db_path: str | None, project_ids: list[int]) -> set[int]:
    """Return page projects consuming capacity on at least one overloaded day."""
    return create_project_overallocation_service(db_path).overallocated_project_ids(project_ids)
