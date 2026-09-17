"""Real pool dialogs and Settings routing through the migrated services."""

from unittest.mock import patch

import psycopg
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.domain.organization.models import Employee, Team
from app.domain.resources.models import PoolAssignment, PoolMapping, ResourcePool
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied
from app.main import create_organization_service, create_resource_pool_service
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.runtime import RuntimeResources
from tests.postgresql.ui import native_screen


@pytest.fixture
def database(authorized) -> RuntimeResources:
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
        connection.execute("INSERT INTO eppm.tag_group(id,tag_group_name) VALUES(1,'pool_tag'),(2,'project_tag')")
        connection.execute("INSERT INTO eppm.tag_dictionnary(id,tag,tag_group_id) VALUES(1,'Priority',1),(2,'Project only',2),(3,'Unclassified',NULL)")
        connection.execute("UPDATE eppm.project SET name='<script>project</script>',status='In Progress' WHERE id=1")
    return RuntimeResources(authorized.database, authorized.key)


@pytest.fixture
def access(authorized) -> BusinessAccess:
    return authorized.binding(4).access


def dialog(resources: RuntimeResources, access: BusinessAccess, invocation: str) -> AppTest:
    """Keep the production modal open across AppTest's full-script reruns."""
    app = native_screen(
        f"""
from app.main import create_resource_pool_service, create_organization_service
from app.presentation.components import resource_pool_dialogs as dialogs
from app.presentation.components.organization_frames import teams_frame, employees_frame
from app.presentation.i18n import set_current_locale
set_current_locale('en')
service = create_resource_pool_service(runtime, access=access)
org = create_organization_service(runtime, access=access)
teams = teams_frame(org.get_all_teams())
employees = employees_frame(org.get_all_employees())
dialogs.{invocation}
""",
        resources, access,
    ).run()
    assert not app.exception, [item.message for item in app.exception]
    return app


