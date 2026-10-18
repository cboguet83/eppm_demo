# Extraction reference (task 1.2)

## Fixture and environment

Source baseline: planning commit `48386c9`, with the reference-fixture correction
in this task. Python 3.14.7, Node 26.11.1, Chrome for Testing 151.0.7922.34,
Linux, browser viewport 1500 by 1100. The browser retains its default sandbox.
Tests launch temporary profiles and disposable PostgreSQL databases against the
explicit test-server configuration; no application data is edited.

Synthetic fixture: 100 projects, 1,000 tasks, 127 pools, 730 dated capacity/demand
entries per pool, and dense cross-project dependencies. Native fixture:
`tests/postgresql/business.py` with two projects/tasks and one assigned pool.
The native driver restores that fixture before exercising its existing callback
transport. This diagnostic does not measure OIDC login or native HTTP hydration;
the separate native browser checks exercise the actual application.

The synthetic fixture previously omitted `used_by_selected_projects`, so default
Hide unused pools filtered out every pool. The task adds that fixture flag and
requires positive resource row/cell counts, at most 40 resource rows, and pane
alignment within 1 pixel. Application behavior is unchanged.

## Behavior-to-test mapping

| Behavior retained during extraction | Existing reference checks |
| --- | --- |
| Calendar boundaries, row geometry, frame sizing, synchronized scroll | `tests/test_gantt_scrolling.cjs` |
| Opt-in editing, revoked capabilities, baseline capture, alternative-only drag | `tests/test_gantt_permissions.cjs`, `tests/test_gantt_edit_mode.py` |
| Single-flight reads, 25/100 bounds, eviction, stale revisions, patches, interval zero/gap transport | `tests/test_planning_lazy.cjs` |
| Project/task/resource context and filter scope | `tests/test_ui_menus.cjs` |
| Delayed tooltip, cancelled reveal, native title restoration | `tests/test_gantt_tooltip_browser.py` |
| Keyboard submenus and resource toggle | Gantt case in `tests/test_table_accessibility_browser.py` |
| Independent fixed resource headers | `tests/test_resource_grid_headers.py` |
| Event validation, deduplication, viewport focus and targeted host updates | `tests/test_planning_event_requests.py`, `tests/test_planning_view.py` |
| Created/selected scenarios, milestones, shared dialogs, dependencies, activation | `tests/postgresql/test_gantt_scenarios_browser.py` |
| Organization/status selection and navigation | `tests/postgresql/test_shared_project_filters_browser.py` |
| Native summary invalidation, scope tokens and bounded patches | `tests/postgresql/test_planning_lazy.py` |

Replace source-slicing tests with imported module or mounted-interface tests as
their owners are extracted. Preserve the behavior/assertion in this table; do
not retain private globals merely to satisfy a test. Keep existing native
security and transactional checks.

Task 3.2's imported `packages/planning-view/tests/timeline.test.js` and mounted
`tests/test_planning_component_browser.py` now characterize project boundaries,
summary/placeholder geometry, sort and expansion, inclusive leap-day bars,
milestones, progress, stable comparison pairing and overlay-only rows. The
mounted 1,000-task fixture asserts at most 39 timeline rows and unchanged bar
nodes on horizontal scroll. Injected-read disposal is checked in the browser.
Existing EPPM entry checks remain until the compatibility integration is migrated.

Tasks 3.3/3.4 add imported dependency/action checks and mounted regressions for
individual bundle inspection, hidden endpoint redaction, safe correlated
rejection, accepted dates, resize/progress, alternative-only writes, draft
preservation/removal, mid-drag revocation, single/double-click delivery,
keyboard submenus/editors, delayed/cancelled hover and disposal during a drag.
These become the independent behavior surface for the permissions, menu,
tooltip and dependency assertions when task 5.2 removes source slicing.

Task 3.5 adds imported resource-grid hierarchy/window/filter checks and mounted
1,001-pool checks for capacity/demand/excess, comparison scopes, period/header
alignment, allocation/context/clear-filter events, single/double-click and
keyboard behavior, dynamic sizing and optional layout. The fixture asserts at
most 40 mounted resource rows and fewer than 40×30 cells while scrolling both
axes. Group selection uses actual hierarchy IDs and preserves independent
resource vertical scroll/reset through the store.

## Commands and current results

- `node --test tests/test_gantt_scrolling.cjs tests/test_gantt_permissions.cjs tests/test_planning_lazy.cjs tests/test_ui_menus.cjs`: four files passed.
- Targeted Python edit-mode, event, view, and resource-header checks: 28 passed.
- Tooltip and Gantt keyboard browser checks: two passed, seven unrelated cases deselected.
- Native scenario, shared-filter and lazy-projection checks: ten passed in 88.61 seconds.
- Final serial capture: 25 passed in 118.92 seconds. Five iterations of all five modes are retained in `reference.json` with the original asset checksum and runtime versions.

Median initial-render / scroll-work-p95 times were 35.1 / 4.8 ms collapsed,
36.8 / 4.4 ms expanded, and 38.6 / 5.0 ms with external links. Synthetic
captures rendered 26 resource rows and 208 cells with zero pane misalignment.
Native date-edit preparation had median 0.646 seconds with a 2,850-byte
component payload. Native render median was 25.5 ms on the small fixture.

The first sandboxed tooltip launch failed because process operations were
restricted; rerunning with approved host execution passed. The initial capture
module omitted fixture registration and was corrected. An early repeated run
passed 18 cases before a global database-set assertion detected another
concurrent capture's copy. The corrected harness checks source integrity and
the host-edit capture checks cleanup of its own named copy. These failed
attempts are not accepted reference measurements.

Capture repeated measurements explicitly (this module is intentionally outside
default `test_*.py` discovery):

```bash
POSTGRES_TEST_CLIENT_CONTAINER=eppm-workflow-tests-postgres-1 \
python -m dotenv -f /path/to/ignored/workflow-tests.env run -- \
  python -m pytest -q -x -p no:cacheprovider \
  tests/postgresql/capture_gantt_reference.py \
  --basetemp=.local/gantt-reference-NEW-RUN
```

Use a new ignored temporary directory for each run. The harness records five
iterations each of collapsed, expanded, external-link, native-render, and
native-date-edit modes. Preserve the resulting numeric reports in
`reference.json` and compare the same fixtures, browser, viewport, flags, and
transport after extraction. Host timings exclude browser paint. No credentials
or business payloads belong in reports. Final change acceptance still requires
the complete strict suite; this reference is not full acceptance evidence.
