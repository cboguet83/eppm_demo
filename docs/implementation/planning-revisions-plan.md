# Task and resource plans: PostgreSQL implementation handoff for Codex

Status: Dedicated implementation plan; no application changes implemented.

Prerequisite: complete and validate the
[PostgreSQL migration](postgresql-migration-plan.md) first. This plan owns all
planning-specific PostgreSQL tables, columns, constraints, migrations, version
checks, and user workflows. It requires no dormant columns from that migration.

## Implementation instructions

Read `AGENTS.md`, the accepted PostgreSQL migration ADR, and the actual
post-migration application before implementation. Preserve the layered
Python 3.14/Streamlit architecture, Psycopg connection management, current access
policy, and unrelated work. This document replaces the earlier SQLite-targeted
planning-revisions specification while retaining its whole-plan business rules.

Create `codex/planning-revisions` from the accepted PostgreSQL baseline when
implementation begins, recording the starting commit. Use an isolated worktree
if other changes are in progress. If the branch already exists, inspect and
resume it without resetting unrelated work. Make focused intermediate commits
after relevant tests and diff review; do not merge, publish, or create a pull
request without a separate request.

Deliver the complete feature described here, including backend enforcement,
task and allocation editors, review/history screens, migration of existing
PostgreSQL planning data, and acceptance evidence. Do not stop at adding tables
or version columns. Use the Streamlit skill for implementation of UI changes.

## 1. Objective and boundaries

Introduce one planning aggregate per project, with complete numbered revisions. Approve or reject a whole planning revision, including its tasks, dependencies, task tags, and both task-level and project-level resource allocations.

Both allocation levels already share a model, distinguished by an optional task reference. They use the same snapshot, concurrency, and approval transaction as tasks. The implementation includes allocation editing, revision-aware queries, capacity previews, and validation.

This plan replaces the earlier task-by-task approval and retained-task allocation-lock proposals. Editors may deliberately add, edit, reassign, or remove allocations in a New revision. Existing allocations are copied unchanged by default.

Project metadata, project status, budgets/actuals, resource pool definitions, employees, calendars, and resource capacity history are outside planning versioning. Capacity calculations use current resource data. Retain the layered Python/Streamlit application and the PostgreSQL infrastructure delivered by the preceding migration; introduce no additional database, ORM, or service.

The task schedule and its resource demand form **one project plan**, reviewed and
approved together. Resource plan versioning covers both allocation levels; it
does not create a separate approval lifecycle or snapshot the shared resource
catalog. Stale-edit protection for project metadata or shared employee/pool
records is outside this feature.

## 2. Model and lifecycle

- `Planning`: one per project, with independent nullable `active_revision_id` and `baseline_revision_id` references, a `state_version`, and a `next_revision_number` allocator.
- `PlanningRevision`: planning ID, monotonic `revision_number`, source revision ID, base active revision ID, status (`new`, `approved`, `rejected`), `edit_version`, and creation/update/review metadata. Status applies only to the planning revision.
- Revision contents: full task snapshots, dependency edges, task-tag links, and allocation snapshots. Preserve stable logical task and assignment IDs across copied revisions. Snapshot keys include the planning revision ID; copying a plan does not create new logical tasks or assignments.
- Allocation snapshots contain logical assignment ID, resource pool ID, optional task ID, FTE quantity, explicit start/end dates, and notes. A null task ID means a project-level allocation. Resource pool records themselves are shared, not copied.
- Use complete snapshot copies for this proof of concept. Do not share mutable task or allocation rows between revisions. Add indexes for planning/revision lookup, task identity, and resource pool filtering.
- Enforce one New revision per planning and unique revision numbers. Revision-owned task references must resolve within that same planning revision. Active and baseline references must belong to their planning and reference Approved revisions.

The first edit of an approved plan creates a complete New revision and applies the edit atomically. Further edits update that shared working revision. No-op saves do not create a revision. Explicit revision creation is also available from the active plan or a selected historical revision. New projects start with no active revision; their first proposal starts empty.