def test_pool_dialogs_create_edit_and_delete_with_tags(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    app = dialog(database, access, "_open_add_pool_dialog(service)")
    assert app.multiselect[0].options == ['Priority']
    app.button[0].click().run()
    assert app.error and service.get_all_pools() == []
    app.text_input[0].input("Delivery")
    app.number_input[0].set_value(2.5)
    app.multiselect[0].set_value([1])
    app.button[0].click().run()
    assert not app.exception
    pool = service.get_all_pools()[0]
    assert pool.capacity_fte == 2.5
    assert service.get_pool_tags(pool.id)[0].tag_name == "Priority"
    app = dialog(database, access, f"_open_edit_pool_dialog(service, {pool.id})")
    assert app.multiselect[0].options == ['Priority']
    next(widget for widget in app.text_input if widget.label == 'Resource Pool Name *').input('Renamed')
    app.multiselect[0].set_value([])
    next(widget for widget in app.button if widget.label == 'Save Changes').click().run()
    assert not app.exception
    assert service.get_pool_by_id(pool.id).name == "Renamed"
    assert service.get_pool_tags(pool.id) == []
    app = dialog(database, access, f"_open_delete_pool_dialog(service, {pool.id}, 'Renamed')")
    app.button[0].click().run()
    assert not app.exception and service.get_all_pools() == []


def test_failed_tag_write_rolls_back_pool_and_displays_safe_error(database: RuntimeResources, access: BusinessAccess, authorized) -> None:
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_pool_tag() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private database detail' USING ERRCODE='23514'; END $$""")
        connection.execute("""CREATE TRIGGER reject_pool_tag BEFORE INSERT ON eppm.resource_pool_tag
            FOR EACH ROW EXECUTE FUNCTION eppm.reject_pool_tag()""")
    app = dialog(database, access, "_open_add_pool_dialog(service)")
    app.text_input[0].input("Failed")
    app.multiselect[0].set_value([1])
    app.button[0].click().run()
    assert not app.exception and app.error
    assert "private database detail" not in app.error[0].value
    assert create_resource_pool_service(database, access=access).get_all_pools() == []


def test_parent_selector_creates_children_excludes_descendants_and_warns_on_assignment(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    parent = service.create_pool(ResourcePool('Parent'))
    app = dialog(database, access, f"_open_add_pool_dialog(service, {parent})")
    app.text_input[0].input('Child')
    app.button[0].click().run()
    assert not app.exception and not app.error
    child = next(pool for pool in service.get_all_pools() if pool.name == 'Child')
    assert child.parent_pool_id == parent
    app = dialog(database, access, f"_open_edit_pool_dialog(service, {parent})")
    assert app.selectbox(key=f'parent_pool_{parent}').options == ['No parent (root pool)']
    assert next(widget for widget in app.number_input if 'capacity' in widget.label.lower()).disabled
    service.create_assignment(PoolAssignment(child.id, 1, 1))
    app = dialog(database, access, f"_open_add_pool_dialog(service, {child.id})")
    assert any('project or task assignments' in warning.value for warning in app.warning)
    app.text_input[0].input('Blocked')
    app.button[0].click().run()
    assert not app.exception and any('Cannot add a child' in error.value for error in app.error)
    assert len(service.get_all_pools()) == 2


def test_new_pool_dialog_saves_initial_exception_and_hides_legacy_nonpool_tags(database, access):
    service = create_resource_pool_service(database, access=access)
    app = dialog(database, access, '_open_add_pool_dialog(service)')
    app.text_input[0].input('Initial exception')
    app.checkbox(key='new_pool_add_exception').check().run()
    app.text_input(key='new_pool_exception_reason').input('Training')
    next(button for button in app.button if button.label == 'Save').click().run()
    assert not app.exception and not app.error
    pool = next(row for row in service.get_all_pools() if row.name == 'Initial exception')
    assert service.capacity_exceptions(pool.id)[0].reason == 'Training'
    service.set_pool_tags(pool.id, [1, 2, 3])
    app = dialog(database, access, f'_open_edit_pool_dialog(service, {pool.id})')
    assert not app.exception
    assert app.multiselect[0].options == ['Priority']
    assert app.multiselect[0].value == [1]
    assert service.get_tags_by_pools([pool.id]) == {pool.id: ['Priority']}
    next(button for button in app.button if button.label == 'Save Changes').click().run()
    assert not app.exception and not app.error
    assert {tag.tag_id for tag in service.get_pool_tags(pool.id)} == {1, 2, 3}


def test_mapping_dialog_preserves_team_and_employee_choices(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool("Delivery"))
    org = create_organization_service(database, access=access)
    team = org.create_team(Team("Team"))
    second_team = org.create_team(Team("Second team"))
    employee = org.create_employee(Employee("Ada", "Lovelace", "ada@example.invalid", "ADA"))
    second_employee = org.create_employee(Employee("Grace", "Hopper", "grace@example.invalid", "GRACE"))
    app = dialog(database, access, f"_open_add_pool_mapping_dialog(service, {pool}, teams, employees)")
    app.multiselect(key=f'mapping_teams_{pool}').set_value([team, second_team]).run()
    app.multiselect(key=f'mapping_employees_{pool}').set_value([employee, second_employee]).run()
    assert all(widget.value == 100 for widget in app.number_input)
    app.number_input(key=f'mapping_pct_{pool}_team_{team}').set_value(50)
    app.number_input(key=f'mapping_pct_{pool}_employee_{employee}').set_value(25)
    next(button for button in app.button if button.label == 'Save mappings').click().run()
    assert not app.exception
    before = {(row.target_type, row.target_id): row for row in service.get_mappings_by_pool(pool)}
    assert len(before) == 4
    assert before['team', team].allocation_pct == 50 and before['employee', employee].allocation_pct == 25
    app.button(key=f'remove_mapping_{pool}_team_{team}').click().run()
    app.button(key=f'remove_mapping_{pool}_team_{second_team}').click().run()
    app.button(key=f'remove_mapping_{pool}_employee_{second_employee}').click().run()
    assert app.multiselect(key=f'mapping_teams_{pool}').value == []
    assert app.multiselect(key=f'mapping_employees_{pool}').value == [employee]
    assert len(service.get_mappings_by_pool(pool)) == 4
    app.number_input(key=f'mapping_pct_{pool}_employee_{employee}').set_value(75)
    next(button for button in app.button if button.label == 'Save mappings').click().run()
    assert not app.exception
    after = service.get_mappings_by_pool(pool)
    assert len(after) == 1 and after[0].id == before['employee', employee].id and after[0].allocation_pct == 75
    app.button(key=f'remove_mapping_{pool}_employee_{employee}').click().run()
    next(button for button in app.button if button.label == 'Save mappings').click().run()
    assert not app.exception and service.get_mappings_by_pool(pool) == []


def test_mapping_batch_rolls_back_removals_when_insertion_fails(database, access, authorized):
    service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool('Delivery'))
    org = create_organization_service(database, access=access)
    team = org.create_team(Team('Original team'))
    employee = org.create_employee(Employee('Ada', 'Lovelace', 'batch@example.invalid', 'BATCH'))
    original = service.create_mapping(PoolMapping(pool, 'team', team, 50))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('REVOKE INSERT ON eppm.resource_pool_mapping FROM eppm_runtime')
    try:
        with pytest.raises(AccessDenied):
            service.save_mappings(pool, [PoolMapping(pool, 'employee', employee, 25)])
    finally:
        with psycopg.connect(authorized.setup.operator_url) as connection:
            connection.execute('GRANT INSERT ON eppm.resource_pool_mapping TO eppm_runtime')
    remaining = service.get_mappings_by_pool(pool)
    assert len(remaining) == 1
    assert remaining[0].id == original and remaining[0].allocation_pct == 50


def test_concurrent_delete_and_read_failures_do_not_report_success(database: RuntimeResources, access: BusinessAccess, authorized) -> None:
    service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool("Delivery"))
    app = dialog(database, access, f"_open_delete_pool_dialog(service, {pool}, 'Delivery')")
    service.delete_pool(pool)
    app.button[0].click().run()
    assert not app.exception and app.error and not app.toast
    assert "no longer exists" in app.error[0].value
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('REVOKE SELECT ON eppm.tag_dictionnary FROM eppm_runtime')
    try:
        app = dialog(database, access, "_open_add_pool_dialog(service)")
        assert app.error and 'tag_dictionnary' not in app.error[0].value
        assert authorized.setup.runtime_url not in app.error[0].value
    finally:
        with psycopg.connect(authorized.setup.operator_url) as connection:
            connection.execute('GRANT SELECT ON eppm.tag_dictionnary TO eppm_runtime')


