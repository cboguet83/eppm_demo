"""Real transaction regressions for schedule replacement and project link drafts."""

import csv
from datetime import date
import io
from unittest.mock import patch

import psycopg
from psycopg import sql
import pytest

from app.application.exceptions import PlanningConflictError
from app.application.services.business_access import BusinessAccess
from app.domain.planning.schedule_template import export_template, parse_template
from app.domain.resources.models import PoolAssignment, ResourcePool, ResourcePoolGroup
from app.main import create_planning_service, create_project_service, create_resource_pool_service
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import native_screen, runtime as runtime, access as access


HEADER = "step_number,task_name,start_date,end_date,progress_pct,preceding_step,dependency_type,dependency_lag\n"
VALID = HEADER + "1,New first,2026-01-01,2026-01-02,0,,,\n2,New second,2026-01-03,2026-01-04,50,1,FS,0\n"


@pytest.fixture
def database(runtime: RuntimeResources, access: BusinessAccess) -> RuntimeResources:
    """Create a connected four-project schedule through native business services."""
    projects = create_project_service(runtime, access=access)
    for identity, name in enumerate(("Selected", "Predecessor", "Successor"), 1):
        projects.update_project(identity, name, "Draft", 0, 0, {})
    assert projects.create_project(name="Unrelated") == 4
    planning = create_planning_service(runtime, access=access)
    for project in range(1, 5):
        planning.create_milestone(project, f"Task {project}", "Build", "2026-01-01", "2026-01-04", 0)
    planning.add_dependency(1, predecessor_task_id=2)
    planning.add_dependency(3, predecessor_task_id=1)
    resources = create_resource_pool_service(runtime, access=access)
    pool = resources.create_pool(ResourcePool("Pool", capacity_fte=2))
    resources.create_assignment(PoolAssignment(pool, 1, .5))
    resources.create_assignment(PoolAssignment(pool, 1, .5, task_id=1))
    return runtime