`source_revision_id` identifies the contents being copied. Independently,
`base_active_revision_id` captures the planning's active reference at creation,
even when the source is a different historical revision. This permits proposing
historical contents without incorrectly treating that history as the active plan.

New revisions are directly reviewable; this version adds no separate submission state. Approval freezes the revision and switches the active reference in the same transaction. Rejection freezes the proposal and leaves the active reference untouched. Editing rejected work creates another New revision with its contents copied. Editors may discard a New revision with an audit event; approved/rejected history cannot be discarded.

When revision 2 becomes active, revision 1 remains Approved. The UI derives Active or Superseded from the active reference. Official queries follow that reference, never all Approved rows. An approved empty plan is valid and has no active tasks; any explicitly retained project-level allocations remain part of it.

### Baselines

An approver can explicitly set any Approved revision as the comparison baseline. Approval never moves the baseline automatically. Record baseline selections and changes, including the previous reference, actor, and timestamp. Baseline designation is separate from review status and active selection. Historical assignment/date comparisons remain reproducible; capacity diagnostics against a baseline use current capacity data and must be labelled accordingly.

### PostgreSQL schema and column ownership

Add the schema through new ordered migrations using the migration runner,
checksum ledger, and operator credentials established by the PostgreSQL work.
Do not rewrite previously applied migrations or add a placeholder version to
`project`.

| Storage | Required fields and purpose |
| --- | --- |
| `planning` | Identity-backed `BIGINT` primary key; unique project reference; nullable active/baseline revision references; positive `state_version BIGINT NOT NULL DEFAULT 1`; positive `next_revision_number BIGINT NOT NULL DEFAULT 1`. |
| `planning_revision` | Identity-backed `BIGINT` key; planning reference; positive revision number; nullable source/base-active revision references; checked status; positive `edit_version BIGINT NOT NULL DEFAULT 1`; creation/update/review timestamps and actor metadata. |
| Task and allocation identities | Stable logical IDs with immutable ownership by one planning. Preserve existing task and assignment IDs during backfill; allocate new identities for newly created objects. |
| Revision snapshots | Separate task, dependency, task-tag, and allocation contents keyed by revision and their logical identities. Task fields include dates/progress; allocations include pool, optional task, FTE, explicit dates, and notes. |

- Enforce `UNIQUE (planning_id, revision_number)` and a partial unique index on
  `planning_id WHERE status = 'new'`. Allocate revision numbers while locking
  the owning planning row; advance `next_revision_number` in the creation
  transaction. Never reuse numbers from discarded, committed proposals.
- Use composite foreign keys/unique constraints to enforce planning ownership
  and same-revision task references for internal dependencies, task tags, and
  task allocations. Project-level allocations have a null task reference.
- Active, baseline, source, and base-active revision references must belong to
  the same planning. Enforce active/baseline Approved status with deferred
  constraint triggers, alongside transaction guards; do not use a cross-table
  `CHECK` expression.
- Use PostgreSQL `DATE` for schedule dates and timezone-aware timestamps for
  audit/lifecycle metadata. Reuse the accepted allocation numeric representation
  and existing FTE validation rules; this feature does not change financial or
  resource arithmetic conventions.
- Add bounded-query indexes for planning/revision selection, snapshot task IDs,
  predecessor lookup, and resource pool demand. Do not index `edit_version`
  separately when the revision primary key already locates the row.
- All version fields are implemented and used by this feature. No per-task,
  per-allocation, or per-property concurrency columns are required.

### Three distinct kinds of version

- `revision_number` identifies a whole saved proposal/history snapshot, such as
  Revision 3. An ordinary save within that proposal does not create Revision 4.
- `planning_revision.edit_version` protects the complete contents and review
  status of that revision. A task or allocation edit advances the same token.
- `planning.state_version` protects changes to active/baseline pointers and the
  existence of a working revision. Advance it for creation, discard, approval,
  rejection, and baseline changes; ordinary content edits use `edit_version`.

