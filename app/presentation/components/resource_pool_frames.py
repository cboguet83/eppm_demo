"""DataFrame formatting at the pool presentation boundary."""

from dataclasses import asdict
import pandas as pd

from app.domain.resources.models import (
    AssignmentRow,
    PoolGroupMemberRow,
    PoolGroupSummary,
    PoolMapping,
    PoolTag,
    PoolTagChoice,
    ResourcePool,
    ResourcePoolGroupMember,
)


def pools_frame(records: list[ResourcePool]) -> pd.DataFrame:
    """Keep stable pools columns, including empty catalogs."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=["id", "name", "description", "capacity_fte", "created_at"],
    )


def groups_frame(records: list[PoolGroupSummary]) -> pd.DataFrame:
    """Keep stable groups columns, including empty catalogs."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=[
            "id",
            "name",
            "description",
            "created_at",
            "hierarchy_type_id",
            "direct_pool_count",
            "child_group_count",
            "recursive_pool_count",
        ],
    )


def all_members_frame(records: list[ResourcePoolGroupMember]) -> pd.DataFrame:
    """Keep stable all members columns, including empty catalogs."""
    return pd.DataFrame(
        [asdict(row) for row in records], columns=["group_id", "pool_id", "child_group_id"]
    )


def members_frame(records: list[PoolGroupMemberRow]) -> pd.DataFrame:
    """Keep stable members columns, including empty catalogs."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=["id", "group_id", "pool_id", "child_group_id", "member_type", "member_name"],
    )


def mappings_frame(records: list[PoolMapping]) -> pd.DataFrame:
    """Keep stable mappings columns, including empty catalogs."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=["id", "pool_id", "target_type", "target_id", "allocation_pct"],
    )


def assignments_frame(records: list[AssignmentRow]) -> pd.DataFrame:
    """Keep stable assignments columns, including empty catalogs."""
    return pd.DataFrame(
        records,
        columns=[
            "id",
            "pool_id",
            "pool_name",
            "project_id",
            "project_name",
            "task_id",
            "task_name",
            "task_start_date",
            "task_end_date",
            "fte_assigned",
            "custom_start_date",
            "custom_end_date",
            "effective_start_date",
            "effective_end_date",
            "schedule_anchor",
            "offset_days",
            "duration_days",
            "notes",
        ],
    )


def tags_frame(records: list[PoolTag]) -> pd.DataFrame:
    """Keep stable tags columns, including empty catalogs."""
    return pd.DataFrame(
        [asdict(row) for row in records],
        columns=["id", "pool_id", "tag_id", "tag_name", "tag_group_name"],
    )


def tag_choices_frame(records: list[PoolTagChoice]) -> pd.DataFrame:
    """Keep stable tag choices columns, including empty catalogs."""
    return pd.DataFrame(
        [asdict(row) for row in records], columns=["id", "tag", "tag_group_id", "tag_group_name"]
    )
