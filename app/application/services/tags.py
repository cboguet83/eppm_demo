"""Tag management with injected transactions and domain validation."""

from app.domain.access.models import Permission
from app.application.ports.references import TagReference


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
from app.application.ports.tags import TagGateway
from app.domain.tags.rules import (
    normalize_group,
    normalize_tag,
    normalize_project_tag,
    normalize_task_tag,
)


class TagService:
    """Coordinate tag catalog and assignment use cases."""

    def __init__(self, gateway: TagGateway) -> None:
        """Inject persistence without opening a connection."""
        self._gateway = gateway

    def project_tag_choices(self) -> list[TagReference]:
        """Read only dictionary selector labels for project tagging."""
        with self._gateway.transaction() as store:
            return [TagReference(row.id, row.tag, row.tag_group_id, row.tag_group_name)
                    for row in store.get_project_tag_group_tags()]

    def task_tag_choices(self) -> list[TagReference]:
        """Read only dictionary selector labels for task tagging."""
        with self._gateway.transaction() as store:
            return [TagReference(row.id, row.tag, row.tag_group_id, row.tag_group_name)
                    for row in store.get_task_tag_group_tags()]

    def get_all_tag_groups(self) -> list[TagGroupRow]:
        """Get all tag groups through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.get_all_tag_groups()

    def get_tag_group_by_id(self, group_id: int) -> TagGroup | None:
        """Get tag group by id through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.get_tag_group_by_id(group_id)

    def create_tag_group(self, group: TagGroup) -> int:
        """Create tag group through one transaction."""
        group = normalize_group(group)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.create_tag_group(group)

    def update_tag_group(self, group: TagGroup) -> bool:
        """Update tag group through one transaction."""
        if group.id is None:
            return False
        group = normalize_group(group)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.update_tag_group(group)

    def delete_tag_group(self, group_id: int) -> bool:
        """Delete tag group through one transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            count = store.count_tags_by_group(group_id)
            if count:
                raise ValueError(
                    f"Cannot delete Tag Group (ID: {group_id}): {count} dictionary tags are associated with it."
                )
            return store.delete_tag_group(group_id)

    def count_tags_by_group(self, group_id: int) -> int:
        """Count tags by group through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.count_tags_by_group(group_id)

    def get_all_tags(self) -> list[DictionaryRow]:
        """Get all tags through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.get_all_tags()

    def get_tags_by_group_name(self, group_name: str) -> list[DictionaryRow]:
        """Get tags by group name through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.get_tags_by_group_name(group_name)

    def get_project_tag_group_tags(self) -> list[DictionaryRow]:
        """Get project tag group tags through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.get_project_tag_group_tags()

    def get_task_tag_group_tags(self) -> list[DictionaryRow]:
        """Get task tag group tags through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.get_task_tag_group_tags()

    def get_tag_group_for_tag(self, tag_id: int) -> TagGroup | None:
        """Get tag group for tag through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.get_tag_group_for_tag(tag_id)

    def get_tag_by_id(self, tag_id: int) -> TagDictionary | None:
        """Get tag by id through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.get_tag_by_id(tag_id)

    def create_tag(self, tag_item: TagDictionary) -> int:
        """Create tag through one transaction."""
        tag_item = normalize_tag(tag_item)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.create_tag(tag_item)

    def update_tag(self, tag_item: TagDictionary) -> bool:
        """Update tag through one transaction."""
        if tag_item.id is None:
            return False
        tag_item = normalize_tag(tag_item)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.update_tag(tag_item)

    def delete_tag(self, tag_id: int) -> bool:
        """Delete tag through one transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.delete_tag(tag_id)

    def count_tag_usages(self, tag_id: int) -> int:
        """Count tag usages through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.count_tag_usages(tag_id)

    def get_all_resource_pool_tags(self) -> list[PoolTagRow]:
        """Get all resource pool tags through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.get_all_resource_pool_tags()

    def get_resource_pool_tags(self, pool_id: int) -> list[PoolTagRow]:
        """Get resource pool tags through one transaction."""
        with self._gateway.transaction(write=False, permission=Permission.SHARED) as store:
            return store.get_resource_pool_tags(pool_id)

    def create_resource_pool_tag(self, pool_tag: ResourcePoolTag) -> int:
        """Create resource pool tag through one transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.create_resource_pool_tag(pool_tag)

    def delete_resource_pool_tag(self, pool_tag_id: int) -> bool:
        """Delete resource pool tag through one transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.delete_resource_pool_tag(pool_tag_id)

    def get_all_project_tags(self) -> list[ProjectTagRow]:
        """Get all project tags through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.get_all_project_tags()

    def get_project_tags_by_project(self, project_id: int) -> list[ProjectTagRow]:
        """Get project tags by project through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.get_project_tags_by_project(project_id)

    def get_project_tag_by_id(self, pt_id: int) -> ProjectTag | None:
        """Get project tag by id through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.get_project_tag_by_id(pt_id)

    def create_project_tag(self, pt: ProjectTag) -> int:
        """Create project tag through one transaction."""
        pt = normalize_project_tag(pt)
        with self._gateway.transaction(write=True) as store:
            return store.create_project_tag(pt)

    def update_project_tag(self, pt: ProjectTag) -> bool:
        """Update project tag through one transaction."""
        if pt.id is None:
            return False
        pt = normalize_project_tag(pt)
        with self._gateway.transaction(write=True) as store:
            return store.update_project_tag(pt)

    def delete_project_tag(self, pt_id: int) -> bool:
        """Delete project tag through one transaction."""
        with self._gateway.transaction(write=True) as store:
            return store.delete_project_tag(pt_id)

    def get_task_tags_page(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        search: str = "",
        filters: dict[str, object] | None = None,
        sort: str = "id",
        ascending: bool = False,
    ) -> TaskTagPage:
        """Validate the component query and read counts/rows in one snapshot.

        Filter values are dynamic JSON at the component boundary. Convert their
        display values to strings before passing them to parameterized queries.
        """
        if not isinstance(search, str) or not isinstance(sort, str):
            raise ValueError("Invalid tag search or sorting request.")
        if filters is not None and not isinstance(filters, dict):
            raise ValueError("Invalid tag filter request.")
        try:
            page, page_size = int(page), int(page_size)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid tag page request.") from exc
        filters = {key: str(value or "").strip() for key, value in (filters or {}).items()}
        with self._gateway.transaction(write=False) as store:
            return store.get_task_tags_page(
                page=page,
                page_size=page_size,
                search=search,
                filters=filters,
                sort=sort,
                ascending=ascending,
            )

    def get_all_task_tags(self) -> list[TaskTagRow]:
        """Get all task tags through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.get_all_task_tags()

    def get_task_tags_by_task(self, task_id: int) -> list[TaskTagRow]:
        """Get task tags by task through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.get_task_tags_by_task(task_id)

    def get_task_tag_by_id(self, tt_id: int) -> TaskTag | None:
        """Get task tag by id through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.get_task_tag_by_id(tt_id)

    def create_task_tag(self, tt: TaskTag) -> int:
        """Create task tag through one transaction."""
        tt = normalize_task_tag(tt)
        with self._gateway.transaction(write=True) as store:
            return store.create_task_tag(tt)

    def update_task_tag(self, tt: TaskTag) -> bool:
        """Update task tag through one transaction."""
        if tt.id is None:
            return False
        tt = normalize_task_tag(tt)
        with self._gateway.transaction(write=True) as store:
            return store.update_task_tag(tt)

    def delete_task_tag(self, tt_id: int) -> bool:
        """Delete task tag through one transaction."""
        with self._gateway.transaction(write=True) as store:
            return store.delete_task_tag(tt_id)

    def get_task_tags_by_task_ids(self, task_ids: list[int]) -> dict[int, list[TagLink]]:
        """Get task tags by task ids through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.get_task_tags_by_task_ids(task_ids)

    def get_project_tags_by_project_ids(self, project_ids: list[int]) -> dict[int, list[TagLink]]:
        """Get project tags by project ids through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.get_project_tags_by_project_ids(project_ids)

    def project_choices(self) -> list[EntityChoice]:
        """Project choices through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.project_choices()

    def search_task_choices(self, search: str = "", *, limit: int = 50) -> list[TaskChoice]:
        """Search task choices through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.search_task_choices(search, limit=limit)

    def get_task_choice(self, task_id: int) -> TaskChoice | None:
        """Get task choice through one transaction."""
        with self._gateway.transaction(write=False) as store:
            return store.get_task_choice(task_id)