Existing display/capacity cache counters are separate from all three. Shared
resource changes invalidate diagnostics without editing the proposal's contents.

## 3. Allocation and planning behavior

- Copy all task-level and project-level allocations unchanged when creating a revision, including logical identities, quantities, explicit dates, and notes. New allocations receive new logical identities.
- Allow editors to change allocations only in the New revision. Task-linked assignments must reference a task included in that revision; project-level assignments belong to its project.
- Removing a task removes its task allocations and internal dependency/tag links from the proposal only. Project-level allocations remain unless explicitly changed. Show all these consequences in the review comparison.
- Approval publishes task and allocation changes together. Allocation reductions/removals release demand only at approval; rejection leaves active demand unchanged. Historical snapshots never consume capacity.
- Resolve inherited allocation dates from the selected revision's task dates or project bounds, preserving existing date-fallback and quantity-validation rules.
- Official demand combines the active revisions of authorized projects. A proposal preview substitutes that project's proposed revision for its active revision; it does not add both. Include both allocation levels in each calculation.
- Preserve existing authorization filtering and staffing-data redaction in previews and official results. A planning editor does not gain access to shared employee/capacity details.
- Keep current over-allocation diagnostics rather than introducing a new hard capacity limit. Revalidate references and allocation validity at approval; recalculate capacity warnings using current data.
- Cross-project allocation transfers require separate proposed edits to each project's plan. This release does not introduce atomic multi-project approval or mutate another project's active plan implicitly.

Internal dependencies use task identities within the revision. External dependencies retain stable task/project identities and resolve against the other project's active plan for live calculations. Approval validates the complete proposed schedule. Block removing a task still referenced by another project's active plan until that other plan resolves the reference. Preserve existing cycle/constraint warning behavior and scope checks for changed cross-project relationships.

CSV append creates tasks within the proposal. Full template replacement replaces the proposed task schedule and its task-linked allocations, preserving proposed project-level allocations. Imported steps receive new logical task identities under the existing CSV contract; do not guess identity matches by names or step numbers. Preview must disclose removed tasks and allocations. Approved data and historical snapshots are untouched until whole-plan approval.

## 4. Services, interfaces, and enforcement

Extend the existing planning application boundary with typed planning/revision results and operations for creating revisions, reading selected contents, listing history, comparing revisions, approving, rejecting, and setting a baseline.

Key command contracts (all results are typed application DTOs):

- `read_planning(project_id, revision_id=None)` returns selected contents and revision/state metadata from one snapshot; the default selects the active revision.
- `list_planning_revisions(project_id, ...)` and `compare_planning_revisions(project_id, left_revision_id, right_revision_id)` use bounded, authorized projections.
- `create_planning_revision(project_id, source_revision_id, expected_source_version, expected_state_version)` copies the selected source; a new project's empty proposal uses null source context.
- `approve_planning(project_id, revision_id, expected_version, expected_state_version)`.
- `reject_planning(project_id, revision_id, expected_version, expected_state_version, comment=None)`.
- `discard_planning_revision(project_id, revision_id, expected_version, expected_state_version)`.
- `set_planning_baseline(project_id, revision_id, expected_state_version)`.

Planning and allocation mutations carry revision context plus an expected version and return updated revision metadata. A first-edit command also carries the source revision/version and expected planning state version; the server creates the working revision and applies the change atomically. If another working revision has appeared, return a conflict rather than silently applying a stale edit to it. Planning-state checks also detect pointer changes that were subsequently reversed, instead of relying only on the last selected baseline ID.

Use `project.read` for authorized revision reads, `project.edit` for proposal changes, and `project.approve` for review and baseline selection. Reuse existing roles and scopes. Users with both roles may approve their own work. Business administration alone does not grant approval. Derive ownership from stored planning/task/assignment records, never submitted project identifiers alone.

