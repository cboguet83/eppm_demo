"""Typed catalog, assignment, paging, and entity-choice projections."""

from dataclasses import dataclass
from typing import NotRequired, TypedDict
from app.domain.tags.models import ProjectTag, ResourcePoolTag, TagDictionary, TagGroup, TaskTag


@dataclass
class TagGroupRow(TagGroup):
    """Group label with a batched dictionary-entry count."""

    tag_count: int = 0


@dataclass
class DictionaryRow(TagDictionary):
    """Dictionary label and its optional group name."""

    tag_group_name: str | None = None
    usage_count: int = 0


@dataclass
class ProjectTagRow(ProjectTag):
    """Project assignment enriched with catalog labels."""

    project_name: str | None = None
    tag_name: str | None = None
    tag_group_name: str | None = None


@dataclass
class TaskTagRow(TaskTag):
    """Task assignment enriched with task, project, and catalog labels."""

    task_name: str | None = None
    project_id: int | None = None
    project_name: str | None = None
    tag_name: str | None = None
    tag_group_name: str | None = None


@dataclass
class PoolTagRow(ResourcePoolTag):
    """Pool assignment enriched with dictionary and pool labels."""

    pool_name: str | None = None
    tag_name: str | None = None
    tag_group_name: str | None = None


class TagLink(TypedDict):
    """Compact tag assignment for batched project/task reads."""

    id: int
    tag_id: int | None
    tag_name: str | None
    tag_group_name: str | None
    free_tag: str | None
    project_id: NotRequired[int]
    task_id: NotRequired[int]


@dataclass(frozen=True)
class EntityChoice:
    """Minimal project identity for an assignment selector."""

    id: int
    name: str


@dataclass(frozen=True)
class TaskChoice:
    """Bounded task-selector projection."""

    id: int
    task_name: str
    project_id: int
    project_name: str


@dataclass
class TaskTagPage:
    """One consistent result page and the counts used by its controls."""

    rows: list[TaskTagRow]
    total: int
    filtered_total: int
    page: int
    pages: int
    page_size: int
