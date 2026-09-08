"""Compatibility exports for resource domain records."""

from app.domain.resources.models import (
    TeamFunction,
    ResourcePool,
    ResourcePoolGroup,
    ResourcePoolGroupMember,
    PoolMapping,
    PoolAssignment,
    PoolFunctionContribution,
    DailyOverassignment,
    PoolCapacityDetail,
)

__all__ = [
    "TeamFunction",
    "ResourcePool",
    "ResourcePoolGroup",
    "ResourcePoolGroupMember",
    "PoolMapping",
    "PoolAssignment",
    "PoolFunctionContribution",
    "DailyOverassignment",
    "PoolCapacityDetail",
]