Route every mutation path through revision-aware application operations: task editors, Gantt date/progress changes, dependency/tag editors, task and project allocation dialogs, resource-pool allocation screens, bulk allocation actions, imports, and schedule replacement. Maintenance writers must use explicit deployment paths without rewriting reviewed snapshots.

Approval locks the affected PostgreSQL planning/revision rows, rechecks the session and permission scopes, verifies the expected edit/state versions and unchanged base active reference, validates the complete candidate, writes the audit event, and switches the active reference atomically. Reject stale review screens; do not approve changes made after the reviewer loaded the proposal. Concurrency versions increment for allocation edits as well as task edits.

Extend database transaction guards and constraints to enforce revision ownership, editable state, reference integrity, and reviewed-history immutability across direct repository/service calls. Protect history from project/task/resource-pool deletion paths; reject destructive operations that would erase or invalidate retained snapshots. Keep safe error handling and transactional audit rollback.

Record revision creation, edits, discards, approval/rejection, and baseline changes with the existing audit infrastructure. Treat planning events as business changes for cache invalidation; retain permission-revision invalidation for actual access-policy changes.

### Atomic stale-edit protection

Read each editor's displayed contents and version metadata in the same database
snapshot. Retain that context with the unsaved draft. A later cache refresh,
background request, or unrelated screen action must not replace its original
expected version.

Every effective mutation of a New revision, including child-only allocation or
tag changes, conditionally advances the revision's `edit_version` exactly once
per application command and changes its contents in the same transaction. The
condition checks the revision ID, ownership, `status = 'new'`, and the supplied
expected version. No-op saves check freshness but leave contents and versions
unchanged. Creation initializes the new proposal at version 1 with its complete
initial contents; subsequent effective edits advance that value.

Use one mutation gateway for all planning writers. Database guards must reject
unprotected child writes and changes to Approved/Rejected snapshots; operator
credentials must not provide an ordinary application bypass. Audit insertion,
version advancement, and child updates either all commit or all roll back.

Lock planning rows before revision rows; acquire multiple planning IDs in sorted
order when validating cross-project relationships. Reuse PostgreSQL transaction
isolation and bounded whole-operation retries from the preceding migration.
Retain the original expected tokens across a retry. An explicit stale-edit
conflict is not retryable and must never be changed into a save against the
newest version. Do not hold database locks while a human edits or reviews a form.

Introduce a dedicated application error `PlanningEditConflict`, distinct
from the existing cache-batch `PlanningRevisionChanged`. Reauthorize before
returning conflict details; inaccessible records receive the existing safe
denial. A conflict writes no business data or success audit and returns safe
context for explicitly reloading the latest authorized proposal. For any HTTP
mutation route, use a stable conflict code and HTTP 409; existing Streamlit
callbacks handle the typed error directly.

Approval/rejection conditionally advance the reviewed revision's edit version
and the planning state version in their transaction, then freeze the revision.
Discard and baseline changes use the same original-token discipline. Thus an
editor and approver using the same version cannot both succeed unnoticed.

### Conflict experience

Keep the user's unsaved values and original version after a rejected save. Show
that the proposal changed and nothing was saved. Provide **Review latest
changes** and **Discard my changes and reload**. Review displays original,
current authorized, and draft values without automatically submitting or
overwriting data. The user must explicitly reconcile their draft against the
latest contents before a new save uses its new token; no automatic merge or
force-save is included.

Apply the same behavior to inline Gantt edits and allocation dialogs. If a
proposal was approved, rejected, or discarded, do not silently redirect the edit
to a different revision. A new proposal must be an explicit, currently authorized
operation. If access was revoked, preserve security boundaries rather than
returning a comparison that discloses newly inaccessible data.

## 5. Readers, UI, and rollout

Update planning bundles, task selectors, dependency queries, portfolio summaries, exports, allocation maps, and capacity readers to select one revision per project. Official defaults select active revisions; explicit proposal/history reads carry a revision identifier. Avoid duplicate task identities and multiplied allocation totals across snapshots.

