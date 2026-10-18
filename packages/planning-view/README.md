# Planning view: host contract v1

The independent contracts module uses native ES modules and no runtime imports.
Run `node --test packages/planning-view/tests/*.test.js` from the repository root.
The root export is `mountPlanningView`; internal modules remain implementation
seams for focused tests. Rendering features are added by the extraction tasks.

`validateMessage(input)` returns an independently owned validated JSON copy or
throws `ContractError` with only a schema location. Call it before changing view
state. `validateEvent(input)` validates display intentions; hosts must still
authorize every read/write. Contract version 1 is separate from package 0.1.0.

Messages have `version: 1`, nonempty opaque `scope` and `revision` strings and
`kind` of `snapshot`, `patch`, or `response`. A snapshot supplies `projects` and
`tasks`; each record has a unique opaque string `id`. Projects have `name`.
Tasks have `projectId`, `name`, inclusive ISO calendar `start`/`end`, optional
`progress` from 0 through 100, and optional `stableId` for comparison pairing.
Snapshot tasks must belong to supplied projects. Task IDs are unique per view;
overlay IDs and stable pairing identities are mapped by host adapters.

Optional fields are `dependencies`, `resources`, `hierarchy`, `overlays`, flat
boolean `capabilities`, and flat text `labels`. Dependencies supply `id`, `type`
(FS/SS/FF/SF), integer `lagDays`, and predecessor/successor endpoints. Endpoints
have `kind` project/task plus opaque `id`, or `kind: unavailable` with no invented
metadata. Resource records supply `id`, `name`, nonnegative `capacity`, and
optional `usage`, `selectedUsage`, `assignedCapacity` daily ISO-date maps. Zero
is retained and missing days remain absent. Hierarchy nodes have unique `id`,
optional `resourceId`, and optional `children`; cycles are rejected iteratively.
Overlays supply `id`, `kind` baseline/alternative, `projectId`, `tasks`, and
optional dependencies using the same record shapes.

Patches supply changed collections and optional unique string lists
`replaceProjectIds`, `removeProjectIds`, `loadedProjectIds`. State ownership,
cross-collection patch reconciliation, and request cancellation belong to the
instance store, added in task 2.3. `reset` is an optional explicit boolean.
Responses carry `requestId`, `accepted`, and optional safe text `error`.

Events carry the same version/scope/revision plus `requestId` and `type`:
dates/progress/task/dependency/select use `targetId`; date edits add start/end;
progress edits add progress; commands add `command`; loads add `projectIds`.
Hosts accept or reject requests through correlated responses and authoritative
updates. UI capabilities are presentation hints. Additional metadata must be
JSON data; cycles, executable values, nonfinite numbers, and class instances
are rejected. User text must be rendered as text by later rendering modules.

## Calendar and resource models

`calendar` exports date-only day indexing, day shifts, padded `timelineBounds`,
`createCalendar`, and `shiftTask`. Supply `today` explicitly. Period cells have
inclusive `start`/`end` dates, label, width and x position; calendar input `end`
is exclusive. Day/Week/Month/Quarter/Year retain existing widths and padding,
including the Year mode's two complete half-year cells per displayed year.
Viewport stretching is shared by both headers. Date positions interpolate
within the same period cells as the grid, including unequal month lengths;
inverse positions and drag deltas use calendar days, independent of timezone.
Resource and timeline renderers must share this one model. `maxPeriods` defaults
to 10,000 and bounds expansion; invalid geometry fails with `ContractError`.

`resources` exports `decodeIntervals`, `createResourceSummaries` and
`formatResourceValue`. Decoding ordered, inclusive, nonoverlapping intervals
preserves zero and missing-day distinctions. The default expansion limit is
25 years of entries; hosts can supply an explicit finite limit. A summary
instance owns its caches and indexes; supply validated immutable daily maps,
replace a changed map rather than mutating it, and call `clear` when disposing
the view. No cache is shared across instances. Period results are frozen.

Summaries distinguish minimum/maximum effective capacity, peak demand, maximum
positive daily excess, and minimum nonnegative availability. A missing override
uses normal capacity; zero remains zero and fully overridden periods never add
normal capacity artificially. Pass each demand scope independently with the
same effective capacity. FTE labels retain one decimal below 100 and whole
numbers from 100. Python-derived integration tests compare the browser results
against the existing domain's effective capacity and overallocation functions.

## Instance data and loading

`createPlanningStore(snapshot)` owns a frozen copy and private collection
indexes. `read()` returns frozen data/view values; `lookup(collection, id)`
returns one immutable record. `update(message)` validates changed input and
reconciled relationships before atomically publishing. Unchanged records and
daily series retain identity, so task patches do not reclone the resource grid.
`setView(patch)` handles scroll position, mode, expansion, filters, selection,
editor draft and pending preview/request. `subscribe(listener)` returns an
unsubscribe function. `destroy()` is idempotent and releases indexes/listeners.

