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

Task 5.1 replaces the monolithic asset with the shared core/bridge plus scoped
EPPM DTO/transport/command/choice/project-batch modules. Native scenario and
project-dependency selectors now address mounted parts, opaque targets, lanes
and accessible menu/form controls. All persistence, baseline isolation, colors,
milestone/date-handle counts, label associations/focus, dependency warning text,
stale drafts, explicit reload, relative allocations, activation confirmation and
single-rerun assertions remain. Diagnostic warning marks open their inspector
directly; its same delivered content is asserted without the former intermediate
global menu ID. The registration test now patches the Python presentation adapter.

Integration validation (targeted evidence, not final acceptance):

- PostgreSQL/native group: `test_gantt_scenarios_browser.py`,
  `test_project_dependency_browser.py`, `test_gantt_step_reruns.py`,
  `test_scoped_planning_updates_ui.py`, `test_planning_ui.py`,
  `test_gantt_scenarios.py`, `test_planning_http.py`, `test_planning_log_event.py`,
  `test_shared_project_filters_browser.py`: **111 passed in 195.03 s** using the
  isolated workflow database configuration and actual restricted browser servers.
- EPPM/shared mounted browser, distributions, installed consumers and Python
  adapter checks: **45 passed in 55.23 s**. These retain resource row/cell bounds,
  two-instance isolation, frame/scroll alignment and installed asset checks.
- Latest Node module/protocol checks: **105 passed**. These include captured
  draft revisions, task-creation defaults, approval/admin versus edit hints,
  403/409 single refresh, source tokens, redaction and group filter identities.
- After preserving creation defaults, EPPM browser/Python follow-up: **12 passed
  in 5.33 s**. Python callback/event/edit-mode checks: **33 passed in 0.43 s**.

Native checks exposed a rerun/menu race and missing comparison-summary identity;
both were corrected. Mounted checks exposed scale/scroll extent publication
before the next animation frame; mode changes now publish geometry synchronously.
Restored individual column controls required the existing splitter selectors to
name the main splitter explicitly. Failed attempts are not acceptance evidence.
Remaining legacy source/global consumers and repeated benchmark comparisons are
tracked in tasks 5.2 and 6.1.

Task 5.3 records the renderer correction discovered during that consumer mapping.
Mounted small vertical scrolls through 400 px now retain the existing task DOM;
large jumps keep the existing at-most-39-row fixture bound. Imported clipping
checks retain the original `[2400,207,2100,1076.4]` rectangle for a 900 px
viewport at scroll 3000 and rows 5–30; scrolling to 3100 reuses that rectangle,
and jumping to 8000 moves it to x=7400. Mounted checks exercise real SVG bounds,
clickable two-member incoming markers, inspection, and marker removal outside
the row window. Known expanded/unloaded task endpoints wait for hydration.
The independent Node suite passed **100 checks**, and mounted component checks
passed **21 tests in 33.98 s**. This corrects earlier extracted renderer behavior.
Native project-dependency/alternative-context follow-ups passed **2 tests in
29.35 s** with the actual EPPM bootstrap and restricted PostgreSQL services.
Legacy entry migration and final performance acceptance remain pending.

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

Task 5.4 restores nested viewport-bounded menus, capacity badge/tooltip styling,
comparison resource restrictions, task assignment identity/icon, coalesced
independently cancellable predecessor reads, failed-choice selection retention,
and expansion without viewport movement after creation. Public configuration and
EPPM ownership documentation describe these behaviors. Validation: 111 Node
module/adapter checks passed; 32 mounted component/adapter browser checks passed
in 48.71 seconds; all five native PostgreSQL project-dependency/scenario browser
checks passed in 63.84 seconds. The native checks retain stale-save, dependency,
scenario activation, milestone and shared-dialog assertions. Browser selectors
are scoped per instance and await rendered expansion before invoking markers.

## Remaining legacy consumer migration (task 5.2)

