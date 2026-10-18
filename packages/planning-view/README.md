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
