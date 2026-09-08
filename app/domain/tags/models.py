"""Domain models for tag groups, dictionary entries, and tagged entities."""

from dataclasses import dataclass


@dataclass
class TagGroup:
    """Represents a category/group for organizing tags.

    Attributes:
        id: Unique tag group identifier.
        tag_group_name: Name of the tag group.
    """

    id: int | None = None
    tag_group_name: str = ""


@dataclass
class TagDictionary:
    """Represents a standard discrete tag in the dictionary taxonomy.

    Attributes:
        id: Unique tag identifier.
        tag: Text name/label of the tag.
        tag_group_id: Optional foreign key to associated tag group.
    """

    id: int | None = None
    tag: str = ""
    tag_group_id: int | None = None


@dataclass
class ProjectTag:
    """Associates a project with a dictionary tag or a free-form tag.

    Attributes:
        id: Unique project tag assignment ID.
        project_id: Foreign key to the project.
        tag_id: Optional foreign key to standard dictionary tag.
        free_tag: Optional free-form tag text.
    """

    id: int | None = None
    project_id: int = 0
    tag_id: int | None = None
    free_tag: str | None = None


@dataclass
class TaskTag:
    """Associates a task with a dictionary tag or a free-form tag.

    Attributes:
        id: Unique task tag assignment ID.
        task_id: Foreign key to the task (project_task).
        tag_id: Optional foreign key to standard dictionary tag.
        free_tag: Optional free-form tag text.
    """

    id: int | None = None
    task_id: int = 0
    tag_id: int | None = None
    free_tag: str | None = None


@dataclass
class ResourcePoolTag:
    """Associates a resource pool with a dictionary tag."""

    id: int | None = None
    pool_id: int = 0
    tag_id: int = 0