Same-scope snapshots and patches retain applicable interaction state. A new
scope or explicit reset clears it. A deleted draft target is invalidated with a
safe explanation. Draft/selection targets use `{kind: 'tasks', id: 'task-id'}`
(or projects/dependencies/resources/overlays). Rejected correlated responses
clear preview/pending state and retain the editor; accepted responses close it.
Responses with an obsolete request ID, patches for another scope, and revision
changes without the current `baseRevision` are ignored. For an authoritative
revision change, send a snapshot or a patch with `baseRevision` matching the
current revision. Updated capabilities take effect in the published snapshot.

Patches upsert records and support `removeTaskIds`, `removeDependencyIds`,
`removeResourceIds`, and `evictProjectIds` in addition to the contract fields.
Project replacement removes its old tasks and owned dependency records before
adding the delivered bundle; project removal also drops its overlays. Eviction
keeps project headers/task counts but removes hydrated task/dependency records.

`createLoadingController({store, load, onError, batchSize, maxProjects})` owns
one cancellable request at a time. Call `request(visibleIds, overscanIds)` with
the latest window; priority is visible first. Requests are coalesced through a
60-ms scheduler, with injectable schedule/cancel functions for host integration.
Only known projects are requested; desired and retained working sets are bounded.
Defaults are 25 projects per batch and 100 retained projects. Limits must be
finite positive integers and batch size cannot exceed retention.

The async provider receives `{projectIds,scope,revision,requestId,signal}` and
returns a versioned patch for exactly the requested project IDs. Fully loaded
snapshots default to all supplied projects loaded; lazy hosts explicitly supply
`loadedProjectIds: []`. Scope/revision changes abort and invalidate old reads;
the renderer requests its new window afterwards. Failures retain valid rows,
emit a safe error, and wait for explicit `retry()`. `status()` exposes pending,
failed, queued and disposed values. `destroy()` cancels timers/reads, detaches
its observer, and prevents late results/errors from reaching the store/host.

## Workspace lifecycle

```js
import {mountPlanningView} from './src/index.js';
const display = mountPlanningView(document.querySelector('#planning'), {
  snapshot, today: '2026-01-01', mode: 'Quarter', showResources: true,
  onHeight: pixels => resizeEmbeddingFrame(pixels),
});
display.update({...snapshot, revision: 'next'});
display.destroy();
```

Serve the source tree over HTTP so native modules and the adjacent scoped CSS
load from the same package. The host must provide a nonzero available width.
The display retains other host children and removes only its own subtree.
The two panels share their horizontal scroll, scale, header geometry and frozen
column width, while vertical scroll stays independent. The splitter supports
pointer capture and Left/Right keys. Resource data is optional and its absence
reserves no grid space. Names/labels are written as text, never executable HTML.
Theme variables such as `--planning-primary`, `--planning-background`, and
`--planning-text` can be set on the host. All CSS selectors are scoped.

`update` returns whether an applicable message was accepted, throws a safe
`ContractError` for malformed input, and returns false after disposal.
`destroy` is idempotent: listeners, pointer capture, observers, frames, timers,
reads, state indexes and owned DOM are released. It never resets another
instance. Hosts should destroy before removing their host element. Distinct
instances can use the same data IDs. No renderer maps or document globals are
part of the public API. Exceptions thrown by host callbacks propagate; an
initial callback failure releases the partly mounted display before throwing.

## Timeline and comparison rows

Project headers group tasks by `projectId`; expanding a header reveals its own
date-sorted tasks. Header sort buttons cycle ascending, descending, original
project order. Task order uses date then natural opaque-ID order; IDs themselves
are preserved. `grouped: false` shows task rows directly. Delivered project
`start`/`end` summaries are authoritative; absent summaries use delivered task
extrema. Optional `taskCount` is a nonnegative safe integer and keeps placeholder
rows sized while a host loader supplies an expanded project.

Pair comparison tasks using `stableId` within each project. A missing stable ID
uses that record's opaque `id`. Give current and overlay records distinct `id`
values when they represent separately editable entities, but the same stable ID
when they should share a row. Stable identities must be unique within each
project and each supplied task collection. Names never determine pairing.
Unpaired comparison records create overlay-only rows. Current, alternative and
baseline bars retain separate target identities/lanes; baseline lines remain
display-only. Comparison dependencies use the overlay task IDs, documented with
the dependency module. Inclusive date widths and equal-date milestone diamonds
use the shared calendar. Delivered progress/violation flags style the bar.

