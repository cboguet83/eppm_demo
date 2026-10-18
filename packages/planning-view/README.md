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