Extend cache keys/invalidation to include selected revision IDs and edit versions, current capacity-input revisions, and existing authorization context. Proposal calculations must not populate official cache entries. On approval refresh affected project bounds, dependent schedules, portfolio summaries, and resource pools. Retain current scoped-cache race protections.

Provide Approved, Proposed, and History views. The Proposed view shows a complete editable Gantt and both allocation levels, clearly labelled as pending. Review compares tasks, dependencies, assignments, FTE, and dates against the active revision; allow comparison with the selected baseline. Approve/Reject actions operate once at planning level. Show active, baseline, and superseded designations independently of approval status.

Expose project-level allocations in the selected plan even when it contains no
tasks. Resource-pool screens must label active demand versus proposed demand and
open edits in the owning project's New revision. Selecting another revision
must refresh both the task schedule and its allocation context. Historical
screens cannot expose editing actions. Preserve existing lazy task loading,
virtualization, fragment reruns, and bounded component payloads.

Introduce additive PostgreSQL migrations and update all affected adapters before enabling the workflow. Unlike the preceding fresh-start database migration, this feature must preserve planning data already present in PostgreSQL. Backfill one Approved revision per existing project, copying tasks, dependencies, tags, and both allocation levels while preserving logical identities and official totals. Mark these as migration-origin initial revisions without inventing human approvals. Leave the formal baseline reference unset until an approver explicitly selects it. Initialize revision/state versions to 1 and the next revision number to 2 for backfilled projects; future projects begin with no active revision and next revision number 1.

Retire mutable legacy write paths after conversion; there must not be two independent authoritative copies of planning data. Rebuild affected derived caches. Add an ADR and update the permission inventory and operator/deployment documentation, including the replacement of destructive schedule behavior. Implementation must preserve unrelated in-progress repository changes.

Perform the populated-data cutover with application writers stopped and a
verified PostgreSQL backup. Backfill and validate in a controlled migration
transaction before switching readers/writers. Verify task/allocation identities,
foreign keys, sequences, counts, dates, and official demand totals before
accepting the conversion. Do not automatically overwrite data on migration
reruns. After new revision history has been created, rollback uses a compatible
application revision and PostgreSQL recovery procedures, not a lossy collapse
back into unversioned rows.

## 6. Acceptance and validation

1. Ten approved tasks become a proposal with nine: eight unchanged and one edited. Approval activates exactly those nine; rejection retains the original ten.
2. Revision 1 remains Approved after revision 2 becomes active. Exactly one revision drives official results. Baseline selection remains unchanged through later approvals, with auditable rebaselining.
3. New revisions inherit every task and project allocation exactly. Draft edits leave active and historical allocations unchanged; both allocation levels can be added, modified, reassigned, or removed in the proposal.
4. Task removal removes only its task allocations from the proposal. Project allocations persist unless explicitly edited. Reductions and releases affect official demand only after approval.
5. Capacity previews replace the project's active contribution exactly once and use current capacity data. Cover inherited/explicit dates, project-only allocations, empty schedules, and shared pools across projects.
6. Verify scopes, cross-project references, allowed self-approval, read-only roles, revoked/disabled users, forged revision ownership, and direct-call attempts to bypass the workflow.
7. Exercise concurrent editors, edit-versus-approval races including allocation changes, stale baselines, failed copying, failed audit, and mid-transaction failures. Assert complete rollback and immutable history.
8. Test imports, full replacement, dependent-task removal, approved/history exports, UI comparison counts, proposal labels, and whole-plan review controls.
9. Validate clean installation and populated upgrade using real PostgreSQL, including IDs, composite foreign keys, migration reruns, unchanged initial totals, and cache rebuilding. Run focused Python/Streamlit/JavaScript tests, then the full regression suite and required quality checks.

Additional concurrency and schema acceptance:

