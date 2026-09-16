"""Project use-case, transaction integrity, and new UI regressions."""

from app.main import create_project_service
from app.main import create_schema_service

from app.application.exceptions import ProjectConflictError, ProjectStorageError

from app.infrastructure.postgresql.projects import PostgresProjectGateway, PostgresProjectStore
import pandas as pd

import psycopg

import pytest

from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import native_screen, runtime as runtime, access as access

from app.application.services.projects import ProjectService
from app.domain.projects.project import normalize_project_name, prepare_project_values
from app.infrastructure.postgresql.seed_projects import create_seed_project
from app.main import create_project_type_service, create_portfolio_service


@pytest.fixture
def database(runtime: RuntimeResources, authorized: AuthorizedFixture) -> RuntimeResources:
    """Start project workflows empty while preserving native identity high-water marks."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.project')
    return runtime


def test_core_rejects_blank_names_without_storage_and_copies_default_lists() -> None:
    class UnavailableGateway:
        def run(self, operation, **options):
            raise AssertionError("No storage access for an invalid create")

    with pytest.raises(ValueError, match="name is required"):
        ProjectService(UnavailableGateway()).create_project(name="  ")
    assert normalize_project_name("  Rail  ") == "Rail"
    template = [{"param_id": "p", "param_name": "Tags", "param_type": "TAGS",
                 "mandatory": False, "has_default": True, "default_value": ["Rail"]}]
    result = prepare_project_values(template, {}, {}, creating=True)
    result["p"].append("Road")
    assert template[0]["default_value"] == ["Rail"]
    assert prepare_project_values(template, {}, {}, creating=False) == {}
    for empty in (None, "", []):
        assert prepare_project_values(template, {}, {"p": empty}, creating=True) == {"p": empty}
    with pytest.raises(ValueError, match="do not apply"):
        prepare_project_values(template, {}, {"other": "value"}, creating=True)
    template[0]["mandatory"] = True
    with pytest.raises(ValueError, match="Required property: Tags"):
        prepare_project_values(template, {}, {"p": []}, creating=True)


def test_type_switches_restore_values_without_reapplying_creation_defaults(database: RuntimeResources, access: BusinessAccess) -> None:
    schema = create_schema_service(database, access=access)
    types = create_project_type_service(database, access=access)
    special = types.create_type("Rail")
    schema.create_parameter("p", None, "Rail code", "TEXT", applies_to_all=False, project_type_ids=[special])
    types.save_rule(special, "p", True, has_default=True, default_value="Initial")
    projects = create_project_service(database, access=access)
    pid = projects.create_project(name="Line", project_type_id=special)
    assert projects.get_project_by_id(pid).dynamic_attributes == {"p": "Initial"}
    projects.update_project(pid, "Line", "Draft", 10, 2, {"p": "Edited"})
    projects.update_project(pid, "Line", "Draft", 10, 2, {}, project_type_id=1)
    assert projects.get_project_by_id(pid).dynamic_attributes == {"p": "Edited"}
    assert pd.DataFrame(create_project_service(database, access=access).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(database, access=access).get_all_parameters()))).iloc[0].dynamic_attributes == {}
    projects.update_project(pid, "Line", "Draft", 10, 2, {}, project_type_id=special)
    assert projects.get_project_by_id(pid).dynamic_attributes == {"p": "Edited"}
    fresh = projects.create_project(name="No rail history")
    with pytest.raises(ValueError, match="Required property"):
        projects.update_project(fresh, "Changed", "Draft", 0, 0, {}, project_type_id=special)
    assert projects.get_project_by_id(fresh).name == "No rail history"
    with pytest.raises(AccessDenied):
        projects.update_project(999, "", "Draft", 0, 0, {})
    assert projects.delete_project(999) is False
    assert projects.get_project_by_id(999) is None


def test_partial_property_write_rolls_back_master_and_all_prior_values(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    schema = create_schema_service(database, access=access)
    for pid in ("a", "b"):
        schema.create_parameter(pid, None, pid, "TEXT")
    service = create_project_service(database, access=access)
    pid = service.create_project(name="Original", dynamic_attributes={"a": "old", "b": "old"})
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("""CREATE FUNCTION eppm.reject_second_value() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'internal failure detail' USING ERRCODE='23514'; END $$""")
        conn.execute("""CREATE TRIGGER reject_second_value BEFORE INSERT ON eppm.project_property_value
            FOR EACH ROW WHEN (NEW.param_id='b' AND NEW.text_value='reject') EXECUTE FUNCTION eppm.reject_second_value()""")
    for operation in (
        lambda: service.create_project(name="Must roll back", dynamic_attributes={"a": "new", "b": "reject"}),
        lambda: service.update_project(pid, "Must roll back", "Draft", 99, 22, {"a": "new", "b": "reject"}),
    ):
        with pytest.raises(ProjectConflictError) as error:
            operation()
        assert error.value.__cause__ is None
        assert "internal failure" not in str(error.value)
    project = service.get_project_by_id(pid)
    assert (project.name, project.planned_budget, project.dynamic_attributes) == (
        "Original", 0, {"a": "old", "b": "old"},
    )
    assert create_portfolio_service(database, access=access).get_metrics().total_projects == 1
    with pytest.raises(ProjectConflictError):
        create_project_service(database, access=access).create_project(project_id=pid, name="Duplicate")


def test_delete_rolls_back_dependencies_if_final_delete_fails(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    service = create_project_service(database, access=access)
    pid = service.create_project(name="Project with tasks")
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date,project_plan_id) VALUES (%s,%s,%s,%s,(SELECT id FROM eppm.project_plan WHERE project_id=%s AND is_current))",
                     (pid, "First task", "2026-09-01", "2026-09-02", pid))
        conn.execute("""CREATE FUNCTION eppm.reject_project_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'blocked' USING ERRCODE='23514'; END $$""")
        conn.execute("""CREATE TRIGGER reject_project_delete BEFORE DELETE ON eppm.project
            FOR EACH ROW EXECUTE FUNCTION eppm.reject_project_delete()""")
    with pytest.raises(ProjectConflictError):
        service.delete_project(pid)
    with psycopg.connect(authorized.setup.operator_url) as conn:
        assert conn.execute("SELECT COUNT(*) FROM eppm.project_task WHERE project_id=%s", (pid,)).fetchone()[0] == 1
        conn.execute("DROP TRIGGER reject_project_delete ON eppm.project")
    assert service.delete_project(pid)
    assert not service.exists(pid)


def test_bulk_seeding_uses_the_same_rules_without_committing_its_caller(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("BEGIN")
        create_seed_project(conn, name="Outer transaction")
        with pytest.raises(ValueError, match="name is required"):
            create_seed_project(conn, name=" ")
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
        conn.rollback()
    assert create_portfolio_service(database, access=access).get_metrics().total_projects == 0


def test_gateway_rolls_back_and_returns_usable_leases_without_locking_independent_projects(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    """Failed project changes are atomic while another project writer can commit."""
    service = create_project_service(database, access=access)
    first = service.create_project(name="First")
    second = service.create_project(name="Second")
    with pytest.raises(ValueError, match="Unknown project type"):
        service.create_project(name="Invalid", project_type_id=999)
    gateway = PostgresProjectGateway(database.database, database.key, access=access)

    def abort_edit(store: PostgresProjectStore) -> None:
        assert store.exists(first)
        store.connection.execute("UPDATE eppm.project SET name='Rolled back' WHERE id=%s", (first,))
        with psycopg.connect(authorized.setup.operator_url) as other:
            other.execute("SET LOCAL statement_timeout='1s'")
            other.execute("UPDATE eppm.project SET name='Independent' WHERE id=%s", (second,))
        raise ValueError('cancel')

    with pytest.raises(ValueError, match='cancel'):
        gateway.run(abort_edit, write=True)
    assert service.get_project_by_id(first).name == 'First'
    assert service.get_project_by_id(second).name == 'Independent'


def test_project_storage_errors_are_safe_across_services_and_readers(
    database: RuntimeResources, access: BusinessAccess, caplog: pytest.LogCaptureFixture,
) -> None:
    """Unavailable native storage fails safely before producing display results."""
    service = create_project_service(database, access=access)
    database.database.close()
    with pytest.raises(ProjectStorageError) as error:
        service.exists(1)
    assert 'postgresql://' not in str(error.value) + caplog.text
    assert error.value.__cause__ is None
    with pytest.raises(ProjectStorageError):
        create_portfolio_service(database, access=access, include_allocations=False).get_page([], {})
    with pytest.raises(ProjectStorageError):
        service.get_planning_catalog(())


def test_create_dialog_retains_draft_when_another_user_takes_the_preview_id(database: RuntimeResources, access: BusinessAccess) -> None:
    create_schema_service(database, access=access).create_parameter("p", None, "Notes", "TEXT")
    preview_id = create_project_service(database, access=access).generate_project_id()
    app = native_screen('''
from app.main import create_project_workspace
from app.presentation.components.project_dialogs import open_create_project_dialog
from app.presentation.i18n import set_current_locale
set_current_locale("en")
open_create_project_dialog(create_project_workspace(runtime, access=access))
''', database, access).run()
    assert not app.exception
    app.text_input(key=f"portfolio_create_{preview_id}_p").input("Draft notes").run()
    next(w for w in app.text_input if w.label == "Project Title *").input("My project").run()
    other_id = create_project_service(database, access=access).create_project(name="Another user's project")
    assert other_id == preview_id
    next(b for b in app.button if b.label == "Create project").click().run()
    assert not app.exception
    project = create_project_service(database, access=access).get_project_by_id(other_id + 1)
    assert (project.name, project.dynamic_attributes) == ("My project", {"p": "Draft notes"})
    assert app.session_state["selected_portfolio_project_id"] == other_id + 1
