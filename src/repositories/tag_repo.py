"""Compatibility facade for legacy tag DataFrames and SQLite exceptions."""

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
import pandas as pd
from app.application.exceptions import TagConflictError, TagStorageError
from app.main import create_tag_service, create_resource_pool_service
from app.application.ports.tag_records import (
    DictionaryRow,
    EntityChoice,
    PoolTagRow,
    ProjectTagRow,
    TagGroupRow,
    TagLink,
    TaskChoice,
    TaskTagPage,
    TaskTagRow,
)
from app.domain.tags.models import ProjectTag, ResourcePoolTag, TagDictionary, TagGroup, TaskTag
from app.presentation.components.tag_frames import (
    get_all_tag_groups_frame,
    get_all_tags_frame,
    get_tags_by_group_name_frame,
    get_project_tag_group_tags_frame,
    get_task_tag_group_tags_frame,
    get_all_resource_pool_tags_frame,
    get_resource_pool_tags_frame,
    get_all_project_tags_frame,
    get_project_tags_by_project_frame,
    get_all_task_tags_frame,
    get_task_tags_by_task_frame,
    page_frame,
)
from src.repositories.project_repo import parse_project_id
from src.repositories.resource_pool_repo import legacy_pool_errors


@contextmanager
def legacy_tag_errors() -> Iterator[None]:
    """Preserve historical SQLite exceptions outside migrated presentation."""
    try:
        yield
    except (TagConflictError, TagStorageError) as exc:
        if isinstance(exc.__cause__, sqlite3.DatabaseError):
            raise exc.__cause__ from exc
        raise


