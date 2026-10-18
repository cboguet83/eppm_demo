# Planning view: host contract v1

The independent contracts module uses native ES modules and no runtime imports.
Run `node --test packages/planning-view/tests/*.test.js` from the repository root.
Mounting and rendering are introduced by subsequent extraction tasks.

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
