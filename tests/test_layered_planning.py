"""Task use-case integrity, scheduling rules, and real SQLite transaction behavior."""

from contextlib import closing
import io
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from app.application.exceptions import PlanningConflictError, PlanningStorageError
from app.domain.planning.constraints import evaluate_constraints
from app.domain.planning.csv_import import get_csv_template, parse_csv
from app.domain.planning.models import LinkType
from app.domain.planning.rules import normalize_dependency, normalize_task
from app.infrastructure.database.connection import get_db
from app.infrastructure.repositories.planning import SqlitePlanningGateway
from app.main import create_planning_service
from app.presentation.components.planning_imports import csv_text
from src.database.schema_init import init_db
from src.repositories.milestone_repo import MilestoneRepository


@pytest.fixture
def database(tmp_path: Path) -> str:
    path = str(tmp_path / "planning.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executemany(
            "INSERT INTO project(id,name) VALUES(?,?)", [(1, "Build"), (2, "Deploy")]
        )
    return path


def test_task_creation_and_dependency_edit_roll_back_together(database: str) -> None:
    service = create_planning_service(database)
    with pytest.raises(PlanningConflictError) as failure:
        service.create_milestone(
            1,
            "Failed",
            "",
            "2026-01-01",
            "2026-01-02",
            0,
            dependencies=[{"predecessor_task_id": 999}],
        )
    assert isinstance(failure.value.__cause__, sqlite3.IntegrityError)
    assert service.get_all_milestones() == []
    predecessor = service.create_milestone(1, "First", "", "2026-01-01", "2026-01-01", 0)
    successor = service.create_milestone(
        2, "Original", "", "2026-01-02", "2026-01-03", 0, predecessor_id=predecessor
    )
    original = service.get_milestone_by_id(successor)
    links = service.get_task_dependencies(successor)
    with pytest.raises(PlanningConflictError):
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
    database: str,
) -> None:
    service = create_planning_service(database)
    header = "task_name,start_date,end_date\n"
    valid = "Good,2026-01-01,2026-01-02\n"
    with pytest.raises(ValueError, match="Row 3"):
        service.import_csv(1, header + valid + "Bad,2026-02-01,2026-01-01\n")
    assert service.get_all_milestones() == []
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""CREATE TRIGGER reject_bad_task BEFORE INSERT ON project_task
            WHEN NEW.task_name='Rejected' BEGIN SELECT RAISE(ABORT,'internal details'); END""")
    with pytest.raises(PlanningConflictError, match="constraint"):
        service.import_csv(1, header + valid + "Rejected,2026-01-01,2026-01-01\n")
    assert service.get_all_milestones() == []
    assert service.bulk_create_milestones([]) == 0
    assert service.import_csv(1, header + valid) == 1


def test_deletion_rollback_restores_links_and_legacy_predecessor_columns(database: str) -> None:
    service = create_planning_service(database)
    first = service.create_milestone(1, "First", "", "2026-01-01", "2026-01-02", 0)
    second = service.create_milestone(
        1, "Second", "", "2026-01-03", "2026-01-04", 0, predecessor_id=first
    )
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(f"""CREATE TRIGGER reject_task_delete BEFORE DELETE ON project_task
            WHEN OLD.id={first} BEGIN SELECT RAISE(ABORT,'internal details'); END""")
    with pytest.raises(PlanningConflictError):
        service.delete_milestone(first)
    assert service.get_task_dependencies(second)[0]["predecessor_task_id"] == first
    assert service.get_milestone_by_id(second)["predecessor_id"] == first
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("DROP TRIGGER reject_task_delete")
    assert service.delete_milestone(first)
    assert service.get_task_dependencies(second) == []
    assert service.get_milestone_by_id(second)["predecessor_id"] is None
    assert not service.delete_milestone(first)


def test_planning_gateway_reserves_writes_and_hides_storage_details(database: str) -> None:
    held = get_db(database)
    with patch("app.infrastructure.repositories.planning.get_db", return_value=held):
        with SqlitePlanningGateway(database).transaction(write=True) as store:
            assert store.connection.in_transaction
            with closing(sqlite3.connect(database, timeout=0)) as competitor:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    competitor.execute("BEGIN IMMEDIATE")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        held.execute("SELECT 1")
    with patch(
        "app.infrastructure.repositories.planning.get_db",
        side_effect=sqlite3.OperationalError("internal database path"),
    ):
        with pytest.raises(PlanningStorageError) as failure:
            create_planning_service(database).get_all_milestones()
    assert "internal" not in str(failure.value)
    assert isinstance(failure.value.__cause__, sqlite3.OperationalError)
    with pytest.raises(sqlite3.IntegrityError):
        MilestoneRepository(database).create_milestone(
            999, "Unknown project", "", "2026-01-01", "2026-01-01", 0
        )


def test_batched_tasks_and_dependencies_share_a_stable_read_snapshot(database: str) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    service = create_planning_service(database)
    first = service.create_milestone(1, "First", "", "2026-01-01", "2026-01-02", 0)
    second = service.create_milestone(2, "Second", "", "2026-01-03", "2026-01-04", 0)
    with SqlitePlanningGateway(database).transaction() as store:
        assert len(store.get_milestones_for_projects([1, 2])) == 2
        service.add_dependency(second, first)
        assert store.get_dependencies_for_projects([1, 2]) == []
    assert len(service.get_dependencies_for_projects([1, 2])) == 1
    assert service.get_milestones_for_projects([]) == []
    assert service.get_dependencies_for_projects([]) == []
    assert service.get_project_date_bounds(999) == (None, None)
    assert service.get_all_project_date_bounds()[1] == ("2026-01-01", "2026-01-02")


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
    database: str, change: dict, message: str
) -> None:
    values = dict(
        task_name="Task", phase="", start_date="2026-01-01", end_date="2026-01-02", progress_pct=0
    )
    values.update(change)
    service = create_planning_service(database)
    with pytest.raises(ValueError, match=message):
        service.create_milestone(1, **values)
    assert service.get_all_milestones() == []


def test_normalization_preserves_existing_dependency_defaults_and_progress_clamp(
    database: str,
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
    service = create_planning_service(database)
    service.add_dependency(1, 1)
    service.add_dependency(1)
    assert not service.update_progress(999, -20)
    assert not service.update_dates(999, "2026-01-01", "2026-01-01")
    assert LinkType.get_display_name("FS") == "Finish-to-Start (FS)"
    assert LinkType.get_display_name("new") == "new"


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


def test_task_choice_search_is_bounded_literal_and_supports_exact_identity(database: str) -> None:
    service = create_planning_service(database)
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
    assert MilestoneRepository(database).search_task_choices("#1") == service.search_task_choices(
        "#1"
    )
