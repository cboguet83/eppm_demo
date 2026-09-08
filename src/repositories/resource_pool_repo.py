"""Compatibility facade for legacy pool DataFrames and SQLite exceptions."""

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from app.domain.resources.models import AssignmentLink

import pandas as pd

from app.application.exceptions import ResourcePoolConflictError, ResourcePoolStorageError
from app.main import create_organization_service, create_resource_pool_service
from app.domain.resources.models import (
    PoolAssignment,
    PoolCapacityDetail,
    PoolMapping,
    ResourcePool,
    ResourcePoolGroup,
)
from app.presentation.components.resource_pool_frames import (
    pools_frame,
    groups_frame,
    all_members_frame,
    members_frame,
    mappings_frame,
    assignments_frame,
)
from src.repositories.organization_repo import legacy_organization_errors


@contextmanager
def legacy_pool_errors() -> Iterator[None]:
    """Preserve legacy SQLite exception types without exposing SQL errors in migrated UI."""
    try:
        yield
    except (ResourcePoolConflictError, ResourcePoolStorageError) as exc:
        if isinstance(exc.__cause__, sqlite3.DatabaseError):
            raise exc.__cause__ from exc
        raise


class ResourcePoolRepository:
    """Adapt legacy frames and entry points to the new application service."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain the path used by legacy planning and seeding callers."""
        self.db_path = db_path
        self.service = create_resource_pool_service(db_path)

    def get_all_pools(self) -> pd.DataFrame:
        """Get all pools through the application service."""
        with legacy_pool_errors():
            return pools_frame(self.service.get_all_pools())

    def get_all_resource_pools(self) -> pd.DataFrame:
        """Retrieves all resource pools (alias for get_all_pools).

        Returns:
            pd.DataFrame: Table of resource pools.
        """
        return self.get_all_pools()

    def get_pool_capacity_detail(self, pool_id: int) -> PoolCapacityDetail:
        """Convenience method to compute capacity breakdown and daily overassignments.

        Args:
            pool_id: Resource pool ID.

        Returns:
            PoolCapacityDetail: Detailed capacity calculation.
        """
        from src.repositories.milestone_repo import MilestoneRepository
        from src.repositories.organization_repo import OrganizationRepository
        from src.services.resource_pool_service import ResourcePoolService

        org_repo = OrganizationRepository(self.db_path)
        milestone_repo = MilestoneRepository(self.db_path)
        return ResourcePoolService.calculate_pool_capacity(pool_id, org_repo, self, milestone_repo)

    def get_pool_by_id(self, pool_id: int) -> ResourcePool | None:
        """Get pool by id through the application service."""
        with legacy_pool_errors():
            return self.service.get_pool_by_id(pool_id)

    def create_pool(self, pool: ResourcePool) -> int:
        """Create pool through the application service."""
        with legacy_pool_errors():
            return self.service.create_pool(pool)

    def update_pool(self, pool: ResourcePool) -> bool:
        """Update pool through the application service."""
        with legacy_pool_errors():
            return self.service.update_pool(pool)

    def delete_pool(self, pool_id: int) -> bool:
        """Delete pool through the application service."""
        with legacy_pool_errors():
            return self.service.delete_pool(pool_id)

    def get_all_pool_groups(self) -> pd.DataFrame:
        """Get all pool groups through the application service."""
        with legacy_pool_errors():
            return groups_frame(self.service.get_all_pool_groups())

    def get_all_group_members(self) -> pd.DataFrame:
        """Get all group members through the application service."""
        with legacy_pool_errors():
            return all_members_frame(self.service.get_all_group_members())

    def get_pool_group_by_id(self, group_id: int) -> ResourcePoolGroup | None:
        """Get pool group by id through the application service."""
        with legacy_pool_errors():
            return self.service.get_pool_group_by_id(group_id)

    def create_pool_group(self, group: ResourcePoolGroup) -> int:
        """Create pool group through the application service."""
        with legacy_pool_errors():
            return self.service.create_pool_group(group)

    def update_pool_group(self, group: ResourcePoolGroup) -> bool:
        """Update pool group through the application service."""
        with legacy_pool_errors():
            return self.service.update_pool_group(group)

    def delete_pool_group(self, group_id: int) -> bool:
        """Delete pool group through the application service."""
        with legacy_pool_errors():
            return self.service.delete_pool_group(group_id)

    def get_group_members(self, group_id: int) -> pd.DataFrame:
        """Get group members through the application service."""
        with legacy_pool_errors():
            return members_frame(self.service.get_group_members(group_id))

    def get_group_direct_member_ids(self, group_id: int) -> tuple[list[int], list[int]]:
        """Get group direct member ids through the application service."""
        with legacy_pool_errors():
            return self.service.get_group_direct_member_ids(group_id)

    def would_create_group_cycle(self, group_id: int, child_group_id: int) -> bool:
        """Would create group cycle through the application service."""
        with legacy_pool_errors():
            return self.service.would_create_group_cycle(group_id, child_group_id)

    def replace_group_members(
        self,
        group_id: int,
        pool_ids: list[int],
        child_group_ids: list[int],
    ) -> None:
        """Replace group members through the application service."""
        with legacy_pool_errors():
            return self.service.replace_group_members(group_id, pool_ids, child_group_ids)

    def get_group_descendant_pool_ids(self, group_id: int) -> list[int]:
        """Get group descendant pool ids through the application service."""
        with legacy_pool_errors():
            return self.service.get_group_descendant_pool_ids(group_id)

    def get_mappings_by_pool(self, pool_id: int) -> pd.DataFrame:
        """Get mappings by pool through the application service."""
        with legacy_pool_errors():
            return mappings_frame(self.service.get_mappings_by_pool(pool_id))

    def get_all_mappings(self) -> pd.DataFrame:
        """Get all mappings through the application service."""
        with legacy_pool_errors():
            return mappings_frame(self.service.get_all_mappings())

    def create_mapping(self, mapping: PoolMapping) -> int:
        """Create mapping through the application service."""
        with legacy_pool_errors():
            return self.service.create_mapping(mapping)

    def update_mapping(self, mapping_id: int, allocation_pct: float) -> bool:
        """Update mapping through the application service."""
        with legacy_pool_errors():
            return self.service.update_mapping(mapping_id, allocation_pct)

    def delete_mapping(self, mapping_id: int) -> bool:
        """Delete mapping through the application service."""
        with legacy_pool_errors():
            return self.service.delete_mapping(mapping_id)

    def get_assignments(
        self,
        pool_id: int | None = None,
        project_id: int | None = None,
        task_id: int | None = None,
        only_project_level: bool = False,
    ) -> pd.DataFrame:
        """Get assignments through the application service."""
        with legacy_pool_errors():
            return assignments_frame(
                self.service.get_assignments(pool_id, project_id, task_id, only_project_level)
            )

    def get_assignment_by_id(self, assignment_id: int) -> PoolAssignment | None:
        """Get assignment by id through the application service."""
        with legacy_pool_errors():
            return self.service.get_assignment_by_id(assignment_id)

    def create_assignment(self, assignment: PoolAssignment) -> int:
        """Create assignment through the application service."""
        with legacy_pool_errors():
            return self.service.create_assignment(assignment)

    def update_assignment(self, assignment: PoolAssignment) -> bool:
        """Update assignment through the application service."""
        with legacy_pool_errors():
            return self.service.update_assignment(assignment)

    def delete_assignment(self, assignment_id: int) -> bool:
        """Delete assignment through the application service."""
        with legacy_pool_errors():
            return self.service.delete_assignment(assignment_id)

    def get_task_assignments_map(self, task_ids: list[int]) -> dict[int, list[AssignmentLink]]:
        """Get task assignments map through the application service."""
        with legacy_pool_errors():
            return self.service.get_task_assignments_map(task_ids)

    def get_project_assignments_map(
        self, project_ids: list[int]
    ) -> dict[int, list[AssignmentLink]]:
        """Get project assignments map through the application service."""
        with legacy_pool_errors():
            return self.service.get_project_assignments_map(project_ids)

    def get_team_functions(self, team_id: int) -> list[int]:
        """Delegate team membership to the organization application service."""
        with legacy_organization_errors():
            return create_organization_service(self.db_path).get_team_functions(team_id)

    def set_team_functions(self, team_id: int, function_ids: list[int]) -> None:
        """Delegate team membership to the organization application service."""
        with legacy_organization_errors():
            return create_organization_service(self.db_path).set_team_functions(
                team_id, function_ids
            )

    def add_team_function(self, team_id: int, function_id: int) -> bool:
        """Delegate team membership to the organization application service."""
        with legacy_organization_errors():
            return create_organization_service(self.db_path).add_team_function(
                team_id, function_id
            )

    def remove_team_function(self, team_id: int, function_id: int) -> bool:
        """Delegate team membership to the organization application service."""
        with legacy_organization_errors():
            return create_organization_service(self.db_path).remove_team_function(
                team_id, function_id
            )