def test_settings_pool_route_supplies_safe_row_data_and_individual_actions(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool("Delivery", capacity_fte=2))
    assignment = service.create_assignment(
        PoolAssignment(pool, 1, 1, notes="<img src=x onerror=alert(1)>")
    )
    app = native_screen(
        f"""
from app.main import create_organization_service
from app.presentation.pages.settings import render_settings_view
from app.main import create_settings_workspace
render_settings_view(create_settings_workspace(runtime, access=access))
""",
        database, access,
    )
    app.session_state["settings_active_tab"] = "resource_pools"
    with patch("app.presentation.components.action_table.action_table", return_value=None) as table:
        app.run()
    assert not app.exception and len(app.metric) == 3
    rows, columns, actions = table.call_args.args
    assert rows[0]["project"] == "<script>project</script>"
    assert rows[0]["notes"] == "<img src=x onerror=alert(1)>"
    assert rows[0]["id"] == assignment
    assert actions == {"open": "Go to", "unassign": "Unassign"}
    assert not any(button.key == f"btn_unassign_{pool}" for button in app.button)
    assert service.get_assignment_by_id(assignment)
    app = dialog(database, access, f"_confirm_unassign(service, {pool}, {assignment}, 'Project')")
    app.button(key=f"confirm_unassign_{assignment}").click().run()
    assert not app.exception and service.get_assignment_by_id(assignment) is None


def test_overallocation_grid_includes_nested_leaves_even_with_spare_container_capacity(database, access):
    service = create_resource_pool_service(database, access=access)
    parent = service.create_pool(ResourcePool('Parent'))
    nested = service.create_pool(ResourcePool('Nested', parent_pool_id=parent))
    first = service.create_pool(ResourcePool('First', capacity_fte=1, parent_pool_id=nested))
    second = service.create_pool(ResourcePool('Second', capacity_fte=2, parent_pool_id=parent))
    service.create_pool(ResourcePool('Spare', capacity_fte=100, parent_pool_id=parent))
    for pool in [first, second]:
        service.create_assignment(PoolAssignment(pool, 1, 3,
            start_date='2027-01-01', end_date='2027-01-03'))
    app = native_screen("""
from app.main import create_pool_capacity_service, create_organization_service, create_resource_pool_service
from app.presentation.pages.resource_pools import render_resource_pools
render_resource_pools(create_resource_pool_service(runtime, access=access),
    create_pool_capacity_service(runtime, access=access), create_organization_service(runtime, access=access), 'planning')
""", database, access)
    for selected, expected in [(parent, ['First', 'Second']), (nested, ['First']), (second, ['Second'])]:
        app.session_state['target_resource_pool_id'] = selected
        app.run()
        assert not app.exception
        grid = app.dataframe[0].value
        assert list(grid.columns) == ['Pool name', 'Date start', 'Date stop', 'FTE']
        assert grid['Pool name'].tolist() == expected
        assert grid['FTE'].tolist() == ([2, 1] if selected == parent else [2] if selected == nested else [1])
        assert grid['Date start'].astype(str).tolist() == ['2027-01-01'] * len(expected)
        assert grid['Date stop'].astype(str).tolist() == ['2027-01-03'] * len(expected)


