"""Unit tests for organizational structure models, repository, and service layers."""

import os
import tempfile
import unittest

from src.database.schema_init import init_db
from src.models.organization import Employee, FunctionType, HierarchyLevel, OrgFunction
from src.repositories.organization_repo import OrganizationRepository
from src.services.organization_service import OrganizationService


class TestOrganization(unittest.TestCase):
    """Test suite covering OrganizationRepository and OrganizationService."""

    def setUp(self) -> None:
        """Sets up a temporary SQLite database for test isolation."""
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()
        init_db(self.db_path)
        self.repo = OrganizationRepository(self.db_path)

    def tearDown(self) -> None:
        """Cleans up the temporary SQLite database."""
        if os.path.exists(self.db_path):
            try:
                os.unlink(self.db_path)
            except PermissionError:
                pass

    def test_hierarchy_level_crud(self) -> None:
        """Verify Create, Read, Update, Delete operations for Hierarchy Levels."""
        # 1. Create top level
        l1_id = self.repo.create_hierarchy_level(HierarchyLevel(name="Executive Tier", level=1))
        self.assertIsInstance(l1_id, int)
        self.assertGreater(l1_id, 0)

        # 2. Create child level
        l2_id = self.repo.create_hierarchy_level(
            HierarchyLevel(name="VP Tier", level=2, parent_hierarchy_level_id=l1_id)
        )

        # 3. Read
        l1 = self.repo.get_hierarchy_level_by_id(l1_id)
        self.assertIsNotNone(l1)
        self.assertEqual(l1.name, "Executive Tier")
        self.assertEqual(l1.level, 1)
        self.assertIsNone(l1.parent_hierarchy_level_id)

        l2 = self.repo.get_hierarchy_level_by_id(l2_id)
        self.assertIsNotNone(l2)
        self.assertEqual(l2.parent_hierarchy_level_id, l1_id)

        # 4. Update
        updated = self.repo.update_hierarchy_level(
            HierarchyLevel(hierarchy_level_id=l1_id, name="C-Suite Tier", level=1)
        )
        self.assertTrue(updated)
        l1_reloaded = self.repo.get_hierarchy_level_by_id(l1_id)
        self.assertEqual(l1_reloaded.name, "C-Suite Tier")

        # 5. List all
        df_levels = self.repo.get_all_hierarchy_levels()
        self.assertEqual(len(df_levels), 2)

        # 6. Delete
        deleted = self.repo.delete_hierarchy_level(l2_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.repo.get_hierarchy_level_by_id(l2_id))

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
        """Verify Functions CRUD with function_type_id and primary/dual manager relationship mapping."""
        hl_id = self.repo.create_hierarchy_level(HierarchyLevel(name="Management Tier", level=2))
        ft_exec = self.repo.create_function_type(FunctionType(function_type="Executive"))
        ft_tech = self.repo.create_function_type(FunctionType(function_type="Technical"))

        # Create CEO function with function_type_id
        ceo_id = self.repo.create_function(
            OrgFunction(name="Chief Executive Officer", hierarchy_level_id=hl_id, function_type_id=ft_exec)
        )

        # Create CTO with primary manager as CEO and function_type_id
        cto_id = self.repo.create_function(
            OrgFunction(
                name="Chief Technology Officer",
                hierarchy_level_id=hl_id,
                function_type_id=ft_tech,
                manager_function_id=ceo_id,
            )
        )

        # Create Lead Architect with primary manager CTO and dual manager CEO
        arch_id = self.repo.create_function(
            OrgFunction(
                name="Principal Architect",
                hierarchy_level_id=hl_id,
                function_type_id=ft_tech,
                manager_function_id=cto_id,
                dual_manager_function_id=ceo_id,
            )
        )

        arch = self.repo.get_function_by_id(arch_id)
        self.assertIsNotNone(arch)
        self.assertEqual(arch.name, "Principal Architect")
        self.assertEqual(arch.function_type_id, ft_tech)
        self.assertEqual(arch.manager_function_id, cto_id)
        self.assertEqual(arch.dual_manager_function_id, ceo_id)

        # Update
        updated = self.repo.update_function(
            OrgFunction(
                function_id=arch_id,
                name="Chief Architect",
                hierarchy_level_id=hl_id,
                function_type_id=ft_exec,
                manager_function_id=cto_id,
                dual_manager_function_id=None,
            )
        )
        self.assertTrue(updated)
        arch_mod = self.repo.get_function_by_id(arch_id)
        self.assertEqual(arch_mod.name, "Chief Architect")
        self.assertEqual(arch_mod.function_type_id, ft_exec)
        self.assertIsNone(arch_mod.dual_manager_function_id)

        # Delete
        self.assertTrue(self.repo.delete_function(arch_id))
        self.assertIsNone(self.repo.get_function_by_id(arch_id))

    def test_employee_crud_and_code_generation(self) -> None:
        """Verify Employee CRUD, auto-calculated employee codes, and email uniqueness."""
        hl_id = self.repo.create_hierarchy_level(HierarchyLevel(name="Staff Tier", level=3))
        ft_id = self.repo.create_function_type(FunctionType(function_type="Full Time"))
        fn_id = self.repo.create_function(
            OrgFunction(name="Senior Developer", hierarchy_level_id=hl_id, function_type_id=ft_id)
        )

        code_1 = self.repo.generate_next_employee_code()
        self.assertEqual(code_1, "EMP-001")

        e1_id = self.repo.create_employee(
            Employee(
                firstname="John",
                lastname="Doe",
                email="jdoe@example.com",
                mobile="+1-555-1234",
                sigle="JDO",
                employee_code=code_1,
                function_id=fn_id,
            )
        )
        self.assertGreater(e1_id, 0)

        # Next code should be EMP-002
        code_2 = self.repo.generate_next_employee_code()
        self.assertEqual(code_2, "EMP-002")

        # Check email exists
        self.assertTrue(self.repo.check_email_exists("jdoe@example.com"))
        self.assertTrue(self.repo.check_email_exists("JDOE@EXAMPLE.COM"))  # Case-insensitive
        self.assertFalse(self.repo.check_email_exists("jdoe@example.com", exclude_id=e1_id))
        self.assertFalse(self.repo.check_email_exists("other@example.com"))

        # Check code exists
        self.assertTrue(self.repo.check_code_exists("EMP-001"))
        self.assertFalse(self.repo.check_code_exists("EMP-001", exclude_id=e1_id))
        self.assertFalse(self.repo.check_code_exists("EMP-002"))

        # Update
        updated = self.repo.update_employee(
            Employee(
                employee_id=e1_id,
                firstname="Jonathan",
                lastname="Doe",
                email="jdoe_updated@example.com",
                mobile="+1-555-9999",
                sigle="JDO",
                employee_code="EMP-001",
                function_id=fn_id,
            )
        )
        self.assertTrue(updated)
        emp_mod = self.repo.get_employee_by_id(e1_id)
        self.assertEqual(emp_mod.firstname, "Jonathan")
        self.assertEqual(emp_mod.email, "jdoe_updated@example.com")

        # Delete
        self.assertTrue(self.repo.delete_employee(e1_id))
        self.assertIsNone(self.repo.get_employee_by_id(e1_id))

    def test_organization_service_validation_and_enrichment(self) -> None:
        """Verify OrganizationService email checking, field validators, and DataFrame enrichment."""
        # Validation checks
        self.assertTrue(OrganizationService.is_valid_email("user@enterprise.com"))
        self.assertFalse(OrganizationService.is_valid_email("not-an-email"))
        self.assertFalse(OrganizationService.is_valid_email(""))

        with self.assertRaises(ValueError):
            OrganizationService.validate_hierarchy_level("", 1)
        with self.assertRaises(ValueError):
            OrganizationService.validate_hierarchy_level("Valid", 0)

        with self.assertRaises(ValueError):
            OrganizationService.validate_function("", 1)
        with self.assertRaises(ValueError):
            OrganizationService.validate_function("Valid", None)

        with self.assertRaises(ValueError):
            OrganizationService.validate_employee("", "Last", "valid@email.com", "EMP-001")
        with self.assertRaises(ValueError):
            OrganizationService.validate_employee("First", "", "valid@email.com", "EMP-001")
        with self.assertRaises(ValueError):
            OrganizationService.validate_employee("First", "Last", "bad-email", "EMP-001")
        with self.assertRaises(ValueError):
            OrganizationService.validate_employee("First", "Last", "valid@email.com", "")

        # Enrichment test
        hl_id = self.repo.create_hierarchy_level(HierarchyLevel(name="Executive Tier", level=1))
        ft_id = self.repo.create_function_type(FunctionType(function_type="Full Time"))
        fn_id = self.repo.create_function(
            OrgFunction(name="Director of Engineering", hierarchy_level_id=hl_id, function_type_id=ft_id)
        )
        self.repo.create_employee(
            Employee(
                firstname="Alice",
                lastname="Smith",
                email="asmith@enterprise.com",
                employee_code="EMP-001",
                function_id=fn_id,
            )
        )

        df_emps = self.repo.get_all_employees()
        df_funcs = self.repo.get_all_functions()
        df_types = self.repo.get_all_function_types()

        # Check function enrichment
        enriched_funcs = OrganizationService.enrich_functions(df_funcs, self.repo.get_all_hierarchy_levels(), df_types)
        self.assertIn("function_type_name", enriched_funcs.columns)
        self.assertEqual(enriched_funcs.iloc[0]["function_type_name"], "Full Time")

        # Check employee enrichment inherits function_type_name
        enriched_emps = OrganizationService.enrich_employees(df_emps, df_funcs, df_types)
        self.assertIn("full_name", enriched_emps.columns)
        self.assertIn("function_name", enriched_emps.columns)
        self.assertIn("function_type_name", enriched_emps.columns)
        self.assertEqual(enriched_emps.iloc[0]["full_name"], "SMITH Alice")
        self.assertEqual(enriched_emps.iloc[0]["function_name"], "Director of Engineering")
        self.assertEqual(enriched_emps.iloc[0]["function_type_name"], "Full Time")


if __name__ == "__main__":
    unittest.main()
