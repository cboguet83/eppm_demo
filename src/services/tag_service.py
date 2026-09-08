"""Legacy validation signatures backed by pure tag-domain rules."""

from typing import TYPE_CHECKING
from app.domain.tags.rules import validate_assignment, validate_tag, validate_tag_group

if TYPE_CHECKING:
    from src.repositories.tag_repo import TagRepository


class TagService:
    """Keep optional group validation for historical callers."""

    validate_tag = staticmethod(validate_tag)
    validate_tag_group = staticmethod(validate_tag_group)

    @staticmethod
    def validate_project_tag(
        project_id: int | None,
        tag_id: int | None = None,
        free_tag: str | None = None,
        tag_repo: TagRepository | None = None,
    ) -> None:
        """Validate project content and an optional dictionary-group restriction."""
        group = tag_repo.get_tag_group_for_tag(tag_id) if tag_repo is not None and tag_id else None
        validate_assignment(project_id, tag_id, free_tag, entity="Project", group=group)

    @staticmethod
    def validate_task_tag(
        task_id: int | None,
        tag_id: int | None = None,
        free_tag: str | None = None,
        tag_repo: TagRepository | None = None,
    ) -> None:
        """Validate task content and an optional dictionary-group restriction."""
        group = tag_repo.get_tag_group_for_tag(tag_id) if tag_repo is not None and tag_id else None
        validate_assignment(task_id, tag_id, free_tag, entity="Task", group=group)
