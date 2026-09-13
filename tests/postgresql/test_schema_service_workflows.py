"""Schema service identity and display-order contracts on PostgreSQL."""

import unittest

import pytest

from app.application.services.business_access import BusinessAccess
from app.main import create_schema_service
from app.runtime import RuntimeResources
from tests.postgresql.ui import runtime as runtime, access as access


class TestSchemaServices(unittest.TestCase):
    """Preserve service-generated reference identifiers and ordering."""

    @pytest.fixture(autouse=True)
    def native_setup(self, runtime: RuntimeResources, access: BusinessAccess) -> None:
        """Bind schema operations to the real native business-admin fixture."""
        self.resources = runtime
        self.access = access

    def test_schema_service_generate_param_id(self) -> None:
        """Verify sequential parameter ID generation."""
        repo = create_schema_service(self.resources, access=self.access)
        pid1 = create_schema_service(self.resources, access=self.access).generate_param_id()
        self.assertEqual(pid1, "PRM_001")

        repo.create_parameter("PRM_001", None, "Param 1", 'TEXT')
        pid2 = create_schema_service(self.resources, access=self.access).generate_param_id()
        self.assertEqual(pid2, "PRM_002")


    def test_schema_service_next_available_group_order(self) -> None:
        """Verify next available group order computation."""
        repo = create_schema_service(self.resources, access=self.access)
        self.assertEqual(create_schema_service(self.resources, access=self.access).get_next_available_group_order(), 1)

        repo.create_group("Group A", 1)
        repo.create_group("Group B", 2)
        self.assertEqual(create_schema_service(self.resources, access=self.access).get_next_available_group_order(), 3)