class TagRepository:
    """Adapt existing callers to the tag application service."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain the existing per-caller database path."""
        self.db_path = db_path
        self.service = create_tag_service(db_path)

    def get_all_tag_groups(self) -> pd.DataFrame:
        """Keep the historical get all tag groups contract."""
        with legacy_tag_errors():
            return get_all_tag_groups_frame(self.service.get_all_tag_groups())

    def get_tag_group_by_id(self, group_id: int) -> TagGroup | None:
        """Keep the historical get tag group by id contract."""
        with legacy_tag_errors():
            return self.service.get_tag_group_by_id(group_id)

    def create_tag_group(self, group: TagGroup) -> int:
        """Keep the historical create tag group contract."""
        with legacy_tag_errors():
            return self.service.create_tag_group(group)

    def update_tag_group(self, group: TagGroup) -> bool:
        """Keep the historical update tag group contract."""
        with legacy_tag_errors():
            return self.service.update_tag_group(group)

    def delete_tag_group(self, group_id: int) -> bool:
        """Keep the historical delete tag group contract."""
        with legacy_tag_errors():
            return self.service.delete_tag_group(group_id)

    def count_tags_by_group(self, group_id: int) -> int:
        """Keep the historical count tags by group contract."""
        with legacy_tag_errors():
            return self.service.count_tags_by_group(group_id)

    def get_all_tags(self) -> pd.DataFrame:
        """Keep the historical get all tags contract."""
        with legacy_tag_errors():
            return get_all_tags_frame(self.service.get_all_tags())

    def get_tags_by_group_name(self, group_name: str) -> pd.DataFrame:
        """Keep the historical get tags by group name contract."""
        with legacy_tag_errors():
            return get_tags_by_group_name_frame(self.service.get_tags_by_group_name(group_name))

    def get_project_tag_group_tags(self) -> pd.DataFrame:
        """Keep the historical get project tag group tags contract."""
        with legacy_tag_errors():
            return get_project_tag_group_tags_frame(self.service.get_project_tag_group_tags())

    def get_task_tag_group_tags(self) -> pd.DataFrame:
        """Keep the historical get task tag group tags contract."""
        with legacy_tag_errors():
            return get_task_tag_group_tags_frame(self.service.get_task_tag_group_tags())

    def get_tag_group_for_tag(self, tag_id: int) -> TagGroup | None:
        """Keep the historical get tag group for tag contract."""
        with legacy_tag_errors():
            return self.service.get_tag_group_for_tag(tag_id)

    def get_tag_by_id(self, tag_id: int) -> TagDictionary | None:
        """Keep the historical get tag by id contract."""
        with legacy_tag_errors():
            return self.service.get_tag_by_id(tag_id)

    def create_tag(self, tag_item: TagDictionary) -> int:
        """Keep the historical create tag contract."""
        with legacy_tag_errors():
            return self.service.create_tag(tag_item)

    def update_tag(self, tag_item: TagDictionary) -> bool:
        """Keep the historical update tag contract."""
        with legacy_tag_errors():
            return self.service.update_tag(tag_item)

    def delete_tag(self, tag_id: int) -> bool:
        """Keep the historical delete tag contract."""
        with legacy_tag_errors():
            return self.service.delete_tag(tag_id)

    def count_tag_usages(self, tag_id: int) -> int:
        """Keep the historical count tag usages contract."""
        with legacy_tag_errors():
            return self.service.count_tag_usages(tag_id)

    def get_all_resource_pool_tags(self) -> pd.DataFrame:
        """Keep the historical get all resource pool tags contract."""
        with legacy_tag_errors():
            return get_all_resource_pool_tags_frame(self.service.get_all_resource_pool_tags())

    def get_resource_pool_tags(self, pool_id: int) -> pd.DataFrame:
        """Keep the historical get resource pool tags contract."""
        with legacy_tag_errors():
            return get_resource_pool_tags_frame(self.service.get_resource_pool_tags(pool_id))

    def create_resource_pool_tag(self, pool_tag: ResourcePoolTag) -> int:
        """Keep the historical create resource pool tag contract."""
        with legacy_tag_errors():
            return self.service.create_resource_pool_tag(pool_tag)

    def delete_resource_pool_tag(self, pool_tag_id: int) -> bool:
        """Keep the historical delete resource pool tag contract."""
        with legacy_tag_errors():
            return self.service.delete_resource_pool_tag(pool_tag_id)

    def get_all_project_tags(self) -> pd.DataFrame:
        """Keep the historical get all project tags contract."""
        with legacy_tag_errors():
            return get_all_project_tags_frame(self.service.get_all_project_tags())

    def get_project_tags_by_project(self, project_id: int) -> pd.DataFrame:
        """Keep the historical get project tags by project contract."""
        with legacy_tag_errors():
            return get_project_tags_by_project_frame(
                self.service.get_project_tags_by_project(project_id)
            )

    def get_project_tag_by_id(self, pt_id: int) -> ProjectTag | None:
        """Keep the historical get project tag by id contract."""
        with legacy_tag_errors():
            return self.service.get_project_tag_by_id(pt_id)

    def create_project_tag(self, pt: ProjectTag) -> int:
        """Keep the historical create project tag contract."""
        with legacy_tag_errors():
            return self.service.create_project_tag(pt)

    def update_project_tag(self, pt: ProjectTag) -> bool:
        """Keep the historical update project tag contract."""
        with legacy_tag_errors():
            return self.service.update_project_tag(pt)

    def delete_project_tag(self, pt_id: int) -> bool:
        """Keep the historical delete project tag contract."""
        with legacy_tag_errors():
            return self.service.delete_project_tag(pt_id)

    def get_task_tags_page(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        search: str = "",
        filters: dict[str, object] | None = None,
        sort: str = "id",
        ascending: bool = False
    ) -> dict[str, object]:
        """Keep the historical get task tags page contract."""
        with legacy_tag_errors():
            return page_frame(
                self.service.get_task_tags_page(
                    page=page,
                    page_size=page_size,
                    search=search,
                    filters=filters,
                    sort=sort,
                    ascending=ascending,
                )
            )

    def get_all_task_tags(self) -> pd.DataFrame:
        """Keep the historical get all task tags contract."""
        with legacy_tag_errors():
            return get_all_task_tags_frame(self.service.get_all_task_tags())

    def get_task_tags_by_task(self, task_id: int) -> pd.DataFrame:
        """Keep the historical get task tags by task contract."""
        with legacy_tag_errors():
            return get_task_tags_by_task_frame(self.service.get_task_tags_by_task(task_id))

    def get_task_tag_by_id(self, tt_id: int) -> TaskTag | None:
        """Keep the historical get task tag by id contract."""
        with legacy_tag_errors():
            return self.service.get_task_tag_by_id(tt_id)

    def create_task_tag(self, tt: TaskTag) -> int:
        """Keep the historical create task tag contract."""
        with legacy_tag_errors():
            return self.service.create_task_tag(tt)

    def update_task_tag(self, tt: TaskTag) -> bool:
        """Keep the historical update task tag contract."""
        with legacy_tag_errors():
            return self.service.update_task_tag(tt)

    def delete_task_tag(self, tt_id: int) -> bool:
        """Keep the historical delete task tag contract."""
        with legacy_tag_errors():
            return self.service.delete_task_tag(tt_id)

    def get_task_tags_by_task_ids(self, task_ids: list[int]) -> dict[int, list[TagLink]]:
        """Keep the historical get task tags by task ids contract."""
        with legacy_tag_errors():
            return self.service.get_task_tags_by_task_ids(task_ids)

    def get_project_tags_by_project_ids(
        self, project_ids: list[int | str]
    ) -> dict[int, list[TagLink]]:
        """Keep the historical get project tags by project ids contract."""
        with legacy_tag_errors():
            return self.service.get_project_tags_by_project_ids(
                [parse_project_id(pid) for pid in project_ids]
            )

    def set_resource_pool_tags(self, pool_id: int, tag_ids: list[int]) -> None:
        """Share the atomic pool-tag replacement operation."""
        with legacy_pool_errors():
            create_resource_pool_service(self.db_path).set_pool_tags(pool_id, tag_ids)
