"""Unit tests for organizational structure models, repository, and service layers."""

from app.application.exceptions import OrganizationConflictError

from app.domain.organization.rules import is_valid_email
from app.domain.organization.rules import validate_employee
from app.domain.organization.rules import validate_function
from app.domain.organization.rules import validate_team
from app.presentation.components.organization_frames import enrich_employees
from app.presentation.components.organization_frames import enrich_functions
from app.presentation.components.organization_frames import enrich_teams

from app.presentation.components import organization_frames

import unittest
from datetime import date
import pytest

from app.domain.organization.rules import validate_employee_calendar_exception
from app.domain.organization.models import Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team
from app.main import create_organization_service
from tests.postgresql.ui import runtime as runtime, access as access


class TestOrganization(unittest.TestCase):
    """Test suite covering create_organization_service and OrganizationService."""

    @pytest.fixture(autouse=True)
    def native_setup(self, runtime, access) -> None:
        """Exercise organization workflows with a restricted native actor."""
        self.repo = create_organization_service(runtime, access=access)

    def test_function_type_crud(self) -> None:
        """Verify Create, Read, Update, Delete operations for Function Types."""
        t1_id = self.repo.create_function_type(FunctionType(function_type="Core Engineering"))
        self.assertGreater(t1_id, 0)

        ft = self.repo.get_function_type_by_id(t1_id)
        self.assertIsNotNone(ft)
        self.assertEqual(ft.function_type, "Core Engineering")

        updated = self.repo.update_function_type(
            FunctionType(function_type_id=t1_id, function_type="Technical & Engineering")
        )
        self.assertTrue(updated)
        ft_updated = self.repo.get_function_type_by_id(t1_id)
        self.assertEqual(ft_updated.function_type, "Technical & Engineering")

        deleted = self.repo.delete_function_type(t1_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.repo.get_function_type_by_id(t1_id))

    def test_function_crud_with_types_and_managers(self) -> None:
        """Verify Functions CRUD with hierarchy levels, derived reports, and manager relations."""
        ft_exec = self.repo.create_function_type(FunctionType(function_type="Executive"))
        ft_tech = self.repo.create_function_type(FunctionType(function_type="Technical"))

        # Create CEO function
        ceo_id = self.repo.create_function(
            OrgFunction(name="Chief Executive Officer", hierarchy_level=1, function_type_id=ft_exec)
        )

        # Create CTO with primary manager as CEO
        cto_id = self.repo.create_function(
            OrgFunction(
                name="Chief Technology Officer",
                hierarchy_level=2,
                function_type_id=ft_tech,
                manager_function_id=ceo_id,

            )
        )

        # Create Lead Architect with primary manager CTO and dual manager CEO
        arch_id = self.repo.create_function(
            OrgFunction(
                name="Principal Architect",
                hierarchy_level=3,
                function_type_id=ft_tech,
                manager_function_id=cto_id,
                dual_manager_function_id=ceo_id,

            )
        )

        arch = self.repo.get_function_by_id(arch_id)
        self.assertIsNotNone(arch)
        self.assertEqual(arch.name, "Principal Architect")
        self.assertEqual(arch.hierarchy_level, 3)
        self.assertFalse(organization_frames.functions_frame([arch]).iloc[0]["has_reports"])
        self.assertEqual(arch.function_type_id, ft_tech)
        self.assertEqual(arch.manager_function_id, cto_id)
        self.assertEqual(arch.dual_manager_function_id, ceo_id)

        # Update
        updated = self.repo.update_function(
            OrgFunction(
                function_id=arch_id,
                name="Chief Architect",
                hierarchy_level=2,
                function_type_id=ft_exec,
                manager_function_id=cto_id,
                dual_manager_function_id=None,

            )
        )
        self.assertTrue(updated)
        arch_mod = self.repo.get_function_by_id(arch_id)
        self.assertEqual(arch_mod.name, "Chief Architect")
        self.assertEqual(arch_mod.hierarchy_level, 2)
        self.assertFalse(organization_frames.functions_frame([arch_mod]).iloc[0]["has_reports"])
        self.assertEqual(arch_mod.function_type_id, ft_exec)
        self.assertIsNone(arch_mod.dual_manager_function_id)

        # Delete
        self.assertTrue(self.repo.delete_function(arch_id))
        self.assertIsNone(self.repo.get_function_by_id(arch_id))

    def test_employee_crud_and_email_uniqueness(self) -> None:
        """Verify Employee CRUD and email uniqueness."""
        ft_id = self.repo.create_function_type(FunctionType(function_type="Full Time"))
        fn_id = self.repo.create_function(
            OrgFunction(name="Senior Developer", hierarchy_level=3, function_type_id=ft_id)
        )


        e1_id = self.repo.create_employee(
            Employee(
                firstname="John",
                lastname="Doe",
                email="jdoe@example.com",
                mobile="+1-555-1234",
                sigle="JDO",
                function_id=fn_id,
                occupation_percentage=80.0,
            )
        )
        self.assertGreater(e1_id, 0)


        # Check email exists
        self.assertTrue(self.repo.check_email_exists("jdoe@example.com"))
        self.assertTrue(self.repo.check_email_exists("JDOE@EXAMPLE.COM"))  # Case-insensitive
        self.assertFalse(self.repo.check_email_exists("jdoe@example.com", exclude_id=e1_id))
        self.assertFalse(self.repo.check_email_exists("other@example.com"))


        # Update
        updated = self.repo.update_employee(
            Employee(
                employee_id=e1_id,
                firstname="Jonathan",
                lastname="Doe",
                email="jdoe_updated@example.com",
                mobile="+1-555-9999",
                sigle="JDO",
                function_id=fn_id,
            )
        )
        self.assertTrue(updated)
        emp_mod = self.repo.get_employee_by_id(e1_id)
        self.assertEqual(emp_mod.firstname, "Jonathan")
        self.assertEqual(emp_mod.email, "jdoe_updated@example.com")
        self.assertEqual(emp_mod.occupation_percentage, 100.0)

        # Delete
        self.assertTrue(self.repo.delete_employee(e1_id))
        self.assertIsNone(self.repo.get_employee_by_id(e1_id))

    def test_employee_occupation_calendar_exceptions(self) -> None:
        """Verify base occupation, date overrides, overlap checks, and cascade deletion."""
        employee_id = self.repo.create_employee(
            Employee(
                firstname="Jane",
                lastname="Doe",
                email="jane.doe@example.com",
                occupation_percentage=80.0,
            )
        )
        self.assertEqual(
            self.repo.get_effective_occupation_percentage(employee_id, date(2026, 1, 1)),
            80.0,
        )

        exception_id = self.repo.create_employee_calendar_exception(
            EmployeeCalendarException(
                employee_id=employee_id,
                start_date=date(2026, 2, 1),
                end_date=date(2026, 5, 31),
                occupation_percentage=0.0,
                reason="Maternity leave",
            )
        )
        exception = self.repo.get_employee_calendar_exception_by_id(exception_id)
        self.assertIsNotNone(exception)
        self.assertEqual(exception.start_date, date(2026, 2, 1))
        self.assertEqual(exception.end_date, date(2026, 5, 31))
        self.assertEqual(exception.reason, "Maternity leave")

        # The override applies on both boundary dates and the base rate applies outside it.
        self.assertEqual(
            self.repo.get_effective_occupation_percentage(employee_id, date(2026, 2, 1)),
            0.0,
        )
        self.assertEqual(
            self.repo.get_effective_occupation_percentage(employee_id, date(2026, 5, 31)),
            0.0,
        )
        self.assertEqual(
            self.repo.get_effective_occupation_percentage(employee_id, date(2026, 6, 1)),
            80.0,
        )

        with self.assertRaises(ValueError):
            self.repo.create_employee_calendar_exception(
                EmployeeCalendarException(
                    employee_id=employee_id,
                    start_date=date(2026, 5, 1),
                    end_date=date(2026, 6, 30),
                    occupation_percentage=50.0,
                )
            )

        self.assertTrue(self.repo.delete_employee(employee_id))
        self.assertTrue(organization_frames.exceptions_frame(self.repo.get_employee_calendar_exceptions(employee_id)).empty)

    def test_team_crud_and_service_enrichment(self) -> None:
        """Verify Team CRUD operations and enrich_teams."""
        mgr_fn_id = self.repo.create_function(
            OrgFunction(name="Department Manager", hierarchy_level=3)
        )
        # 1. Create team
        t1_id = self.repo.create_team(
            Team(
                team_name="Cloud Platform Team",
                manager_function_id=mgr_fn_id,
            )
        )
        self.assertIsInstance(t1_id, int)
        self.assertGreater(t1_id, 0)

        # 2. Read team
        team = self.repo.get_team_by_id(t1_id)
        self.assertIsNotNone(team)
        self.assertEqual(team.team_name, "Cloud Platform Team")
        self.assertEqual(team.manager_function_id, mgr_fn_id)

        # 3. Update team
        updated = self.repo.update_team(
            Team(
                team_id=t1_id,
                team_name="Core Cloud Team",
                manager_function_id=mgr_fn_id,
            )
        )
        self.assertTrue(updated)
        team_mod = self.repo.get_team_by_id(t1_id)
        self.assertEqual(team_mod.team_name, "Core Cloud Team")

        # 4. List all teams
        df_teams = organization_frames.teams_frame(self.repo.get_all_teams())
        self.assertEqual(len(df_teams), 1)

        # 5. Service enrichment
        df_funcs = organization_frames.functions_frame(self.repo.get_all_functions())
        enriched_teams = enrich_teams(df_teams, df_funcs)
        self.assertIn("manager_function_name", enriched_teams.columns)
        self.assertEqual(enriched_teams.iloc[0]["manager_function_name"], "Department Manager")

        # 6. Delete team
        self.assertTrue(self.repo.delete_team(t1_id))
        self.assertIsNone(self.repo.get_team_by_id(t1_id))

    def test_organization_service_validation_and_enrichment(self) -> None:
        """Verify OrganizationService validation rules and DataFrame enrichment."""
        # Validation checks
        self.assertTrue(is_valid_email("user@enterprise.com"))
        self.assertFalse(is_valid_email("not-an-email"))
        self.assertFalse(is_valid_email(""))

        with self.assertRaises(ValueError):
            validate_function("", 1)
        with self.assertRaises(ValueError):
            validate_function("Valid", None)
        with self.assertRaises(ValueError):
            validate_function("Valid", 0)
        with self.assertRaises(ValueError):
            validate_function("Valid", 1, fte_percentage=-10)
        with self.assertRaises(ValueError):
            validate_function("Valid", 1, fte_percentage=150)

        with self.assertRaises(ValueError):
            validate_team("")
        with self.assertRaises(ValueError):
            validate_team("   ")

        with self.assertRaises(ValueError):
            validate_employee("", "Last", "valid@email.com")
        with self.assertRaises(ValueError):
            validate_employee("First", "", "valid@email.com")
        with self.assertRaises(ValueError):
            validate_employee("First", "Last", "bad-email")
        validate_employee("First", "Last", "valid@email.com")
        with self.assertRaises(ValueError):
            validate_employee(
                "First", "Last", "valid@email.com", occupation_percentage=101
            )
        with self.assertRaises(ValueError):
            validate_employee_calendar_exception(
                date(2026, 2, 1), date(2026, 1, 31), 0
            )

        # Enrichment test
        ft_id = self.repo.create_function_type(FunctionType(function_type="Full Time"))
        fn_id = self.repo.create_function(
            OrgFunction(name="Director of Engineering", hierarchy_level=1, function_type_id=ft_id, fte_percentage=80)
        )
        self.repo.create_employee(
            Employee(
                firstname="Alice",
                lastname="Smith",
                email="asmith@enterprise.com",
                function_id=fn_id,
            )
        )

        df_emps = organization_frames.employees_frame(self.repo.get_all_employees())
        df_funcs = organization_frames.functions_frame(self.repo.get_all_functions())
        df_types = organization_frames.function_types_frame(self.repo.get_all_function_types())

        # Check function enrichment and fte_percentage
        enriched_funcs = enrich_functions(df_funcs, df_types)
        self.assertIn("function_type_name", enriched_funcs.columns)
        self.assertEqual(enriched_funcs.iloc[0]["function_type_name"], "Full Time")
        self.assertEqual(enriched_funcs.iloc[0]["fte_percentage"], 80)
        self.assertEqual(enriched_funcs.iloc[0]["hierarchy_level"], 1)
        self.assertFalse(bool(enriched_funcs.iloc[0]["has_reports"]))

        # Check employee enrichment inherits function_type_name
        enriched_emps = enrich_employees(df_emps, df_funcs, df_types)
        self.assertIn("full_name", enriched_emps.columns)
        self.assertIn("function_name", enriched_emps.columns)
        self.assertIn("function_type_name", enriched_emps.columns)
        self.assertEqual(enriched_emps.iloc[0]["full_name"], "SMITH Alice")
        self.assertEqual(enriched_emps.iloc[0]["function_name"], "Director of Engineering")
        self.assertEqual(enriched_emps.iloc[0]["function_type_name"], "Full Time")

    def test_soft_deleted_function_retains_references_and_blocks_type_deletion(self) -> None:
        """Functions retain employee links; referenced types cannot be deleted."""
        ft_id = self.repo.create_function_type(FunctionType(function_type="Core Type"))
        fn_id = self.repo.create_function(
            OrgFunction(name="Director", hierarchy_level=1, function_type_id=ft_id)
        )
        self.repo.create_employee(
            Employee(
                firstname="Bob",
                lastname="Marley",
                email="bmarley@enterprise.com",
                function_id=fn_id,
            )
        )

        self.assertTrue(self.repo.delete_function(fn_id))
        self.assertIsNone(self.repo.get_function_by_id(fn_id))
        self.assertEqual(self.repo.get_all_employees()[0].function_id, fn_id)

        with self.assertRaisesRegex(ValueError, 'in use'):
            self.repo.delete_function_type(ft_id)


if __name__ == "__main__":
    unittest.main()
