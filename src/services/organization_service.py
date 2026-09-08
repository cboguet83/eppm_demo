"""Compatibility delegates for organization validation and display formatting."""

from app.presentation.components.planning_catalog import (
    _build_function_lookup,
    enrich_projects_with_organization,
    get_function_occupant_names,
    get_level_3_managing_function,
)
from app.domain.organization.rules import (
    find_level_3_function,
    is_valid_email,
    validate_function,
    validate_team,
    validate_employee,
    validate_occupation_percentage,
    validate_employee_calendar_exception,
)
from app.presentation.components.organization_frames import (
    enrich_functions,
    enrich_employees,
    enrich_teams,
)
from src.logging_config import get_logger

logger = get_logger(__name__)


class OrganizationService:
    """Provides business validation, formatting, and relational data enrichment for organization entities."""

    is_valid_email = staticmethod(is_valid_email)
    validate_function = staticmethod(validate_function)
    validate_team = staticmethod(validate_team)
    validate_employee = staticmethod(validate_employee)
    validate_occupation_percentage = staticmethod(validate_occupation_percentage)
    validate_employee_calendar_exception = staticmethod(validate_employee_calendar_exception)
    enrich_functions = staticmethod(enrich_functions)
    enrich_employees = staticmethod(enrich_employees)
    enrich_teams = staticmethod(enrich_teams)
    get_level_3_managing_function = staticmethod(get_level_3_managing_function)
    _build_function_lookup = staticmethod(_build_function_lookup)
    _find_level_3_function = staticmethod(find_level_3_function)
    enrich_projects_with_organization = staticmethod(enrich_projects_with_organization)
    get_function_occupant_names = staticmethod(get_function_occupant_names)
