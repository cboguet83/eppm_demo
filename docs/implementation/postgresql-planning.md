# PostgreSQL task scheduling and dependencies

The Planning chart now uses the shared browser package through the
[EPPM planning integration](planning-component-integration.md). That guide records
the current browser/presentation C3 map; the service/store map below remains the
authoritative persistence ownership map.

## Project dependency management

Right-click a project label or summary bar and choose **Manage dependencies**.
The panel edits incoming links for the whole project, without step fields. Choose
another project, optionally one of its steps, FS/FF/SS/SF, and calendar-day lag
(negative values are supported). Save commits the explicit changes atomically;
Cancel discards the draft. A failed or stale save keeps the panel open. Reload
dependencies explicitly discards edits and reads current data.

Project bounds use the earliest/latest task dates. Missing dates mean a link
cannot yet be evaluated; links never adjust dates automatically. External arrows
use the existing **External Dependencies** toggle. Project warning badges,
diagnostics and dependency filters include project-owned links, including cyclic
graphs. Whole-project links survive schedule replacement, while links referencing
deleted steps are removed with those steps.

Migration `0030_project_dependencies.sql` adds a separate protected table and
extends source fingerprints. Existing task dependencies require no conversion.
Back up before migration. The current database was backed up to
`data/backups/postgresql/eppm-before-project-dependencies-migration-20260914-071055-832999-f61fc4abb9107b33.dump`
before applying it. See [ADR 0025](../decisions/0025-project-owned-dependencies.md).

Tests: `tests/test_project_dependency_rules.py`,
`tests/postgresql/test_project_dependencies.py`,
`tests/postgresql/test_project_dependency_browser.py`, and the Gantt JavaScript
regressions cover evaluation, access, explicit deltas, rollback, stale/concurrent
saves, cache refresh, cleanup and the reused panel.

The final feature run passed 48 PostgreSQL/UI/browser tests, 54 rule/layer/locale
checks and 20 JavaScript tests. The new Python dependency modules measured
98.63% statement coverage (the pure rules module: 100%). Live verification checked
schema version 30 and unchanged record hashes across 48 existing tables, including
1,000 projects, 7,336 tasks and 6,583 existing task dependencies. The live panel was
visually checked and its draft cancelled; no demonstration links were saved.

`PlanningService` now executes complete database callbacks through
`PostgresPlanningGateway`. The native adapter covers task reads and edits, CSV
imports/exports, schedule templates, dependencies, recursive project filters,
summary headers and batched task metadata. Application composition injects the
native gateway; the former SQLite callback bridge is archived outside runtime.

## Transactions and scheduling contracts

Task details and requested predecessors save together. Imports validate their
entire input before inserting, and template replacement validates external
references again within every attempt. Replacement removes the old schedule's
incoming/outgoing links, primary predecessor references, task tags and project/task
allocations before creating fresh task identities and resolving local step links.
A failure rolls back the complete operation, including deletions and earlier
inserts. Other projects' tasks and unrelated records survive.

The transaction runner retries complete serializable callbacks only for known
serialization/deadlock rollbacks. Task values, nested dependency submissions and
batch inputs are copied before callbacks. Concurrent replacements commit complete
templates with internally consistent fresh identities; concurrent date/progress
edits retain both independent fields. These are transaction guarantees, not
planning history, version tokens or stale-form protection.

Dates use native PostgreSQL parameters and return ISO strings independently of
DateStyle. Existing normalization, progress clamping, nullable legacy fields,
zero-duration milestones and the four dependency rules remain unchanged.
Migration `0014_dependency_lag_range.sql` widens the initial dependency lag column
to BIGINT to preserve the signed 64-bit range already accepted by templates.
Summary comparisons subtract dates instead of adding a potentially enormous lag.
Applied migrations remain unchanged.

## Scoped reads and protected references

All task predecessor reads use `eppm.visible_project_task`; the runtime role
cannot select the base table's unredacted predecessor column. Dependency RLS
checks both endpoints before labels, warning flags, counts or graph traversal.
Hidden projects contribute no metadata keys. Active accounts without business
read permission remain denied by the shared business runner.

Recursive project queries traverse task, whole-project and legacy primary links.
One recursive reference and UNION deduplication terminate cycles without banning
existing cyclic warning data. An inaccessible project cannot bridge two visible
parts of the graph. Selectors use bounded literal searches and exact IDs.

Task and dependency edits preserve old/new owner checks. Updating dates or
progress does not remove a hidden primary predecessor. Saving visible dependency
selections preserves hidden links; a caller cannot silently clear a hidden primary
reference. Deleting a task or replacing its schedule fails atomically when hidden
foreign-key references or uneditable owners prevent cleanup.