The four original CJS entry points remain runnable. They import their extracted
owner tests instead of parsing HTML function bodies; Node's normal test runner
executes the same assertions in those modules. The three unrelated CSV download,
tab-position and action-table cases remain in `test_ui_menus.cjs` unchanged.
Mounted checks complement pure models; implementation globals are not retained.

| Original assertion group | Current assertion owner / mounted coverage |
| --- | --- |
| Complete script parses | Browser module graph loads without page errors in `test_planning_component_browser.py` / `test_eppm_planning_browser.py`; all Node modules import in entry checks |
| Project single-click; task double-click; resource single/double-click cancellation | Timeline expansion/pairing and resource action tests in `test_planning_component_browser.py`; native alternative-resource workflow |
| Hierarchy all-level expansion / collapse keeps roots | `resource-grid.test.js` hierarchy projection and mounted collapse/expand controls; native alternative-resource workflow |
| Calendar Month/Quarter/Year exact 15/5/4 cells and 675/140/160 widths, leap/year adjacency | `models.test.js` period geometry cases |
| Row 41.4 px / toolbar padding / 234–495 panel and full frame height | Mounted timeline/resource geometry, `test_eppm_planning_browser.py`, native baseline/alternative resource checks |
| Fixed headers, horizontal synchronization and independent vertical offsets | `test_resource_grid_headers.py` mounted ancestor/position checks; scroll/splitter and resource alignment tests |
| Eight precision boundaries and 23.8 px resource rows | `models.test.js` exact legacy precision cases; native alternative-resource height assertions |
| Comparison peaks compare displayed periods rather than different daily dates | `resource-grid.test.js` equal swapped daily peaks vs differing Day periods |
| One red scale / gray alternatives | EPPM mode styles and mounted per-instance mode state checks |
| Hide unused / ancestor retention / collapsed groups / changed selection / no matches | `resource-grid.test.js` exact legacy visibility fixtures and native resource controls |
| External links initially disabled | EPPM snapshot hints and every benchmark configuration's checked public toolbar state |
| Daily-zero capacity filter composed with selected-project visibility and period | `resource-grid.test.js` exact legacy [2,3]/[3]/empty period assertions |
| Dependency FS/SS/FF/SF, bundles, member identity, lag, violation, whole-project header | `dependencies.test.js` geometry/index/inspection cases and mounted bundle/dependency editor tests |
| 600 px horizontal overscan and exact clip rectangles | `dependencies.test.js` [2400,207,2100,1076.4] / reuse / [7400,...]; mounted SVG viewBox/width assertions |
| Incoming entry markers, all members and no orphan stubs | Mounted dependency viewport test; expanded undelivered endpoint module test |
| Retained small-scroll DOM, bounded large jumps, data refresh, frame coalescing | Mounted row-identity/large-scroll/disposal tests, `timeline.test.js`, `lifetime.test.js` |
| Local/visible/offscreen/whole-project predecessor choices | Generic task editor choices; EPPM project panel and predecessor-reader module/mounted cases |
| Capacity min/max, daily paired excess, cache identity and sparse override availability | `models.test.js` original zero/0.1/8/full-override/matching-day cases plus scope summary tests |
| Choice queue, stale/project/source correlation and retained selected predecessor on failure | `streamlit.test.js` queue ownership, `test_eppm_planning_adapter.cjs` coalesced reader, mounted failed-choice and project-panel tests |
| Baseline first capture / replacement confirmation / opt-in approval | EPPM command capability and confirmation tests; native immutable baseline workflow |
| Task/project permissions, log without edit mode, navigation/export retained, stale listeners | `actions.test.js`, EPPM capability matrix, mounted revocation during editor/pointer edit |
| Dependency owners / shared-pool administration / alternative-only writes | EPPM adapter dependency/resource capability cases and native scenario dependency/edit checks |
| HTTP 25/100, requested fingerprints, unchanged source patches, single flight / stale abort / 403–409 refresh / explicit retry | `state.test.js`, `test_eppm_planning_adapter.cjs`, mounted lazy read/retry and native HTTP tests |
| Same-selection viewport vs new-scope reset; unrelated record identity; hydration / eviction / exact intervals | `state.test.js`, `models.test.js`, mounted update/creation tests and native scoped update workflows |
| CSV/pool/group identity, quarter dates, total/selected allocation scopes and filter scopes | EPPM event mapping, mounted period drill-through and native alternative-resource filtering / shared CSV panels |
| Viewport-clamped pointer/keyboard nested menus and cancelled confirmations | Mounted nested menu bounds, Tab/Right/Left, single delivery and EPPM cancelled confirmation tests |
| Badge-only orange/purple deviation, whole-calendar capacity summary, escaped concise green/red FTE hover | `models.test.js` capacityDetails and mounted EPPM capacity tooltip / color assertions |
| Task assignment person icon / owning identity | Mounted EPPM Assign Resource test and native shared task-pool dialog |
| Tooltip 600 ms hidden / one-second show / 200 ms cancellation / native-title restoration | `test_gantt_tooltip_browser.py` now mounts the actual component |
| Resource toggle and comparison disabled details / enabled nested filters with keyboard | Gantt case in `test_table_accessibility_browser.py` now mounts the actual adapter |
| Native baseline, alternative-only pools, tags, CSV, shared dependency panels, recovery, portfolio navigation/filter spacing | Corresponding PostgreSQL consumers use public target/lane/part attributes, accessible buttons and host render messages |
| 10,001-project load harness usable task arrival | `tests/performance/browser_load.py` selects rendered nonempty headers and waits for actual task DOM, without private models |