Virtual canvases retain total scroll height while mounting only viewport rows
plus 15 rows of overscan per side. Horizontal scrolling reuses existing bar DOM
and calendar headers. Visible project IDs precede overscan in injected lazy
reads; disposal aborts those reads. No row-level inline handlers are generated.

## Dependencies and diagnostics

```js
const dependency = {
  id: 'build-after-design', type: 'FS', lagDays: 2,
  predecessor: {kind: 'task', id: 'design', projectId: 'alpha'},
  successor: {kind: 'task', id: 'build'},
  violated: true, evaluable: true, external: false,
  diagnostics: ['Build starts before the delivered constraint allows.'],
};
```

FS/SS/FF/SF determine predecessor/successor start or finish anchors. Lag and
diagnostic status are delivered metadata; links do not move dates or calculate
authoritative constraints. Optional `diagnostics` entries are text or objects
with a text `message`. Project endpoints use `{kind:'project', id:'alpha'}`.
Overlay dependency endpoints use their overlay's task IDs; delivered current
tasks remain available for external references. Stable pairing determines rows
without rewriting endpoint identities. A collapsed task uses its known project
summary anchor. For undelivered tasks, optional `projectId` enables that fallback
only when the project is collapsed. Otherwise available ends show a short stub.

An unavailable endpoint uses `{kind:'unavailable'}`. Inspection exposes no name,
ID or dates for it. A project fallback does not manufacture hidden task names
or dates. No dependency interaction fetches endpoint metadata. Delivered
records sharing a path are bundled, and an accessible selector retains every
member's type, lag and diagnostic information. Click/context menu or Enter/Space
opens details; Escape or Close dismisses it. SVG clipping identifiers are unique
per instance. Paths crossing the virtual window remain eligible through a
row-interval index; distant unrelated links do not enter the render query.

## Editing, events and context actions

Pass `onEvent: event => handleIntention(event)` to receive selections, commands
and writes. Editing is opt-in through the toolbar. `editEnabled: true` opts in
on mount; a scope change/reset restores the default. The snapshot must also
grant `capabilities.edit: true`. Optional `editDates`, `editProgress`,
`editTasks`, and `editDependencies` flags can disable individual operations.
An entity/overlay with `editable: false` disables its edits. Baselines remain
read-only. When an alternative is displayed, current records are read-only and
permitted writes target its separate `overlayId`. These are UI hints; always
authorize against current server grants and revisions.

Enter/double-click opens a task editor; the context menu and dependency details
also open editors. The task editor includes name, dates, progress, description,
phase and incoming predecessor/type/lag records. Its predecessor choices are
delivered records. Dependency editors support both endpoints and all link
types. Draft fields survive same-scope patches. Removed targets invalidate
drafts explicitly. Escape closes the editor, Tab stays within it, and
Ctrl/Command+Enter submits. Date/progress handles use pointer capture; Escape,
revocation, scope/revision change, pointer cancellation and disposal stop a drag.

Date/progress events carry the requested fields at the top level; task and
dependency events carry a `values` object (so dependency `values.type: 'FS'`
cannot overwrite event `type: 'dependency'`). Every event retains opaque IDs,
scope, revision and a unique request ID. A pending write blocks duplicate
submits. Apply authoritative patches and then a correlated response:

```js
display.update({version:1, kind:'patch', scope, revision, tasks: savedTasks});
display.update({version:1, kind:'response', scope, revision,
  requestId: event.requestId, accepted:true});
// Or retain authoritative data and reject the preview/draft safely:
display.update({version:1, kind:'response', scope, revision,
  requestId: event.requestId, accepted:false, error:'The schedule changed.'});
```

Neither dragging nor submitting modifies business data locally. Rejection
restores authoritative bars, retains an editor's unsaved fields, and displays
safe host text. A rejected/thrown event sink releases pending state with a
generic message. Async failures after disposal are ignored. Single selections
are delayed briefly to distinguish double-click editing; they do not block
writes or require acknowledgements.

`contextActions` accepts copied JSON descriptors such as:

```js
[{id:'project-actions', label:'Project actions', targetKinds:['projects'],
  children:[{id:'export-csv', label:'Export CSV', capability:'export'}]}]
```

Use optional `targetKinds`, `lanes` (current/baseline/alternative), `capability`,
and `requiresEdit` restrictions. Up to eight submenu levels are accepted, with
unique nonempty IDs and no cycles/executable content. Arrow keys, Home/End,
Enter/Space, Escape and Shift+F10 provide keyboard operation. Every invocation
rechecks current capabilities; application dialogs, import/export, approval,
navigation and persistence belong in the host handler for `type:'command'`.
The core supplies no application commands implicitly.

