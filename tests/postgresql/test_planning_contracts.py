"""Task use-case integrity, scheduling rules, and native PostgreSQL transaction behavior."""

from app.application.exceptions import PlanningConflictError

import io
import psycopg

import pytest

from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access

from app.application.exceptions import PlanningStorageError
from app.domain.planning.constraints import evaluate_constraints
from app.domain.planning.csv_import import get_csv_template, parse_csv
from app.domain.planning.rules import normalize_dependency, normalize_task
from app.infrastructure.postgresql.planning import PostgresPlanningGateway, PostgresPlanningStore
from app.main import create_planning_service
from app.presentation.components.planning_imports import csv_text


@pytest.fixture
def database(runtime: RuntimeResources, authorized: AuthorizedFixture) -> RuntimeResources:
    """Retain native actors while supplying the original schedule labels."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='Build' WHERE id=1")
        connection.execute("UPDATE eppm.project SET name='Deploy' WHERE id=2")
    return runtime


def test_task_creation_and_dependency_edit_roll_back_together(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_planning_service(database, access=access)
    with pytest.raises(AccessDenied) as failure:
        service.create_milestone(
            1,
            "Failed",
            "",
            "2026-01-01",
            "2026-01-02",
            0,
            dependencies=[{"predecessor_task_id": 999}],
        )
    assert failure.value.__cause__ is None
    assert service.get_all_milestones() == []
    predecessor = service.create_milestone(1, "First", "", "2026-01-01", "2026-01-01", 0)
    successor = service.create_milestone(
        2, "Original", "", "2026-01-02", "2026-01-03", 0, predecessor_id=predecessor
    )
    original = service.get_milestone_by_id(successor)
    links = service.get_task_dependencies(successor)
    with pytest.raises(AccessDenied):
        service.update_milestone(
            successor,
            "Changed",
            "P",
            "2026-01-10",
            "2026-01-12",
            50,
            dependencies=[{"predecessor_task_id": 999}],
        )
    assert service.get_milestone_by_id(successor) == original
    assert service.get_task_dependencies(successor) == links
    assert service.update_milestone(
        successor, "Changed", "P", "2026-01-10", "2026-01-12", 50, predecessor_id=successor
    )
    assert service.get_milestone_by_id(successor)["predecessor_id"] is None
    assert service.get_task_dependencies(successor) == []
    assert not service.update_milestone(
        999,
        "Missing",
        "",
        "2026-01-01",
        "2026-01-01",
        0,
        dependencies=[{"predecessor_task_id": 9999}],
    )
    with pytest.raises(ValueError, match="no longer exists"):
        service.save_task_dependencies(999, [])


def test_import_validation_and_mid_batch_database_failure_leave_no_partial_rows(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    service = create_planning_service(database, access=access)
    header = "task_name,start_date,end_date\n"
    valid = "Good,2026-01-01,2026-01-02\n"
    with pytest.raises(ValueError, match="Row 3"):
        service.import_csv(1, header + valid + "Bad,2026-02-01,2026-01-01\n")
    assert service.get_all_milestones() == []
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_bad_task() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'internal details' USING ERRCODE='23514'; END $$""")
        connection.execute("""CREATE TRIGGER reject_bad_task BEFORE INSERT ON eppm.project_task
            FOR EACH ROW WHEN (NEW.task_name='Rejected') EXECUTE FUNCTION eppm.reject_bad_task()""")
    with pytest.raises(PlanningConflictError, match="constraint"):
        service.import_csv(1, header + valid + "Rejected,2026-01-01,2026-01-01\n")
    assert service.get_all_milestones() == []
    assert service.bulk_create_milestones([]) == 0
    assert service.import_csv(1, header + valid) == 1