10. Two editors load one proposal at version 12. A task edit succeeds and returns 13; an allocation edit using 12 fails without changing data. After explicit reconciliation, the allocation can be saved using 13. Repeat for two different tasks to verify deliberate whole-plan protection; independent project plans do not conflict solely because another plan changed.
11. Cover every mutation route: Gantt dates/progress, dialogs, dependency/tag changes, task/project allocation editors, resource-pool screens, imports, full schedule replacement, bulk actions, and review commands. Child-only changes must advance the shared token; no-op saves must not.
12. Race two first edits, proposal creation versus discard/recreation, approval versus allocation editing, and baseline changes including a change-away-and-back. Reject stale tokens without silently attaching a command to another proposal or reusing a discarded revision number.
13. Verify original draft tokens survive background refresh and database retries. Conflicts retain unsaved values; explicit reload/reconciliation is required before resubmission. Revoked users receive no newly inaccessible comparison data.
14. Use restricted PostgreSQL runtime credentials to test direct repository/SQL attempts to mutate closed history, use another plan's task in an allocation, delete retained references, or bypass the guarded mutation path. No check may rely solely on UI disabling.
15. Verify one New revision per plan, positive version counters, same-plan active/baseline references, status constraints, sequence advancement after backfill, all-or-nothing copying, audit rollback, and backup restoration.
16. Preserve the PostgreSQL baseline's routine responsiveness target on the documented 50-user workload. Measure new copy, compare, history, and approval operations separately on representative large plans; keep all-project readers bounded and never load every historical revision into the browser. Record p50/p95, database/pool waits, payload sizes, and remaining limitations.

Use real PostgreSQL for constraints, row security, transactions, locking,
migrations, and repository tests; use separate setup and restricted runtime
credentials. Run the existing Python/Streamlit and JavaScript regression suites,
authenticated browser workflows, and at least 95% statement coverage. Include
tests proving both task and allocation history remain immutable after later
revisions are approved.

Delivery is one coherent feature. Internal implementation order is schema/domain, transactional services and security, selected-revision readers and capacity calculations, UI, then migration/regression validation; do not ship a partially versioned allocation path.

## 7. Milestones, commits, and completion

| Milestone | Deliverable before committing |
| --- | --- |
| 1. Baseline and decisions | Accepted PostgreSQL starting commit, current tests/performance, writer/read-path inventory, and an ADR for whole-plan revisions and concurrency boundaries. |
| 2. PostgreSQL model | Planning/revision schema, version columns, stable identities, complete snapshot storage, constraints, and real-database tests. Keep the existing workflow active until cutover. |
| 3. Lifecycle and guarded writes | Copy/create/edit/discard, approval/rejection/baselines, original-token checks, audit/security enforcement, and concurrency regressions for tasks and both allocation levels. |
| 4. Selected-revision reads | Active/proposal/history projections, resource demand substitution, cross-project dependency validation, scoped caches, exports, and bounded queries. |
| 5. Complete user workflows | Revision navigation, task/allocation editors, review/comparison, approval/baseline controls, and draft-preserving conflict handling across every editing route. |
| 6. Data conversion and acceptance | Populated PostgreSQL backfill, clean install, writer cutover, obsolete-path retirement, regression/browser/load tests, and backup/restore evidence. |
| 7. Documentation and handoff | Accurate C4 diagrams, permission matrix, deployment/recovery instructions, milestone commits, test results, benchmark results, and remaining limitations. |

Split large milestones into focused intermediate commits with useful checks and
diff review. Record evidence alongside the implementation; do not claim the
feature complete while allocations, alternate edit routes, or closed-history
protections remain unversioned.

Completion requires working PostgreSQL schema **and** the application/UI paths
that use it. The general PostgreSQL migration document must remain free of
preparatory planning-version columns and must not take on this feature's scope.

## References

- [PostgreSQL constraints and composite references](https://www.postgresql.org/docs/18/ddl-constraints.html)
- [PostgreSQL partial unique indexes](https://www.postgresql.org/docs/18/indexes-partial.html)
- [PostgreSQL transaction retry requirements](https://www.postgresql.org/docs/18/mvcc-serialization-failure-handling.html)
