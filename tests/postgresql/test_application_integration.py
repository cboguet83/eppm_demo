"""Native portfolio workflow across schema, project, planning and budget services."""

import unittest

import pandas as pd
import pytest

from app.application.services.business_access import BusinessAccess
from app.main import create_budget_service, create_planning_service, create_project_service, create_schema_service
from app.presentation.components import schema_frames
from app.presentation.components.planning_catalog import flatten_dynamic_attributes
from app.runtime import RuntimeResources
from tests.postgresql.ui import runtime as runtime, access as access


class TestApplicationIntegration(unittest.TestCase):
    """Use actual PostgreSQL actors for the complete portfolio lifecycle."""

    @pytest.fixture(autouse=True)
    def native_setup(self, runtime: RuntimeResources, access: BusinessAccess) -> None:
        """Bind the four application layers to the same native resources."""
        self.resources = runtime
        self.access = access
        self.schema_repo = create_schema_service(runtime, access=access)
        self.project_repo = create_project_service(runtime, access=access)
        self.milestone_repo = create_planning_service(runtime, access=access)

    def test_full_portfolio_lifecycle(self) -> None:
        """Verify full lifecycle: create schema -> create project -> add milestone -> calculate KPIs -> delete."""
        # 1. Add new schema group and parameter
        grp_id = self.schema_repo.create_group("Cloud Operations", 10)
        self.schema_repo.create_parameter("PRM_CLD", grp_id, "Cloud Target", "ENUM")
        self.schema_repo.add_option("PRM_CLD", "GCP", 1)
        self.schema_repo.add_option("PRM_CLD", "Azure", 2)

        # 2. Add new project using the dynamic parameter
        new_pid = 101
        self.project_repo.create_project(
            project_id=new_pid,
            name="Cloud Migration",
            status="In Progress",
            dynamic_attributes={"PRM_CLD": "GCP"},
        )

        # 3. Add milestones
        self.milestone_repo.create_milestone(
            project_id=new_pid,
            task_name="Assessment",
            phase="Phase 1",
            start_date="2026-01-01",
            end_date="2026-02-01",
            progress_pct=100,
        )

        # 4. Fetch projects and verify metrics & attribute flattening
        df_projects = pd.DataFrame(create_project_service(self.resources, access=self.access).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(self.resources, access=self.access).get_all_parameters())))
        df_params = schema_frames.parameters_frame(self.schema_repo.get_all_parameters())
        metrics = create_budget_service(self.resources, access=self.access).get_report().metrics
        df_flattened = flatten_dynamic_attributes(df_projects, df_params)

        self.assertIn("PRM_CLD", df_flattened.columns)
        self.assertEqual(
            df_flattened.loc[df_flattened["id"] == new_pid, "PRM_CLD"].values[0],
            "GCP",
        )
        self.assertGreaterEqual(metrics.total_projects, 4)

        # 5. Clean up project
        self.project_repo.delete_project(new_pid)
        self.assertFalse(self.project_repo.exists(new_pid))