def test_deletion_rollback_restores_links_and_legacy_predecessor_columns(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    service = create_planning_service(database, access=access)
    first = service.create_milestone(1, "First", "", "2026-01-01", "2026-01-02", 0)
    second = service.create_milestone(
        1, "Second", "", "2026-01-03", "2026-01-04", 0, predecessor_id=first
    )
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_task_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'internal details' USING ERRCODE='23514'; END $$""")
        connection.execute(f"""CREATE TRIGGER reject_task_delete BEFORE UPDATE OF is_deleted ON eppm.project_task
            FOR EACH ROW WHEN (OLD.id={first} AND NOT OLD.is_deleted AND NEW.is_deleted) EXECUTE FUNCTION eppm.reject_task_delete()""")
    with pytest.raises(PlanningConflictError):
        service.delete_milestone(first)
    assert service.get_task_dependencies(second)[0]["predecessor_task_id"] == first
    assert service.get_milestone_by_id(second)["predecessor_id"] == first
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DROP TRIGGER reject_task_delete ON eppm.project_task")
    assert service.delete_milestone(first)
    assert service.get_task_dependencies(second) == []
    assert service.get_milestone_by_id(second)["predecessor_id"] is None
    assert not service.delete_milestone(first)


def test_planning_gateway_rolls_back_reuses_leases_and_hides_storage_details(
    database: RuntimeResources, access: BusinessAccess,
    authorized: AuthorizedFixture, caplog: pytest.LogCaptureFixture,
) -> None:
    """Native failures cannot leak credentials or leave an uncommitted task."""
    gateway = PostgresPlanningGateway(database.database, database.key, access=access)
    service = create_planning_service(database, access=access)

    def abort_task(store: PostgresPlanningStore) -> None:
        assert store.connection.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
        store.connection.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date,project_plan_id) VALUES (1,'Rolled back','2026-01-01','2026-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
        with psycopg.connect(authorized.setup.operator_url) as competitor:
            competitor.execute("SET LOCAL statement_timeout='1s'")
            competitor.execute("UPDATE eppm.project SET name='Independent' WHERE id=3")
        raise ValueError('cancel')

    with pytest.raises(ValueError, match='cancel'):
        gateway.run(abort_task, write=True)
    assert service.get_all_milestones() == []
    assert authorized.query('SELECT name FROM eppm.project WHERE id=3', user_id=4) == [('Independent',)]
    with pytest.raises(AccessDenied):
        service.create_milestone(999, 'Unknown project', '', '2026-01-01', '2026-01-01', 0)
    with pytest.raises(PlanningStorageError) as failure:
        gateway.run(lambda store: store.connection.execute('SELECT * FROM eppm.missing_table'))
    assert 'missing_table' not in str(failure.value)
    assert service.get_all_milestones() == []
    database.database.close()
    with pytest.raises(PlanningStorageError) as failure:
        service.get_all_milestones()
    assert 'postgresql://' not in str(failure.value) + caplog.text
    assert failure.value.__cause__ is None


def test_batched_tasks_and_dependencies_share_a_stable_read_snapshot(
    database: RuntimeResources, access: BusinessAccess,
) -> None:
    """A writer commits while the existing read keeps its original dependency snapshot."""
    service = create_planning_service(database, access=access)
    first = service.create_milestone(1, 'First', '', '2026-01-01', '2026-01-02', 0)
    second = service.create_milestone(2, 'Second', '', '2026-01-03', '2026-01-04', 0)
    gateway = PostgresPlanningGateway(database.database, database.key, access=access)

    def snapshot(store: PostgresPlanningStore) -> None:
        assert len(store.get_milestones_for_projects([1, 2])) == 2
        service.add_dependency(second, first)
        assert store.get_dependencies_for_projects([1, 2]) == []

    gateway.run(snapshot)
    assert len(service.get_dependencies_for_projects([1, 2])) == 1
    assert service.get_milestones_for_projects([]) == []
    assert service.get_dependencies_for_projects([]) == []
    assert service.get_project_date_bounds(999) == (None, None)
    assert service.get_all_project_date_bounds()[1] == ('2026-01-01', '2026-01-02')


@pytest.mark.parametrize(
    "change,message",
    [
        ({"task_name": " "}, "name"),
        ({"start_date": "bad"}, "date"),
        ({"start_date": "2026-02-01"}, "after"),
        ({"progress_pct": "bad"}, "progress"),
        ({"phase": ["bad"]}, "text"),
        ({"description": ["bad"]}, "text"),
    ],
)
def test_task_commands_validate_before_persistence(
    database: RuntimeResources, access: BusinessAccess, change: dict, message: str
) -> None:
    values = dict(
        task_name="Task", phase="", start_date="2026-01-01", end_date="2026-01-02", progress_pct=0
    )
    values.update(change)
    service = create_planning_service(database, access=access)
    with pytest.raises(ValueError, match=message):
        service.create_milestone(1, **values)
    assert service.get_all_milestones() == []


def test_normalization_preserves_existing_dependency_defaults_and_progress_clamp(
    database: RuntimeResources, access: BusinessAccess,
) -> None:
    assert (
        normalize_task(
            dict(
                task_name=" Name ",
                start_date="2026-01-01",
                end_date="2026-01-01",
                phase=" ",
                progress_pct=500,
            )
        )["progress_pct"]
        == 100
    )
    assert normalize_dependency(1, {"predecessor_task_id": 1}) is None
    assert normalize_dependency(1, {}) is None
    assert normalize_dependency(1, {"predecessor_task_id": "bad"}) is None
    assert normalize_dependency(
        1, {"predecessor_project_id": 2, "link_type": "bad", "lag_days": "bad"}
    ) == {
        "predecessor_task_id": None,
        "predecessor_project_id": 2,
        "link_type": "FS",
        "lag_days": 0,
    }
    with pytest.raises(ValueError, match="project identity"):
        normalize_dependency(1, {"predecessor_project_id": "bad"})
    with pytest.raises(ValueError, match="selection"):
        normalize_dependency(1, [])
    service = create_planning_service(database, access=access)
    service.add_dependency(1, 1)
    service.add_dependency(1)
    assert not service.update_progress(999, -20)
    assert not service.update_dates(999, "2026-01-01", "2026-01-01")


def test_constraint_evaluation_terminates_for_cycles_and_incomplete_historical_dates() -> None:
    tasks = [
        {"id": 1, "task_name": "First", "start_date": "2026-01-01", "end_date": "2026-01-03"},
        {"id": 2, "task_name": "Second", "start_date": "2026-01-02", "end_date": "2026-01-04"},
        {"id": 3, "task_name": "Incomplete", "start_date": "", "end_date": "invalid"},
        {"task_name": "No identity"},
    ]
    dependencies = [
        {"task_id": 1, "predecessor_task_id": 2},
        {"task_id": 2, "predecessor_task_id": 1},
        {"task_id": 3, "predecessor_task_id": 1},
        {},
        {"task_id": 999},
        {"task_id": 1, "predecessor_task_id": 999},
        {"task_id": 1},
        {"task_id": 1, "predecessor_task_id": 2, "link_type": "unknown"},
    ]
    evaluated, warnings = evaluate_constraints(tasks, dependencies)
    assert len(evaluated) == 5
    assert len(warnings[1]) == len(warnings[2]) == 1
    assert warnings[3] == []
    assert all(not row["is_violated"] for row in evaluated[2:])
    assert "is_violated" not in dependencies[0]


@pytest.mark.parametrize(
    "content,message",
    [
        ("", "empty"),
        ("task_name,start_date,end_date\n", "empty"),
        ("task_name,start_date\nTask,2026-01-01\n", "Missing required columns"),
        ("task_name,start_date,end_date\n,2026-01-01,2026-01-02\n", "Row 2.*name"),
        ("task_name,start_date,end_date\nTask,,2026-01-02\n", "Row 2.*date"),
        ("task_name,start_date,end_date\nTask,2026-01-01,2026-01-02,extra\n", "Too many"),
        ('task_name,start_date,end_date\n"unterminated', "invalid CSV structure"),
    ],
)
def test_csv_parser_rejects_malformed_input_with_safe_row_errors(
    content: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_csv(content)


def test_csv_import_retains_optional_defaults_quotes_and_decimal_predecessor_ids() -> None:
    content = (
        "\ufefftask_name,phase,start_date,end_date,progress_pct,description,predecessor_id\n"
        '" Task, one ",,2026-01-01,2026-01-01,500,"Quoted, description",2.0\n'
        "Task two,,2026-01-02,2026-01-03,invalid,,invalid\n"
    )
    rows = parse_csv(content)
    assert rows[0] == {
        "task_name": "Task, one",
        "phase": "General",
        "start_date": "2026-01-01",
        "end_date": "2026-01-01",
        "progress_pct": 100,
        "description": "Quoted, description",
        "predecessor_id": 2,
    }
    assert rows[1]["progress_pct"] == 0
    assert rows[1]["predecessor_id"] is None
    assert len(parse_csv(get_csv_template())) == 3
    assert csv_text(io.BytesIO(content.encode("utf-8"))) == content.lstrip("\ufeff")
    assert csv_text(io.StringIO(content)) == content
    with pytest.raises(ValueError, match="No file"):
        csv_text(None)
    with pytest.raises(ValueError, match="UTF-8"):
        csv_text(io.BytesIO(b"\xff"))


def test_task_choice_search_is_bounded_literal_and_supports_exact_identity(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_planning_service(database, access=access)
    service.bulk_create_milestones(
        [
            dict(
                project_id=1,
                task_name=f"Task {number}",
                start_date="2026-01-01",
                end_date="2026-01-02",
            )
            for number in range(110)
        ]
    )
    assert len(service.search_task_choices()) == 50
    assert len(service.search_task_choices("Build", limit=1000)) == 100
    assert service.search_task_choices("#1") == [
        {"id": 1, "task_name": "Task 0", "project_id": 1, "project_name": "Build"},
    ]
    assert service.search_task_choices("%") == []
    assert len(service.search_task_choices("Task", limit=0)) == 1
    assert create_planning_service(database, access=access).search_task_choices("#1") == service.search_task_choices(
        "#1"
    )