def snapshot(authorized: AuthorizedFixture) -> dict[str, list[tuple]]:
    """Read all authoritative schedule, allocation and link rows as the test operator."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        return {
            table: connection.execute(
                sql.SQL("SELECT * FROM eppm.{} ORDER BY id").format(sql.Identifier(table))
            ).fetchall()
            for table in ("project_task", "task_dependencies", "resource_pool_assignment", "project_link")
        }


@pytest.mark.parametrize("content,problem", [
    ("", "Missing required"), (HEADER, "no tasks"),
    (VALID.replace("New second", ""), "Row 3"),
    (VALID.replace("2026-01-03", "2026-02-03"), "Row 3"),
    (VALID.replace(",50,", ",150,"), "Progress"),
    (VALID.replace("2,New", "1,New"), "unique"),
    (VALID.replace("1,FS,0", "9,FS,0"), "Unknown predecessor"),
    (VALID.replace("1,FS,0", "2,FS,0"), "self-link"),
    (VALID.replace("1,FS,0", "task:999,FS,0"), "External task"),
    (VALID.replace("1,FS,0", "task:1,FS,0"), "use a step reference"),
    (VALID.replace("1,FS,0", "project:1,FS,0"), "refers to this project"),
    (VALID.replace("1,FS,0", "project:999,FS,0"), "missing"),
    (VALID.replace("1,FS,0", "1,XX,0"), "Dependency type"),
    (VALID.replace("1,FS,0", "1,FS,bad"), "lag"),
    (VALID.replace("1,FS,0", "bad,FS,0"), "positive integer"),
    (VALID.replace("1,FS,0", "1;1,FS;FS,0;0"), "Duplicate dependency"),
    (VALID.replace("step_number,", "step_number,step_number,"), "Duplicate or unsupported columns"),
    (VALID.replace("step_number,", "step_number,unexpected,"), "Duplicate or unsupported columns"),
    (VALID.replace("1,New first,", "1,New,first,"), "Row 2: Column count"),
    (VALID.replace("1,New first,", "1,"), "Row 2: Column count"),
    (HEADER + '1,"Unclosed task,2026-01-01,2026-01-02,0,,,', "Invalid CSV quoting"),
    (VALID.replace("1,New first,", "0,New first,"), "Row 2: Step number must be a positive 64-bit integer"),
    (VALID.replace("1,New first,", "9223372036854775808,New first,"), "positive 64-bit integer"),
    (VALID.replace("1,FS,0", "step:1:extra,FS,0"), "Preceding step must"),
    (VALID.replace("1,FS,0", "sql:1,FS,0"), "Preceding step must"),
    (VALID.replace("1,FS,0", "task:0,FS,0"), "Dependency reference must be a positive 64-bit integer"),
    (VALID.replace("1,FS,0", "1,FS,9223372036854775808"), "lag is outside"),
    (VALID.replace("1,FS,0", "1,FS,-9223372036854775809"), "lag is outside"),
])
def test_invalid_replacement_preserves_tasks_links_and_allocations(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture, content: str, problem: str) -> None:
    before = snapshot(authorized)
    with pytest.raises(ValueError, match=problem):
        create_planning_service(database, access=access).replace_project_template(1, content)
    assert snapshot(authorized) == before


@pytest.mark.parametrize("predecessor,kind,identity", [(10, "step", 1), (99, "task", 99)])
def test_legacy_predecessor_exports_preserve_local_and_external_dependency_references(predecessor, kind, identity):
    tasks = [
        {"id": 10, "task_name": "First", "start_date": "2026-01-01", "end_date": "2026-01-02"},
        {"id": 20, "task_name": "Second", "start_date": "2026-01-03", "end_date": "2026-01-04", "predecessor_id": predecessor},
    ]
    content = export_template(tasks, [])
    steps = parse_template(content)
    assert len(steps[1].dependencies) == 1
    dependency = steps[1].dependencies[0]
    assert (dependency.kind, dependency.identity, dependency.link_type, dependency.lag_days) == (kind, identity, "FS", 0)
    modern = export_template(tasks, [{"task_id": 20, "predecessor_project_id": 3, "link_type": "SS", "lag_days": -2}])
    dependency, = parse_template(modern)[1].dependencies
    assert (dependency.kind, dependency.identity, dependency.link_type, dependency.lag_days) == ("project", 3, "SS", -2)


def test_replacement_clears_old_schedule_and_allocations_but_preserves_project_links(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    projects = create_project_service(database, access=access)
    project = projects.get_project_by_id(1)
    projects.update_project(1, project.name, project.status, 0, 0, {}, custom_links=[{"url":"https://example.test", "alias":"Useful"}])
    service = create_planning_service(database, access=access)
    assert service.replace_project_template(1, VALID) == 2
    tasks = service.get_milestones_by_project(1)
    assert [task["task_name"] for task in tasks] == ["New first", "New second"]
    assert service.get_task_dependencies(tasks[1]["id"])[0]["predecessor_task_id"] == tasks[0]["id"]
    assert service.get_task_dependencies(3) == []
    assert len(service.get_milestones_by_project(2)) == 1
    assert create_resource_pool_service(database, access=access).get_assignments(project_id=1) == []
    assert projects.get_links(1) == [{"url":"https://example.test", "alias":"Useful"}]
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM eppm.resource_pool_assignment WHERE project_id=1"
        ).fetchone()[0] == 0


def test_storage_failure_rolls_back_deletion_and_partial_replacement(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_test_replacement() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                IF NEW.task_name='New second' THEN
                    RAISE EXCEPTION 'rejected' USING ERRCODE='23514';
                END IF;
                RETURN NEW;
            END $$""")
        connection.execute("""CREATE TRIGGER reject_replacement BEFORE INSERT
            ON eppm.project_task FOR EACH ROW EXECUTE FUNCTION eppm.reject_test_replacement()""")
    before = snapshot(authorized)
    with pytest.raises(PlanningConflictError):
        create_planning_service(database, access=access).replace_project_template(1, VALID)
    assert snapshot(authorized) == before


