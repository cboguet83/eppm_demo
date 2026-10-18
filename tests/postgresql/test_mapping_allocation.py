"""Real transactions, restored pools and mapping popup allocation limits."""

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import islice
import json
from pathlib import Path
from threading import Barrier, local
from typing import TYPE_CHECKING

import pytest
import psycopg
from streamlit.proto.BackMsg_pb2 import BackMsg

from app.domain.organization.models import Employee, OrgFunction, Team
from app.domain.resources.models import PoolMapping, ResourcePool
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore
from app.application.services.business_access import BusinessAccess
from app.main import create_organization_service, create_resource_pool_service
from app.runtime import RuntimeResources
from tests.postgresql.test_resource_pool_ui import database, access, dialog
from tests.postgresql.browser import native_server
from tests.postgresql.browser_completion import ScriptCompletion
from tests.postgresql.test_pool_hierarchy_browser import SCREEN

if TYPE_CHECKING:
    from playwright.sync_api import Page, WebSocket
    from tests.postgresql.conftest import AuthorizedFixture


_RESTORATION_SCREEN = r"""
import importlib
import json
from pathlib import Path
from app.domain.resources.models import ResourcePool
from app.domain.resources.hierarchy import PoolHierarchy
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore

_pool_module = importlib.import_module('app.presentation.pages.resource_pools')
_trace_path = Path(__file__).with_name('restoration-counts.jsonl')

def _record_counts(kind: str, include_deleted: bool, count: int, deleted: int) -> None:
    with _trace_path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'kind': kind, 'include_deleted': include_deleted,
                                 'count': count, 'deleted': deleted}) + '\n')

if not hasattr(PostgresResourcePoolStore, '_restoration_original_read'):
    PostgresResourcePoolStore._restoration_original_read = PostgresResourcePoolStore.get_all_pools
    def _observed_read(self: PostgresResourcePoolStore, *, include_deleted: bool = False) -> list[ResourcePool]:
        rows = PostgresResourcePoolStore._restoration_original_read(self, include_deleted=include_deleted)
        _record_counts('read', include_deleted, len(rows), sum(row.deleted_flag for row in rows))
        return rows
    PostgresResourcePoolStore.get_all_pools = _observed_read

if not hasattr(_pool_module, '_restoration_original_tree'):
    _pool_module._restoration_original_tree = _pool_module.resource_pool_tree
    def _observed_tree(hierarchy: PoolHierarchy, *args: object, **kwargs: object) -> object:
        _record_counts('tree', bool(st.session_state.get('pool_show_deleted')),
                       len(hierarchy.pools), sum(row.deleted_flag for row in hierarchy.pools.values()))
        return _pool_module._restoration_original_tree(hierarchy, *args, **kwargs)
    _pool_module.resource_pool_tree = _observed_tree
""" + SCREEN


def _observe_restoration_toggle(
    page: 'Page', completion: ScriptCompletion,
) -> list[tuple[int, bool]]:
    """Record only completion state when the first deleted-visibility request leaves.

    Args:
        page: Private browser page, before navigation.
        completion: Its passive server completion observer.

    Returns:
        A list populated by the first true checkbox request; no raw frames persist.
    """
    observations: list[tuple[int, bool]] = []

    def receive(payload: str | bytes) -> None:
        if observations or not isinstance(payload, bytes):
            return
        message = BackMsg.FromString(payload)
        if not message.HasField('rerun_script'):
            return
        widgets = message.rerun_script.widget_states.widgets
        if any(widget.id.endswith('-pool_show_deleted')
               and widget.HasField('bool_value') and widget.bool_value
               for widget in widgets):
            observations.append((completion._completed, completion._running))

    def observe(socket: 'WebSocket') -> None:
        socket.on('framesent', receive)

    page.on('websocket', observe)
    return observations


def _diagnostic_fields(
    value: object, shape: dict[str, type[object]],
) -> dict[str, object]:
    """Retain only explicitly allowed fields with exact primitive types."""
    if not isinstance(value, dict):
        return {}
    labels = {'kind': {'read', 'tree'}, 'scriptState': {'running', 'notRunning'}}
    return {
        key: value[key] for key, expected in shape.items()
        if type(value.get(key)) is expected
        and (expected is not str or value[key] in labels[key])
    }


