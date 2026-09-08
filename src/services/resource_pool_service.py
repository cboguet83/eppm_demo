"""Legacy repository/DataFrame adapters for the pure capacity domain."""

from datetime import date
from dataclasses import fields

import pandas as pd

from app.domain.organization.models import Employee, EmployeeCalendarException, OrgFunction, Team
from app.domain.resources.models import PoolCapacityDetail, PoolMapping, ProjectPoolStatus
from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.capacity import calculate_capacity
from app.domain.resources.capacity_rules import (
    accumulate_daily_usage,
    calculate_daily_overassignments,
    calculate_pool_scope_daily_usage,
    get_effective_capacity_for_date,
    get_projects_consuming_pool_in_period,
    group_date_intervals,
    project_pool_status,
)
from app.domain.resources.rules import (
    validate_allocation_pct,
    validate_capacity_fte,
    validate_fte,
    validate_pool_name,
)
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository


def _records[T](frame: pd.DataFrame, model: type[T]) -> list[T]:
    """Convert the dynamic legacy DataFrame boundary into typed records."""
    names = {field.name for field in fields(model)}
    return [
        model(
            **{
                key: None if pd.isna(value) else value
                for key, value in row.items()
                if key in names
            }
        )
        for row in frame.to_dict("records")
    ]


class ResourcePoolService:
    """Keep existing callers on the same calculation and validation rules."""

    validate_pool_name = staticmethod(validate_pool_name)
    validate_allocation_pct = staticmethod(validate_allocation_pct)
    validate_fte = staticmethod(validate_fte)
    validate_capacity_fte = staticmethod(validate_capacity_fte)
    get_effective_capacity_for_date = staticmethod(get_effective_capacity_for_date)
    calculate_daily_overassignments = staticmethod(calculate_daily_overassignments)
    _accumulate_daily_usage = staticmethod(accumulate_daily_usage)
    _group_date_intervals = staticmethod(group_date_intervals)
    calculate_pool_scope_daily_usage = staticmethod(calculate_pool_scope_daily_usage)
    get_projects_consuming_pool_in_period = staticmethod(get_projects_consuming_pool_in_period)

    @classmethod
    def calculate_pool_capacity(
        cls,
        pool_id: int,
        org_repo: OrganizationRepository,
        pool_repo: ResourcePoolRepository,
        milestone_repo: MilestoneRepository | None = None,
    ) -> PoolCapacityDetail:
        """Adapt injected legacy repositories while keeping the calculation pure."""
        mappings = _records(pool_repo.get_mappings_by_pool(pool_id), PoolMapping)
        exceptions = _records(
            org_repo.get_employee_calendar_exceptions(), EmployeeCalendarException
        )
        for exception in exceptions:
            exception.start_date = date.fromisoformat(str(exception.start_date))
            exception.end_date = date.fromisoformat(str(exception.end_date))
        assignments = [
            {key: None if pd.isna(value) else value for key, value in row.items()}
            for row in pool_repo.get_assignments(pool_id=pool_id).to_dict("records")
        ]
        bounds = milestone_repo.get_all_project_date_bounds() if milestone_repo is not None else {}
        return calculate_capacity(
            CapacityInputs(
                pool_id=pool_id,
                pool=pool_repo.get_pool_by_id(pool_id),
                mappings=mappings,
                functions=_records(org_repo.get_all_functions(), OrgFunction),
                teams=_records(org_repo.get_all_teams(), Team),
                employees=_records(org_repo.get_all_employees(), Employee),
                exceptions=exceptions,
                team_functions={
                    mapping.target_id: pool_repo.get_team_functions(mapping.target_id)
                    for mapping in mappings
                    if mapping.target_type == "team"
                },
                assignments=assignments,
                project_bounds={int(key): value for key, value in bounds.items()},
            ),
            date.today(),
        )

    @classmethod
    def calculate_project_pool_status(
        cls,
        project_id: int,
        pool_id: int,
        org_repo: OrganizationRepository,
        pool_repo: ResourcePoolRepository,
        milestone_repo: MilestoneRepository | None = None,
    ) -> ProjectPoolStatus:
        """Return the historical status dictionary from the shared domain rule."""
        return project_pool_status(
            project_id, cls.calculate_pool_capacity(pool_id, org_repo, pool_repo, milestone_repo)
        )

    @classmethod
    def get_portfolio_pools_summary(
        cls,
        org_repo: OrganizationRepository,
        pool_repo: ResourcePoolRepository,
        milestone_repo: MilestoneRepository | None = None,
    ) -> list[PoolCapacityDetail]:
        """Retain legacy injected-repository behavior for portfolio callers."""
        return [
            cls.calculate_pool_capacity(int(row["id"]), org_repo, pool_repo, milestone_repo)
            for row in pool_repo.get_all_pools().to_dict("records")
        ]
