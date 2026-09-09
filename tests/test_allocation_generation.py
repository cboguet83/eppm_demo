"""Real snapshot, transaction, and capacity checks for allocation generation."""

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from app.application.exceptions import DatabaseMaintenanceError
from app.domain.resources.allocation_generation import (
    AllocationGenerationRequest, allocation_fte, allocation_rates, percentage_count,
)
from app.infrastructure.database.allocation_seed import _apply_plan
from app.infrastructure.database.pool_scenarios import fingerprint
from app.infrastructure.database.schema_init import init_db
from app.operator_services import create_maintenance_service, create_pool_capacity_service


@pytest.fixture
def allocation_database(tmp_path: Path) -> str:
    path = str(tmp_path / "allocations.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO project(id,name) VALUES(1,'Existing project')")
        connection.execute("INSERT INTO project_task(id,project_id,task_name,start_date,end_date) VALUES(1,1,'Task','2026-06-01','2026-06-05')")
        connection.execute("INSERT INTO employee(employee_id,firstname,lastname,email,employee_code) VALUES(1,'Test','Employee','test@example.invalid','E1')")
        connection.executemany("INSERT INTO resource_pool(id,name,capacity_fte) VALUES(?,?,4)", [(index, f"Pool {index}") for index in range(1, 11)])
        connection.executemany("INSERT INTO resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES(?,'employee',1,100)", [(index,) for index in range(1, 11)])
        connection.execute("INSERT INTO resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date) VALUES(1,1,0.5,'2026-06-01','2026-06-05')")
        connection.execute("INSERT INTO employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) VALUES(1,'2026-06-03','2026-06-03',0)")
    return path