def _restoration_snapshot(
    page: 'Page', completion: ScriptCompletion, directory: Path,
) -> str:
    """Capture only counts, flags and completion metadata, never raw messages.

    Args:
        page: The failing test's private browser page.
        completion: Passive observer attached before navigation.
        directory: This test's private server directory.

    Returns:
        JSON containing only diagnostic state, excluding cookies and URLs.
    """
    from playwright.sync_api import Error as PlaywrightError

    state: dict[str, object] = {
        'successful_runs': completion._completed,
        'script_running': completion._running,
    }
    try:
        trace = directory / 'restoration-counts.jsonl'
        with trace.open(encoding='utf-8') as stream:
            state['server_counts'] = [
                _diagnostic_fields(json.loads(line), {
                    'kind': str, 'include_deleted': bool,
                    'count': int, 'deleted': int,
                })
                for line in islice(stream, 64)
            ]
    except (OSError, ValueError) as error:
        state['server_counts_unavailable'] = type(error).__name__
    try:
        dom = page.evaluate("""() => ({
            checkboxChecked: document.querySelector('input[type=checkbox]')?.checked ?? null,
            scriptState: document.querySelector('[data-testid=stApp]')
                ?.getAttribute('data-test-script-state') ?? null
        })""")
        state['dom'] = _diagnostic_fields(dom, {
            'checkboxChecked': bool, 'scriptState': str,
        }) | {
            # Playwright locators traverse the component's shadow root.
            'treeRows': page.get_by_role('treeitem').count(),
            'deletedRows': page.locator('[role=treeitem] .pool-deleted').count(),
        }
    except PlaywrightError as error:
        state['dom_unavailable'] = type(error).__name__
    return json.dumps(state, sort_keys=True)


@contextmanager
def _report_restoration_failure(
    page: 'Page', completion: ScriptCompletion, directory: Path,
) -> Iterator[None]:
    """Attach safe observations while propagating the original browser failure.

    Args:
        page: The test's private page.
        completion: Passive protocol observer.
        directory: This test's private server directory.

    Yields:
        Control to the original browser actions and assertions.
    """
    from playwright.sync_api import Error as PlaywrightError

    try:
        yield
    except (AssertionError, PlaywrightError) as error:
        details = _restoration_snapshot(page, completion, directory)
        error.add_note(f'Restoration browser diagnostics: {details}')
        raise


def setup_resources(database, access):
    service = create_resource_pool_service(database, access=access)
    org = create_organization_service(database, access=access)
    first = service.create_pool(ResourcePool('Alpha'))
    second = service.create_pool(ResourcePool('Beta'))
    function = org.create_function(OrgFunction('Engineer'))
    team = org.create_team(Team('Delivery'), function_ids=[function])
    employee = org.create_employee(Employee('Ada', 'One', 'ada@example.test', function_id=function))
    return service, first, second, team, employee


def test_all_write_paths_reject_excess_and_restore_rejects_conflict(database, access):
    service, first, second, team, employee = setup_resources(database, access)
    service.create_mapping(PoolMapping(first, 'employee', employee, 60))
    with pytest.raises(ValueError, match='cannot exceed 100%'):
        service.create_mapping(PoolMapping(second, 'employee', employee, 50))
    mapping = service.create_mapping(PoolMapping(second, 'employee', employee, 40))
    with pytest.raises(ValueError):
        service.update_mapping(mapping, 41)
    with pytest.raises(ValueError):
        service.save_mappings(second, [PoolMapping(second, 'employee', employee, 50)])
    assert service.get_mappings_by_pool(second)[0].allocation_pct == 40
    service.delete_pool(first)
    service.update_mapping(mapping, 100)
    assert not service.mapping_catalog().allocations().overallocated
    with pytest.raises(ValueError, match='Cannot restore'):
        service.undelete_pool(first)
    service.update_mapping(mapping, 40)
    assert service.undelete_pool(first)
    assert not service.mapping_catalog().allocations().overallocated


def test_popup_filters_exhausted_resources_and_defaults_to_remaining(database, access):
    service, first, second, team, employee = setup_resources(database, access)
    service.create_mapping(PoolMapping(first, 'employee', employee, 65))
    app = dialog(database, access, f'_open_add_pool_mapping_dialog(service, {second}, teams, employees)')
    app.checkbox(key=f'direct_employee_mapping_mode_{second}').check().run()
    app.multiselect(key=f'mapping_employees_{second}').set_value([employee]).run()
    widget = app.number_input(key=f'mapping_pct_{second}_employee_{employee}')
    assert widget.value == 35 and widget.max == 35
    next(button for button in app.button if button.label == 'Save mappings').click().run()
    assert not app.exception and not app.error
    third = service.create_pool(ResourcePool('Gamma'))
    app = dialog(database, access, f'_open_add_pool_mapping_dialog(service, {third}, teams, employees)')
    app.checkbox(key=f'direct_employee_mapping_mode_{third}').check().run()
    assert app.multiselect(key=f'mapping_employees_{third}').options == []
    assert len(app.multiselect(key=f'mapping_teams_{third}').options) == 1


