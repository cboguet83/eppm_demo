"""Display-only DataFrame conversion for typed tag projections."""

from dataclasses import asdict
import pandas as pd
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


def get_all_tag_groups_frame(records: list[TagGroupRow]) -> pd.DataFrame:
    """Preserve the get all tag groups table columns, including empty results."""
    return pd.DataFrame([asdict(row) for row in records], columns=["id", "tag_group_name"])


def get_all_tags_frame(records: list[DictionaryRow]) -> pd.DataFrame:
    """Preserve the get all tags table columns, including empty results."""
    return pd.DataFrame(
        [asdict(row) for row in records], columns=["id", "tag", "tag_group_id", "tag_group_name"]
    )


def get_tags_by_group_name_frame(records: list[DictionaryRow]) -> pd.DataFrame:
    """Preserve the get tags by group name table columns, including empty results."""
    return pd.DataFrame(
        [asdict(row) for row in records], columns=["id", "tag", "tag_group_id", "tag_group_name"]
    )


def get_project_tag_group_tags_frame(records: list[DictionaryRow]) -> pd.DataFrame:
    """Preserve the get project tag group tags table columns, including empty results."""
    return pd.DataFrame(
        [asdict(row) for row in records], columns=["id", "tag", "tag_group_id", "tag_group_name"]
    )


def get_task_tag_group_tags_frame(records: list[DictionaryRow]) -> pd.DataFrame:
    """Preserve the get task tag group tags table columns, including empty results."""
    return pd.DataFrame(
        [asdict(row) for row in records], columns=["id", "tag", "tag_group_id", "tag_group_name"]
    )


def get_all_resource_pool_tags_frame(records: list[PoolTagRow]) -> pd.DataFrame:
    """Preserve the get all resource pool tags table columns, including empty results."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=["id", "pool_id", "pool_name", "tag_id", "tag_name", "tag_group_name"],
    )


def get_resource_pool_tags_frame(records: list[PoolTagRow]) -> pd.DataFrame:
    """Preserve the get resource pool tags table columns, including empty results."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=["id", "pool_id", "tag_id", "tag_name", "tag_group_name"],
    )


def get_all_project_tags_frame(records: list[ProjectTagRow]) -> pd.DataFrame:
    """Preserve the get all project tags table columns, including empty results."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=[
            "id",
            "project_id",
            "project_name",
            "tag_id",
            "tag_name",
            "tag_group_name",
            "free_tag",
        ],
    )


def get_project_tags_by_project_frame(records: list[ProjectTagRow]) -> pd.DataFrame:
    """Preserve the get project tags by project table columns, including empty results."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=["id", "project_id", "tag_id", "tag_name", "tag_group_name", "free_tag"],
    )


def get_all_task_tags_frame(records: list[TaskTagRow]) -> pd.DataFrame:
    """Preserve the get all task tags table columns, including empty results."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=[
            "id",
            "task_id",
            "task_name",
            "project_id",
            "project_name",
            "tag_id",
            "tag_name",
            "tag_group_name",
            "free_tag",
        ],
    )


def get_task_tags_by_task_frame(records: list[TaskTagRow]) -> pd.DataFrame:
    """Preserve the get task tags by task table columns, including empty results."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=["id", "task_id", "tag_id", "tag_name", "tag_group_name", "free_tag"],
    )


def page_frame(page: TaskTagPage) -> dict[str, object]:
    """Convert only one requested page at the component/legacy boundary."""
    data = asdict(page)
    data["rows"] = get_all_task_tags_frame(page.rows)
    return data
