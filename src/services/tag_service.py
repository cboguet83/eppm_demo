"""Business logic and validation service for tag management."""

from typing import Optional


class TagService:
    """Provides validation and business rule enforcement for tags, tag groups, and tag assignments."""

    @staticmethod
    def validate_tag_group(tag_group_name: str) -> None:
        """Validates tag group input attributes.

        Args:
            tag_group_name: Name of the tag group.

        Raises:
            ValueError: If tag_group_name is empty or whitespace.
        """
        if not tag_group_name or not tag_group_name.strip():
            raise ValueError("Tag group name cannot be empty.")

    @staticmethod
    def validate_tag(tag: str) -> None:
        """Validates tag dictionary label input.

        Args:
            tag: Text label of the tag.

        Raises:
            ValueError: If tag label is empty or whitespace.
        """
        if not tag or not tag.strip():
            raise ValueError("Tag name cannot be empty.")

    @staticmethod
    def validate_project_tag(
        project_id: Optional[int],
        tag_id: Optional[int] = None,
        free_tag: Optional[str] = None,
    ) -> None:
        """Validates project tag assignment parameters.

        Args:
            project_id: Target project ID (mandatory).
            tag_id: Optional dictionary tag reference.
            free_tag: Optional free-form tag label.

        Raises:
            ValueError: If project_id is invalid or if neither tag_id nor free_tag is specified.
        """
        if project_id is None or project_id <= 0:
            raise ValueError("A valid Project is mandatory for project tag assignment.")

        has_dict_tag = tag_id is not None and tag_id > 0
        has_free_tag = free_tag is not None and bool(free_tag.strip())

        if not has_dict_tag and not has_free_tag:
            raise ValueError("You must select a Dictionary Tag or provide a Free Tag.")

    @staticmethod
    def validate_task_tag(
        task_id: Optional[int],
        tag_id: Optional[int] = None,
        free_tag: Optional[str] = None,
    ) -> None:
        """Validates task tag assignment parameters.

        Args:
            task_id: Target task ID (mandatory).
            tag_id: Optional dictionary tag reference.
            free_tag: Optional free-form tag label.

        Raises:
            ValueError: If task_id is invalid or if neither tag_id nor free_tag is specified.
        """
        if task_id is None or task_id <= 0:
            raise ValueError("A valid Task is mandatory for task tag assignment.")

        has_dict_tag = tag_id is not None and tag_id > 0
        has_free_tag = free_tag is not None and bool(free_tag.strip())

        if not has_dict_tag and not has_free_tag:
            raise ValueError("You must select a Dictionary Tag or provide a Free Tag.")