def test_export_round_trips_multiline_text_multiple_link_types_and_lags(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    service = create_planning_service(database, access=access)
    task = service.create_milestone(1, 'Quoted, "task"', "Design", "2026-02-01", "2026-02-03", 42,
        description="First line\nSecond line", dependencies=[
            {"predecessor_task_id":1, "link_type":"SS", "lag_days":-2},
            {"predecessor_project_id":4, "link_type":"FF", "lag_days":3},
        ])
    content = service.export_project_template(1)
    steps = parse_template(content)
    assert steps[1].values["description"] == "First line\nSecond line"
    assert {dep.kind for step in steps for dep in step.dependencies} == {"step", "task", "project"}
    service.replace_project_template(1, content)
    assert service.export_project_template(1) == content
    assert service.get_milestone_by_id(task) is None


@pytest.mark.parametrize("date_format,pattern", [("DD/MM/YYYY", "%d/%m/%Y"), ("MM/DD/YYYY", "%m/%d/%Y")])
def test_spreadsheet_reformatted_export_preserves_dates_on_reimport(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture, date_format: str, pattern: str) -> None:
    service = create_planning_service(database, access=access)
    exported = service.export_project_template(1)
    rows = list(csv.DictReader(io.StringIO(exported)))
    # Simulate a spreadsheet changing the start-date cell while retaining ISO end dates.
    rows[0]["start_date"] = date.fromisoformat(rows[0]["start_date"]).strftime(pattern)
    rows[0]["task_name"] = "Edited in spreadsheet"
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    edited = output.getvalue()
    before = snapshot(authorized)
    with pytest.raises(ValueError, match="Row 2: Invalid start_date"):
        service.replace_project_template(1, edited)
    assert snapshot(authorized) == before
    preview = service.validate_project_template(1, edited, date_format=date_format)
    assert preview[0].values["start_date"] == "2026-01-01"
    service.replace_project_template(1, edited, date_format=date_format)
    assert service.export_project_template(1) == exported.replace("Task 1", "Edited in spreadsheet")


def test_ambiguous_dates_follow_selected_format_and_invalid_dates_preserve_schedule(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    content = VALID.replace("2026-01-01", "02/01/2026").replace("2026-01-02", "03/02/2026")
    # Use one task so later task chronology does not obscure the date-order check.
    content = "\n".join(content.splitlines()[:2]) + "\n"
    assert parse_template(content, date_format="DD/MM/YYYY")[0].values["start_date"] == "2026-01-02"
    assert parse_template(content, date_format="MM/DD/YYYY")[0].values["start_date"] == "2026-02-01"
    service = create_planning_service(database, access=access)
    before = snapshot(authorized)
    for bad in ("31/02/2026", "", "01/02/26"):
        with pytest.raises(ValueError, match="Row 2: Invalid start_date"):
            service.replace_project_template(1, content.replace("02/01/2026", bad), date_format="DD/MM/YYYY")
        assert snapshot(authorized) == before
    with pytest.raises(ValueError, match="Unsupported CSV date format"):
        parse_template(content, date_format="guess")


def test_import_defaults_to_day_first_and_previews_normalized_dates(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    content = VALID.replace("2026-01-01", "01/01/2026").encode()
    with patch("app.presentation.components.csv_upload.project_csv_upload", return_value=content.decode()):
        app = native_screen(f'''
from app.main import create_planning_workspace
from app.presentation.pages.planning import _schedule_csv_dialog
_schedule_csv_dialog(create_planning_workspace(runtime, access=access), 1, "import_csv_template")
''', database, access).run()
        assert app.selectbox(key="template_date_format_1").value == "DD/MM/YYYY"
        assert not app.exception
        assert not app.error
        assert app.dataframe[0].value.iloc[0]["start_date"] == "2026-01-01"
        app.selectbox(key="template_date_format_1").select("YYYY-MM-DD").run()
        assert "Invalid start_date" in app.error[0].value


def test_project_filter_uses_transitive_dependencies_and_terminates_on_cycles(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    service = create_planning_service(database, access=access)
    assert service.related_project_ids(1, "this") == [1]
    assert service.related_project_ids(1, "predecessors") == [1, 2]
    assert service.related_project_ids(1, "all") == [1, 2, 3]
    service.add_dependency(2, predecessor_task_id=3)
    assert service.related_project_ids(1, "predecessors") == [1, 2, 3]
    with pytest.raises(ValueError, match="Unknown"):
        service.related_project_ids(1, "invalid")


def test_project_creation_and_update_save_custom_links_atomically(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    service = create_project_service(database, access=access)
    project = service.create_project(name="With links", custom_links=[{"url":"https://example.test", "alias":"Docs"}])
    assert service.get_links(project)[0]["alias"] == "Docs"
    with pytest.raises(ValueError):
        service.update_project(project, "Must not change", "Draft", 0, 0, {}, custom_links=[{"url":"bad", "alias":"Bad"}])
    assert service.get_project_by_id(project).name == "With links"
    assert service.get_links(project)[0]["alias"] == "Docs"
    service.update_project(project, "Edited", "Draft", 0, 0, {}, custom_links=[{"url":"https://example.test/new", "alias":"New"}])
    assert service.get_links(project)[0]["alias"] == "New"
    with pytest.raises(ValueError):
        service.create_project(name="Must not exist", custom_links=[{"url":"bad", "alias":"Bad"}])
    assert len(service.get_planning_catalog()) == 5


def test_project_view_starts_read_only_and_explicit_button_enables_editing(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    app = native_screen(f'''
from app.main import create_project_workspace
from app.presentation.components.project_dialogs import open_edit_project_dialog
open_edit_project_dialog(1, create_project_workspace(runtime, access=access), read_only=True)
''', database, access).run()
    assert not app.exception
    assert all(widget.disabled for widget in app.text_input)
    assert app.text_input(key="portfolio_edit_1_planned").disabled
    assert app.text_input(key="portfolio_edit_1_actual").disabled
    next(button for button in app.button if button.label == "Edit project").click().run()
    assert not app.exception
    assert any(not widget.disabled for widget in app.text_input)
    assert not app.text_input(key="portfolio_edit_1_planned").disabled
    assert not app.text_input(key="portfolio_edit_1_actual").disabled
    assert len(app.dataframe) == 1


def test_group_popup_includes_allocations_from_descendants(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    resources = create_resource_pool_service(database, access=access)
    group = resources.create_pool_group(ResourcePoolGroup(name="Group"), pool_ids=[1])
    with patch("app.presentation.components.action_table.action_table", return_value=None) as table:
        app = native_screen(f'''
from app.main import create_planning_workspace
from app.presentation.pages.planning import _pool_allocations_dialog
_pool_allocations_dialog(0, create_planning_workspace(runtime, access=access), group_id={group})
''', database, access).run()
    assert not app.exception and not app.error
    assert len(table.call_args.args[0]) == 2
    assert table.call_args.args[2] == {"open":"Go to"}


def test_import_dialog_explains_invalid_upload_without_changing_data(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    before = snapshot(authorized)
    invalid = VALID.replace("1,FS,0", "999,FS,0").encode()
    with patch("app.presentation.components.csv_upload.project_csv_upload", return_value=invalid.decode()):
        app = native_screen(f'''
from app.main import create_planning_workspace
from app.presentation.pages.planning import _schedule_csv_dialog
_schedule_csv_dialog(create_planning_workspace(runtime, access=access), 1, "import_csv_template")
''', database, access).run()
    assert not app.exception
    assert "Unknown predecessor" in app.error[0].value
    assert "Nothing is deleted" in app.warning[0].value
    assert not any(button.label == "Replace project schedule" for button in app.button)
    assert snapshot(authorized) == before


def test_template_preserves_existing_multi_task_cycle_warning_behavior(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    content = VALID.replace("2026-01-02,0,,,", "2026-01-02,0,2,FS,0")
    service = create_planning_service(database, access=access)
    assert service.replace_project_template(1, content) == 2
    assert len(service.get_dependencies_for_project(1)) == 2


def test_split_dependency_columns_round_trip_and_reject_mismatched_lists(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    service = create_planning_service(database, access=access)
    content = VALID.replace("1,FS,0", "1;task:2,FS;SS,0;-2")
    service.replace_project_template(1, content)
    exported = service.export_project_template(1)
    rows = list(csv.DictReader(io.StringIO(exported)))
    assert rows[1]["preceding_step"] == "1;task:2"
    assert rows[1]["dependency_type"] == "FS;SS"
    assert rows[1]["dependency_lag"] == "0;-2"
    assert "dependencies" not in rows[1]
    before = snapshot(authorized)
    for invalid in (content.replace("FS;SS", "FS"), content.replace("0;-2", "0;")):
        with pytest.raises(ValueError, match="same number"):
            service.replace_project_template(1, invalid)
        assert snapshot(authorized) == before


def test_clear_all_filters_resets_selection_and_resource_filter_state(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as chart:
        app = native_screen(f'''
import streamlit as st
from app.main import create_planning_workspace
from app.presentation.pages.planning import render_planning_milestones
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.ms_multi_projects = [1]
    st.session_state.ms_planning_tag_filter = ["Stale tag"]
render_planning_milestones(create_planning_workspace(runtime, access=access))
''', database, access).run()
        assert not app.exception
        assert not any(widget.key == "ms_planning_tag_filter" for widget in app.multiselect)
        next(button for button in app.button if button.label == "Clear all filters").click().run()
        assert not app.exception
        assert app.session_state["ms_multi_projects"] == []
        assert app.session_state["ms_planning_tag_filter"] == []
        assert chart.call_args.kwargs["filter_reset"] == 1
    assert create_planning_service(database, access=access).related_project_ids([1, 4], "all") == [1, 2, 3, 4]