Task bundles batch tasks, dependencies, tags, pools, project names and referenced
whole-project bounds in one repeatable-read snapshot. Compact summary SQL
aggregates only visible sources, preserving task-endpoint precedence, signed lags,
empty projects, progress averages and FS/FF/SS/SF warnings without hydrating every
task. It does not reuse globally cached warnings.

## C3: components

```mermaid
flowchart LR
    Service[PlanningService] --> Port[PlanningGateway / PlanningStore]
    Service --> Rules[Task normalization and CSV/template rules]
    Gateway[PostgresPlanningGateway] -. implements .-> Port
    Gateway --> Runner[run_business / Database]
    Runner --> Actor[ActorBinding and authorization policy]
    Gateway --> Store[PostgresPlanningStore]
    Store --> Summaries[Scoped summary SQL]
    Store --> Tags[PostgresTagStore]
    Store --> Pools[PostgresResourcePoolStore]
    Store --> Data[(Tasks, dependencies and protected predecessor view)]
    Data --> Guards[RLS, old/new owners, native constraints and cleanup triggers]
```

## Validation and remaining work

Existing schedule, template, UI, projection and layer checks passed **146 tests
in 24.50 seconds**. The broader native planning, resource, business-security,
integrity, schema and foundation suite passed **194 tests in 65.91 seconds**.
All native scheduling adapter statements were exercised. Tests use real restricted
runtime connections and randomly named isolated PostgreSQL databases.

The final native suite passed **45 tests in 18.83 seconds**, including additional
external-template, nullable-field and hidden-link editing cases. The service and
native adapters cover **305/309 statements (98.71%)**; both native adapters have
100% statement coverage. This is subsystem evidence, not the final application
coverage or browser performance gate.

```powershell
.venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider tests/test_layered_planning.py tests/test_layered_planning_reads.py tests/test_layered_planning_ui.py tests/test_dependencies.py tests/test_schedule_export.py tests/test_planning_dependency_filters.py tests/test_project_template_workflows.py tests/test_planning_read_projections.py tests/test_layer_boundaries.py
.venv/Scripts/python.exe -m dotenv -f .local/postgresql.env run -- .venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider tests/postgresql/test_planning.py tests/postgresql/test_business_security.py tests/postgresql/test_integrity.py tests/postgresql/test_schema.py tests/postgresql/test_foundation.py tests/postgresql/test_resource_pools.py
```

Logs: `.local/postgresql-planning-legacy-expanded.log`,
`.local/postgresql-planning-native-expanded.log` and
`.local/postgresql-planning-native-final.log`. Coverage:
`.local/postgresql-planning-coverage.json`.

[Native derived caches](postgresql-derived-caches.md) now separate summary reads
from publication. The native gateway computes missing headers in repeatable read,
publishes against current source/security keys in a separate serializable
transaction, and reauthorizes all memory and database hits. Capacity inputs and
caches are also ported. Portfolio queries, native runtime/operator tooling,
project money forms, full regression coverage, the 50-user browser acceptance
runs and backup/restore/restart gates remain.

Pool allocation-grid tooltips show the minimum daily available FTE for the hovered period in green, or peak daily overallocation in red, directly below the pool title. They compare demand with capacity on matching days, including capacity exceptions, and respect total versus selected-project rows. Capacity cells use total demand. Group tooltips remain unchanged.

Planning filters begin at the top without a style-element spacer. Gantt rows are
41.4 px (10% smaller), including dependency geometry and centered task/milestone
bars. The Gantt viewport is capped at 495 px, with 5 px toolbar padding above
and below the controls. Resource-grid row heights are unchanged.

Planning has a persistent project-status multiselect defaulting to In Progress.
Clear all filters restores that default; clearing the status selection itself
includes all statuses. Status filtering is applied before the other project
filters, so Total allocation covers every accessible project in those statuses,
while Selected allocation additionally uses the selected project set. Capacity
is unchanged by project-status filtering. Cached pool payloads include the
status-qualified project set in their keys.

Resource-cell actions carry the inclusive period and Selected/Total row scope.
The allocation popup keeps only positive assignments overlapping that period;
Selected uses the server-side current project selection and Total uses the
status-qualified population. Date resolution still follows the assignment's
current fixed, inherited or offset/duration schedule. Row-level actions without
a period retain an unrestricted date range.

## Bounded dependency endpoint reads

Dependency metadata reads select minimal current owner-task fields under native
RLS, then resolve only their predecessor identities. Precomputing the logical
identity before the lateral lookup allows leakproof indexed comparisons through
RLS. Separate plain and copied task cases retain active-plan remapping and
hidden endpoint redaction. Migration 0067 adds a partial index on non-null stable
references; it changes no task records or prior migration bytes.

The real HTTP/query regression checks direct and copied predecessors, exact
result equivalence after 5,000 unrelated rows, a maximum 64-buffer increase and
no task/dependency scan exceeding two rows. Native planning and plan lifecycle
regressions retain transaction, authorization and active/baseline isolation checks.