The benchmark uses the same mounted message/control boundary with an isolated
loopback asset server and installed Playwright driver. It retains positive and
<=40 resource rows, positive cells, <=1 px pane alignment, bundle-member and
Year fit checks. Its native driver performs a real accepted task edit and asserts
source data and disposable database cleanup. The extended procedure documents
measurement boundaries and why captures must not overlap database-copy tests.

Task 5.2 validation: all original JavaScript entry checks plus extracted module
checks passed (302 checks with normal Node file isolation). All mounted component,
EPPM, tooltip/header and table accessibility checks passed (44 tests, 58.71 s).
The migrated native baseline/filter-spacing/portfolio navigation group passed
six checks (52.41 s); the additional alternative-resource/shared-scenario/native
benchmark group passed three checks (38.61 s), including a real editor update and
source/copy cleanup. The explicit five-repeat collector passed 25 checks in
112.46 s; every configuration retained its row/alignment/fit hard assertions.
Timing medians and the still-unapproved render-budget regression are recorded in
`performance-comparison.md` / `candidate.json`. Consumer migration completion does
not waive that separate gate or replace strict full-suite acceptance.

Task 5.7 restores the design's callback fallback for hosts without a direct HTTP
task endpoint. It uses the existing generic bridge queue and Python action, with
nonce correlation and an echoed request revision in presentation patches. Raw
patch scope mismatch is rejected; a stale requested revision cannot update a
newer store. The HTTP path and server authorization/25–100 bounds are unchanged.
The native diagnostic now exercises that actual fallback without an HTTP proxy.
Validation: 32 focused adapter/bridge/state checks, 11 mounted EPPM checks
(14.51 s), and seven native benchmark/bounded-loading/single-rerun regressions
(18.33 s) passed. Module coverage adds malformed record/hierarchy capability
regressions; the 117-test pure run passes with 100% statement coverage in contracts,
owned messages, calendar, state/loading, resource models and dependency models.
Mounted DOM coverage is separate; the Node aggregate includes unexecuted browser
renderers and is not represented as full browser coverage. Final full-suite and
installed-artifact evidence remain part of task 6.1.

The cross-component `test_every_existing_context_menu_uses_the_shared_visual_standard` retains inline CSS checks for inline components and verifies the Gantt module bootstrap. `test_shared_menu_visual_standard_matches_host_context_menus` compares the extracted panel and ordinary/focused items against the actual shared host CSS through computed browser styles; nested keyboard/viewport regressions remain mounted checks.