def test_container_inspector_shows_children_and_aggregates_without_mapping_controls(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    parent = service.create_pool(ResourcePool('Parent'))
    leaf = service.create_pool(ResourcePool('Delivery', capacity_fte=4, parent_pool_id=parent))
    organization = create_organization_service(database, access=access)
    employee = organization.create_employee(Employee('Ada', 'Lovelace', 'ada@pool.test', 'POOL-ADA'))
    service.create_mapping(PoolMapping(leaf, 'employee', employee, 50))
    assignment = service.create_assignment(PoolAssignment(leaf, 1, 0.25))
    app = native_screen("""
from app.main import create_pool_capacity_service, create_organization_service, create_resource_pool_service
from app.presentation.pages.resource_pools import render_resource_pools
render_resource_pools(create_resource_pool_service(runtime, access=access),
    create_pool_capacity_service(runtime, access=access), create_organization_service(runtime, access=access), 'planning')
""", database, access)
    app.session_state['target_resource_pool_id'] = parent
    with patch('app.presentation.components.action_table.action_table', return_value=None) as table:
        app.run()
    assert table.call_args.kwargs['key'] == f'pool_assignments_{leaf}'
    assert table.call_args.args[0][0]['id'] == assignment
    assert not app.exception and not app.error
    assert app.dataframe[0].value.iloc[0]['Pool'] == 'Delivery'
    assert app.dataframe[0].value.iloc[0]['Resource'] == 'Ada Lovelace'
    assert app.dataframe[0].value.iloc[0]['Effective FTE'] == 0.5
    assert not any(button.key == f'btn_add_map_{parent}' for button in app.button)
    assert {metric.label: metric.value for metric in app.metric} == {
        'Total Pools': '1', 'Overassigned Pools': '0', 'Pools with no assignment': '0'}


def test_deleted_visibility_and_summary_calculate_only_active_leaves(database, access):
    service = create_resource_pool_service(database, access=access)
    parent = service.create_pool(ResourcePool('Parent'))
    leaf = service.create_pool(ResourcePool('Leaf', capacity_fte=2, parent_pool_id=parent))
    deleted = service.create_pool(ResourcePool('Deleted leaf', capacity_fte=100, parent_pool_id=parent))
    service.delete_pool(deleted)
    app = native_screen("""
from app.main import create_pool_capacity_service, create_organization_service, create_resource_pool_service
from app.presentation.pages.resource_pools import render_resource_pools
render_resource_pools(create_resource_pool_service(runtime, access=access),
    create_pool_capacity_service(runtime, access=access), create_organization_service(runtime, access=access), 'planning')
""", database, access)
    with patch('app.presentation.pages.resource_pools.resource_pool_tree', return_value=None) as tree, \
            patch('app.application.services.pool_capacity.aggregate_capacity', side_effect=AssertionError('Container calculation')):
        app.run()
        assert not app.exception and not app.error
        assert app.multiselect(key='pool_demand_statuses').value == ['In Progress']
        assert not app.checkbox(key='pool_show_deleted').value
        assert set(tree.call_args.args[0].pools) == {parent, leaf}
        assert set(tree.call_args.args[1]) == {leaf}
        assert set(tree.call_args.kwargs['assigned_capacities']) == {leaf}
        assert set(tree.call_args.kwargs['peak_demands']) == {leaf}
        app.checkbox(key='pool_show_deleted').check().run()
        assert not app.exception and not app.error
        assert set(tree.call_args.args[0].pools) == {parent, leaf, deleted}
        assert set(tree.call_args.args[1]) == {leaf}
        assert {metric.label: metric.value for metric in app.metric} == {
            'Total Pools': '1', 'Overassigned Pools': '0', 'Pools with no assignment': '1'}