Hover details use plain text and appear after 1,000 ms by default. Hosts may
set a finite `tooltipDelay` from 0 through 60,000 ms. Leaving, editing, updating
or disposing cancels the reveal. The Hover details checkbox restores native
titles when rich hover is disabled. Drag feedback appears immediately.

## Optional resource grid

```js
const resources = [{
  id:'engineering', name:'Engineering', capacity:10, definedCapacity:10,
  hasAssignments:true, usedBySelection:true,
  usage:{'2026-01-01':6, '2026-01-02':4},
  selectedUsage:{'2026-01-02':3}, assignedCapacity:{'2026-01-02':2},
  comparisonUsage:{total:{'2026-01-02':5}, selected:{'2026-01-02':4}},
}];
const hierarchy = [{id:'organization', name:'Organization', children:[
  {id:'engineering-node', resourceId:'engineering'},
]}];
// Include resources/hierarchy in the snapshot and configure the mount:
const resourceOptions = {hideUnused:true, onlyOverallocated:false,
  showTotal:true, showSelected:true, collapsed:false};
```

`capacity` is normal effective capacity; sparse `assignedCapacity` overrides it
per calendar day, including zeroes. Optional `definedCapacity` is the reference
for under/overassignment badges, defaulting to capacity. `hasAssignments:false`
uses unassigned display styling. These display hints do not change daily
capacity calculations. `usedBySelection:false` permits Hide unused filtering;
it defaults to visible for independent hosts without selection metadata.
Nonzero comparison selected demand also keeps a pool visible.

Hierarchy nodes are opaque group IDs, optional names, `children`, and resource
leaves using `resourceId`. Projection is iterative. Missing resource references
are omitted without fetching metadata. Absent hierarchy produces flat pool
nodes. Expanded pools show capacity, total and selected demand; collapsed pools
show total demand. Comparison rows appear when formatted period demand differs,
so sub-display-precision changes do not create duplicate rows. Group warnings
use any child's daily excess rather than offsetting it against another child's
unused capacity. The header warns on visible total/selected overallocation.

Mount options include `resourceUnit` (default FTE), `resourceOptions`, and a
finite `resourceMaxHeight` from 50 through 2,000 px (default 324). The two-tier
header stays fixed. Rows are 23.8 px with six-row overscan; columns render the
visible shared calendar plus two extra columns per side. Capacity/demand cells
expose separately computed minimum capacity, peak demand and maximum excess.
The shared today line and column-hover guide use the same geometry in both
panes. Frozen rows, scale, scrolling and resized columns stay aligned.

Resource controls change display scope; the host owns application filters.
Supply `resourceFilter:{resourceId, name, start, end, clearAction}` or a `groupId`
to show active filter indication. Dates are optional for a whole-pool/group
filter. `clearAction` names a supplied context action and adds its clear button;
a command still passes current action-capability checks. Patch with
`resourceFilter:null` to remove the indication.

A single click/Space emits `select` with target kind `resources` or `hierarchy`
and `context:{start,end,scope,periodLabel,resourceNode}` where available. IDs and
periods remain opaque/inclusive. Scope is assigned/total/selected or an
alternative-prefixed demand scope. Alternative demand rows do not emit current
allocation selections. Double-click/Enter on capacity/group/collapsed rows
toggles expansion and cancels pending single selection. Arrow keys/Home/End
navigate cells, scrolling the virtual window as needed. Context actions receive
the same period/scope. Same-scope updates preserve independent resource vertical
scroll; scope/reset clears it. Hiding/removing resources reserves no grid space,
and frame-height callbacks include the enabled controls and complete viewport.

## Streamlit transport

`./streamlit` exports `connectStreamlit(root)`, a separate bridge importing the
same core. It mounts from contract-v1 `snapshot` data and applies `messages`
patches/responses. `options` is JSON mount configuration, `lazy` selects queued
load events, and `ackRequestIds` acknowledges transport receipt. Identical
snapshots/updates are not reapplied on every rerun. Changing mount options
remounts; use data for retained-state label/capability updates.

The bridge pins its actual parent window/origin, owns a single delivery queue,
prioritizes unsent actions before reads, and waits for receipt acknowledgement
before advancing the single component-value channel. Correlated load patches
resolve only their provider request. Aborted reads, stale revisions and disposed
instances cannot deliver late results. Page disposal releases the bridge/core.
Finite `loading:{batchSize,maxProjects}` mount options default to 25/100.
Read failures retain valid data and expose an explicit Retry loading button.

`packages/streamlit-planning-view` contains the typed independent Python wrapper
and full-data/lazy-host examples. It requires Python 3.14 and Streamlit 1.63.x
or a later 1.x release, uses explicit keys, and validates/deduplicates returned
events without importing EPPM. Prepare distributions with
`python -m scripts.build_planning_assets` from the source repository; native
tests also prepare a temporary frontend directly from this one source.
