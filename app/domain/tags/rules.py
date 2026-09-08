"""Pure validation for catalog labels and tag assignments."""

from dataclasses import replace

from app.domain.tags.models import ProjectTag, TagDictionary, TagGroup, TaskTag


def validate_tag_group(name: str) -> None:
    """Require a nonblank group label."""
    if not name or not name.strip():
        raise ValueError("Tag group name cannot be empty.")


def validate_tag(label: str) -> None:
    """Require a nonblank dictionary label."""
    if not label or not label.strip():
        raise ValueError("Tag name cannot be empty.")


def validate_assignment(
    entity_id: int | None,
    tag_id: int | None,
    free_tag: str | None,
    *,
    entity: str,
    group: TagGroup | None = None,
) -> None:
    """Validate assignment content and an explicitly requested group restriction.

    Existing persisted assignments allow tags from any group. Group restrictions
    remain an optional selector validation, preserving cross-group assignments.
    Dictionary and free-form tags may coexist on the same assignment.
    """
    if entity_id is None or entity_id <= 0:
        raise ValueError(f"A valid {entity} is mandatory for {entity.lower()} tag assignment.")
    has_dictionary = tag_id is not None and tag_id > 0
    if not has_dictionary and not (free_tag and free_tag.strip()):
        raise ValueError("You must select a Dictionary Tag or provide a Free Tag.")
    if has_dictionary and group is not None:
        name = group.tag_group_name.strip().lower().replace("_", "").replace(" ", "")
        expected = entity.lower() + "tag"
        if name not in (expected, expected + "s"):
            label = "project_tag" if entity == "Project" else "Task_Tag"
            raise ValueError(
                f"Tag '{tag_id}' belongs to group '{group.tag_group_name}'. "
                f"{entity} tags can only be picked up from the '{label}' group."
            )


def normalize_group(group: TagGroup) -> TagGroup:
    """Validate and trim a tag-group label without mutating the input."""
    validate_tag_group(group.tag_group_name)
    return replace(group, tag_group_name=group.tag_group_name.strip())


def normalize_tag(tag: TagDictionary) -> TagDictionary:
    """Validate and trim a dictionary label."""
    validate_tag(tag.tag)
    return replace(tag, tag=tag.tag.strip())


def normalize_project_tag(tag: ProjectTag) -> ProjectTag:
    """Validate a project assignment while preserving combined/free-tag behavior."""
    validate_assignment(tag.project_id, tag.tag_id, tag.free_tag, entity="Project")
    return replace(tag, free_tag=tag.free_tag.strip() or None if tag.free_tag else None)


def normalize_task_tag(tag: TaskTag) -> TaskTag:
    """Validate a task assignment while preserving combined/free-tag behavior."""
    validate_assignment(tag.task_id, tag.tag_id, tag.free_tag, entity="Task")
    return replace(tag, free_tag=tag.free_tag.strip() or None if tag.free_tag else None)