def test_generation_dialog_previews_without_writing_then_applies_reviewed_mix(allocation_database: str) -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(f'''
from app.operator_services import create_maintenance_service
from app.presentation.components.allocation_seeding import _generate_allocations_dialog
_generate_allocations_dialog(create_maintenance_service({allocation_database!r}))
''', default_timeout=30).run()
    assert not app.exception and len(app.number_input) == 6
    app.number_input(key="seed_over_pct").set_value(25)
    app.number_input(key="seed_unstaffed_pct").set_value(20)
    app.button(key="preview_allocations").click().run()
    assert not app.exception and not app.error and app.dataframe
    with closing(sqlite3.connect(allocation_database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resource_pool_assignment").fetchone()[0] == 1
    app.button(key="apply_allocation_preview").click().run()
    assert not app.exception and not app.error
    assert app.session_state["seeding_status_message"].startswith("Pool allocations generated")
    assert len(create_pool_capacity_service(allocation_database).calculate_many(list(range(1, 11)))) == 10


def test_clear_dialog_waits_for_confirmation_and_cancel_keeps_allocations(allocation_database: str) -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(f'''
from app.operator_services import create_maintenance_service
from app.presentation.components.allocation_seeding import _clear_allocations_dialog
_clear_allocations_dialog(create_maintenance_service({allocation_database!r}))
''').run()
    app.button(key="cancel_clear_allocations").click().run()
    assert not app.exception
    with closing(sqlite3.connect(allocation_database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resource_pool_assignment").fetchone()[0] == 1
    app.button(key="confirm_clear_allocations").click().run()
    assert not app.exception
    with closing(sqlite3.connect(allocation_database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resource_pool_assignment").fetchone()[0] == 0


def test_fte_rounding_never_exceeds_target_or_changes_category() -> None:
    assert allocation_fte(1, 124.049) == 1.24
    assert allocation_fte(1, 100) == 1
    assert allocation_fte(1, 100.1) == 1.001
    for capacity, percentage in [(1, 0.01), (0.1, 100.1), (0.0001, 100), (1.0005, 100)]:
        with pytest.raises(ValueError, match="precision"):
            allocation_fte(capacity, percentage)


def request() -> AllocationGenerationRequest:
    return AllocationGenerationRequest(80, 80, 25, 50, 50, 20)


def test_generation_preserves_live_data_until_apply_and_meets_daily_capacity_mix(allocation_database: str) -> None:
    service = create_maintenance_service(allocation_database)
    with closing(sqlite3.connect(allocation_database)) as connection:
        before = fingerprint(connection)
    preview = service.generate_pool_allocations(request())
    assert not preview["applied"]
    with closing(sqlite3.connect(allocation_database)) as connection:
        assert fingerprint(connection) == before
    assert preview["allocated_pools"] == 8
    assert preview["overallocated_pools"] == 2
    assert preview["underallocated_pools"] == 4
    assert preview["fully_allocated_pools"] == 2
    assert preview["unstaffed_pools"] == 2
    assert preview["average_allocation_pct"] == pytest.approx(80, abs=0.1)
    assert not list(Path(allocation_database).parent.glob("data/backups/*.db"))

    result = service.generate_pool_allocations(request(), apply=True, expected_fingerprint=preview["fingerprint"])

    assert result["applied"] and result["rows"] == preview["rows"]
    assert len(list(Path(allocation_database).parent.glob("data/backups/*.db"))) == 1
    details = create_pool_capacity_service(allocation_database).calculate_many(list(range(1, 11)))
    assert sum(detail.is_overassigned for detail in details) == 2
    rows = {row["pool_id"]: row for row in result["rows"]}
    for detail in details:
        row = rows[detail.pool_id]
        assert detail.has_assigned_resources is not row["unstaffed"]
        for day, demand in detail.daily_usage.items():
            capacity = detail.daily_assigned_capacity.get(day, detail.effective_capacity_fte)
            assert capacity > 0
            assert 100 * demand / capacity == pytest.approx(row["allocation_pct"], abs=0.1)
            assert demand <= capacity * 1.5 + 0.0001
    with closing(sqlite3.connect(allocation_database)) as connection:
        assert connection.execute("SELECT name FROM project WHERE id=1").fetchone()[0] == "Existing project"
        assert connection.execute("SELECT start_date,end_date FROM project_task WHERE id=1").fetchone() == ("2026-06-01", "2026-06-05")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_stale_preview_and_invalid_mix_cannot_replace_allocations(allocation_database: str) -> None:
    service = create_maintenance_service(allocation_database)
    preview = service.generate_pool_allocations(request())
    with closing(sqlite3.connect(allocation_database)) as connection, connection:
        connection.execute("UPDATE project SET name='Concurrent edit' WHERE id=1")
    with pytest.raises(ValueError, match="Preview"):
        service.generate_pool_allocations(request(), apply=True, expected_fingerprint=preview["fingerprint"])
    with pytest.raises(ValueError, match="average between"):
        service.generate_pool_allocations(replace(request(), average_allocation_pct=20), apply=True)
    with closing(sqlite3.connect(allocation_database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resource_pool_assignment").fetchone()[0] == 1


def test_clear_allocations_preserves_membership_and_rolls_back_database_failures(allocation_database: str) -> None:
    service = create_maintenance_service(allocation_database)
    with closing(sqlite3.connect(allocation_database)) as connection, connection:
        connection.execute("CREATE TRIGGER reject_clear BEFORE DELETE ON resource_pool_assignment BEGIN SELECT RAISE(ABORT,'private detail'); END")
    with pytest.raises(DatabaseMaintenanceError, match="could not complete") as error:
        service.clear_pool_allocations()
    assert "private detail" not in str(error.value)
    with closing(sqlite3.connect(allocation_database)) as connection, connection:
        assert connection.execute("SELECT COUNT(*) FROM resource_pool_assignment").fetchone()[0] == 1
        connection.execute("DROP TRIGGER reject_clear")
    assert service.clear_pool_allocations() == 1
    assert service.clear_pool_allocations() == 0
    with closing(sqlite3.connect(allocation_database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resource_pool_mapping").fetchone()[0] == 10
        assert connection.execute("SELECT COUNT(*) FROM resource_pool").fetchone()[0] == 10


def test_plan_application_rolls_back_earlier_deletes_on_foreign_key_failure(allocation_database: str) -> None:
    with closing(sqlite3.connect(allocation_database)) as connection:
        original = fingerprint(connection)
    plan = [
        ("DELETE FROM resource_pool_assignment", ()),
        ("INSERT INTO resource_pool_assignment(pool_id,project_id,fte_assigned) VALUES(9999,1,1)", ()),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        _apply_plan(allocation_database, plan, original)
    with closing(sqlite3.connect(allocation_database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resource_pool_assignment").fetchone()[0] == 1


def test_generation_can_staff_empty_pools_and_supply_unstaffed_capacity(allocation_database: str) -> None:
    with closing(sqlite3.connect(allocation_database)) as connection, connection:
        connection.execute("DELETE FROM resource_pool_mapping")
        connection.execute("UPDATE resource_pool SET capacity_fte=NULL")
    report = create_maintenance_service(allocation_database).generate_pool_allocations(request(), apply=True)
    assert report["mappings_created"] == 8
    assert report["capacity_limits_initialized"] == 2
    assert all(row["capacity_fte"] > 0 for row in report["rows"])


@pytest.mark.parametrize("field,value", [
    ("allocated_pools_pct", -1), ("allocated_pools_pct", 101), ("average_allocation_pct", float("nan")),
    ("max_overallocation_pct", float("inf")), ("max_overallocation_pct", -1),
    ("overallocated_pools_pct", 99), ("underallocated_pools_pct", 101),
    ("unstaffed_pools_pct", True), ("average_allocation_pct", 1001), ("random_seed", 1.5),
])
def test_invalid_generation_inputs_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        allocation_rates(list(range(10)), replace(request(), **{field: value}))


def test_rounding_feasibility_and_empty_allocation_requests() -> None:
    assert percentage_count(3, 50) == 2
    assert allocation_rates([1, 2], replace(request(), allocated_pools_pct=0)) == {}
    assert allocation_rates([], request()) == {}
    all_full = AllocationGenerationRequest(100, 100, 0, 0, 0, 0)
    assert allocation_rates([1, 2, 3], all_full) == {1: 100, 3: 100, 2: 100}
    with pytest.raises(ValueError, match="0.1%"):
        allocation_rates([1, 2, 3], replace(request(), max_overallocation_pct=0))
    mixed = AllocationGenerationRequest(100, 90, 50, 50, 50, 0)
    rates = allocation_rates([1, 2, 3], mixed)
    assert len(rates) == 3 and sum(rates.values()) / 3 == pytest.approx(90)