def test_removing_direct_mapping_cannot_expose_duplicate_team_overallocation(database, access):
    service, first, second, team, employee = setup_resources(database, access)
    org = create_organization_service(database, access=access)
    other = org.create_team(Team('Other team'), function_ids=org.get_team_functions(team))
    direct = service.create_mapping(PoolMapping(first, 'employee', employee, 100))
    service.create_mapping(PoolMapping(first, 'team', team, 100))
    service.create_mapping(PoolMapping(second, 'team', other, 100))
    with pytest.raises(ValueError, match='cannot exceed 100%'):
        service.delete_mapping(direct)
    assert service.mapping_catalog().allocations().total(('employee', employee)) == 100


def test_employee_at_80_percent_leaves_20_percent_capacity_for_fully_mapped_team(database, access):
    service, first, second, team, employee = setup_resources(database, access)
    service.create_mapping(PoolMapping(first, 'employee', employee, 80))
    app = dialog(database, access, f'_open_add_pool_mapping_dialog(service, {second}, teams, employees)')
    assert any('Teams use the remaining employee capacity' in caption.value for caption in app.caption)
    app.multiselect(key=f'mapping_teams_{second}').set_value([team]).run()
    widget = app.number_input(key=f'mapping_pct_{second}_team_{team}')
    assert widget.value == widget.max == 100
    next(button for button in app.button if button.label == 'Save mappings').click().run()
    assert not app.exception and not app.error
    assert service.mapping_catalog().allocations().total(('employee', employee)) == 100


def test_concurrent_allocations_cannot_both_consume_same_remaining_capacity(database, access, monkeypatch):
    service, first, second, _, employee = setup_resources(database, access)
    barrier, state = Barrier(2), local()
    original = PostgresResourcePoolStore.mapping_catalog
    def synchronized(store):
        result = original(store)
        if not getattr(state, 'read', False):
            state.read = True
            barrier.wait(timeout=15)
        return result
    monkeypatch.setattr(PostgresResourcePoolStore, 'mapping_catalog', synchronized)
    def allocate(pool):
        try:
            service.create_mapping(PoolMapping(pool, 'employee', employee, 60))
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(allocate, [first, second]))
    assert sorted(results) == [False, True]
    monkeypatch.setattr(PostgresResourcePoolStore, 'mapping_catalog', original)
    assert service.mapping_catalog().allocations().total(('employee', employee)) == 60


@pytest.mark.parametrize(
    'delayed_initial_completion', [False, True],
    ids=['ordinary', 'delayed-initial-completion'],
)
def test_blocked_restoration_popup_explains_conflicting_pools(
    database: RuntimeResources, access: BusinessAccess,
    authorized: 'AuthorizedFixture', tmp_path: Path,
    delayed_initial_completion: bool,
) -> None:
    """Preserve restoration rejection after bounded initial/toggle completion."""
    playwright_api = pytest.importorskip('playwright.sync_api')
    service, first, second, _, employee = setup_resources(database, access)
    service.create_mapping(PoolMapping(first, 'employee', employee, 100))
    service.delete_pool(first)
    service.create_mapping(PoolMapping(second, 'employee', employee, 100))
    screen = _RESTORATION_SCREEN
    if delayed_initial_completion:
        # Controlled precondition gap, not a reproduction of the hosted failure.
        screen += """
import time
if not st.session_state.get('_initial_restoration_completed'):
    time.sleep(2)
    st.session_state['_initial_restoration_completed'] = True
"""
    with native_server(authorized, tmp_path, screen) as server, playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1200})
            completion = ScriptCompletion(page)
            toggles = _observe_restoration_toggle(page, completion)
            with _report_restoration_failure(page, completion, tmp_path):
                page.goto(server.origin)
                with completion.action():
                    playwright_api.expect(page.get_by_role(
                        'treeitem', name='Beta', exact=True,
                    )).to_be_visible(timeout=30000)
                    page.get_by_text('Show deleted pools', exact=True).click()
                row = page.get_by_role('treeitem', name='Alpha (Deleted)', exact=True)
                playwright_api.expect(row).to_be_visible(timeout=30000)
                row.click(button='right')
                page.get_by_role('menuitem', name='Undelete pool', exact=True).click()
                popup = page.get_by_role('dialog')
                playwright_api.expect(popup).to_contain_text('200% allocated')
                playwright_api.expect(popup).to_contain_text('Alpha: 100%; Beta: 100%')
                page.screenshot(path=str(tmp_path / 'restoration-blocked.png'), full_page=True)
                popup.locator('.st-key-close_pool_restoration_warning button').click()
                playwright_api.expect(row).to_be_visible()
                with psycopg.connect(authorized.setup.operator_url) as connection:
                    assert connection.execute('SELECT deleted_flag FROM eppm.resource_pool WHERE id=%s', (first,)).fetchone() == (True,)
                assert len(toggles) == 1
                assert toggles[0][0] > 0, 'Toggle preceded initial successful completion'
                assert toggles[0][1] is False, 'Toggle interrupted an active script'
        finally:
            browser.close()
