"""Native generated portfolio structures and backed-up reset workflows."""

from pathlib import Path

import psycopg
import pytest

from app.application.ports.maintenance import SeedRequest
from app.application.services.business_access import BusinessAccess
from app.application.services.maintenance import MaintenanceService
from app.infrastructure.postgresql.backup import PostgresTools
from app.main import create_planning_service, create_project_service
from app.operator_services import create_maintenance_service
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access


@pytest.fixture
def maintenance(authorized: AuthorizedFixture, clients: PostgresTools, tmp_path: Path) -> MaintenanceService:
    """Start the isolated native fixture empty and configure real archive tools."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DELETE FROM eppm.project")
    return create_maintenance_service(
        authorized.setup.operator_url, backup_directory=tmp_path, archive_tools=clients,
    )


def test_seed_database_generates_correct_counts_and_structures(
    maintenance: MaintenanceService, runtime: RuntimeResources, access: BusinessAccess,
    authorized: AuthorizedFixture, tmp_path: Path,
) -> None:
    result = maintenance.seed_projects(SeedRequest(
        projects=15, min_tasks=3, max_tasks=8, clean_first=True, random_seed=123,
    ))
    assert result["projects_created"] == 15
    assert 15 * 3 <= result["tasks_created"] <= 15 * 8
    assert result["dependencies_created"] > 0
    projects = create_project_service(runtime, access=access).get_planning_catalog()
    assert len(projects) == 15 and all(isinstance(project["id"], int) for project in projects)
    planning = create_planning_service(runtime, access=access)
    for project in projects:
        assert 3 <= len(planning.get_milestones_by_project(project["id"])) <= 8
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM eppm.task_dependencies WHERE predecessor_project_id IS NULL"
        ).fetchone()[0] > 0
        link_types = {row[0] for row in connection.execute("SELECT DISTINCT link_type FROM eppm.task_dependencies")}
    assert link_types and link_types <= {"FS", "SS", "FF", "SF"}
    assert len(list(tmp_path.glob("*.dump"))) == 1


def test_flush_database_empties_projects_tasks_and_dependencies(
    maintenance: MaintenanceService, runtime: RuntimeResources, access: BusinessAccess,
    authorized: AuthorizedFixture, tmp_path: Path,
) -> None:
    maintenance.seed_projects(SeedRequest(
        projects=10, min_tasks=2, max_tasks=5, clean_first=False, random_seed=99,
    ))
    projects = create_project_service(runtime, access=access)
    assert len(projects.get_planning_catalog()) == 10

    result = maintenance.flush()

    assert result["projects_deleted"] == 10
    assert result["tasks_deleted"] > 0 and result["dependencies_deleted"] > 0
    assert projects.get_planning_catalog() == []
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.project_task").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM eppm.task_dependencies").fetchone() == (0,)
    assert len(list(tmp_path.glob("*.dump"))) == 2


def test_seed_database_with_zero_tasks(
    maintenance: MaintenanceService, runtime: RuntimeResources, access: BusinessAccess,
) -> None:
    result = maintenance.seed_projects(SeedRequest(
        projects=5, min_tasks=0, max_tasks=0, clean_first=True, random_seed=42,
    ))
    assert result["projects_created"] == 5
    assert result["tasks_created"] == 0
    assert result["dependencies_created"] == 0
    projects = create_project_service(runtime, access=access).get_planning_catalog()
    assert len(projects) == 5
    planning = create_planning_service(runtime, access=access)
    assert all(planning.get_milestones_by_project(project["id"]) == [] for project in projects)
