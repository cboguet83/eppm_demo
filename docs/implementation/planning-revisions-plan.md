# Planning revisions, approval, baselines, and resource allocations

Status: Proposed implementation plan; no application changes implemented.

## 1. Objective and boundaries

Introduce one planning aggregate per project, with complete numbered revisions. Approve or reject a whole planning revision, including its tasks, dependencies, task tags, and both task-level and project-level resource allocations.

Allocation versioning is a moderate addition to the planning-revision work. Both allocation levels already share a model, distinguished by an optional task reference. They can use the same snapshot, concurrency, and approval transaction as tasks. The additional work is mainly allocation editing, revision-aware queries, capacity previews, and validation.

This plan replaces the earlier task-by-task approval and retained-task allocation-lock proposals. Editors may deliberately add, edit, reassign, or remove allocations in a New revision. Existing allocations are copied unchanged by default.

Project metadata, project status, budgets/actuals, resource pool definitions, employees, calendars, and resource capacity history are outside versioning. Capacity calculations use current resource data. No new framework, database technology, or architectural layer is required; retain the layered Python/Streamlit application and SQLite.

## 2. Model and lifecycle

- `Planning`: one per project, with independent `active_revision_id` and nullable `baseline_revision_id` references.
- `PlanningRevision`: planning ID, monotonic revision number, source revision ID, base active revision ID, status (`new`, `approved`, `rejected`), edit version, and creation/update/review metadata. Status applies only to the planning revision.
- Revision contents: full task snapshots, dependency edges, task-tag links, and allocation snapshots. Preserve stable logical task and assignment IDs across copied revisions. Snapshot keys include the planning revision ID; copying a plan does not create new logical tasks or assignments.
- Allocation snapshots contain logical assignment ID, resource pool ID, optional task ID, FTE quantity, explicit start/end dates, and notes. A null task ID means a project-level allocation. Resource pool records themselves are shared, not copied.
- Use complete snapshot copies for this proof of concept. Do not share mutable task or allocation rows between revisions. Add indexes for planning/revision lookup, task identity, and resource pool filtering.
- Enforce one New revision per planning and unique revision numbers. Revision-owned task references must resolve within that same planning revision. Active and baseline references must belong to their planning and reference Approved revisions.

The first edit of an approved plan creates a complete New revision and applies the edit atomically. Further edits update that shared working revision. No-op saves do not create a revision. Explicit revision creation is also available from the active plan or a selected historical revision. New projects start with no active revision; their first proposal starts empty.

New revisions are directly reviewable; this version adds no separate submission state. Approval freezes the revision and switches the active reference in the same transaction. Rejection freezes the proposal and leaves the active reference untouched. Editing rejected work creates another New revision with its contents copied. Editors may discard a New revision with an audit event; approved/rejected history cannot be discarded.

When revision 2 becomes active, revision 1 remains Approved. The UI derives Active or Superseded from the active reference. Official queries follow that reference, never all Approved rows. An approved empty plan is valid and has no active tasks; any explicitly retained project-level allocations remain part of it.

### Baselines

An approver can explicitly set any Approved revision as the comparison baseline. Approval never moves the baseline automatically. Record baseline selections and changes, including the previous reference, actor, and timestamp. Baseline designation is separate from review status and active selection. Historical assignment/date comparisons remain reproducible; capacity diagnostics against a baseline use current capacity data and must be labelled accordingly.

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

Key command contracts:

- `approve_planning(project_id, revision_id, expected_version)`
- `reject_planning(project_id, revision_id, expected_version, comment=None)`
- `set_planning_baseline(project_id, revision_id, expected_baseline_revision_id)`

Planning and allocation mutations carry revision context plus an expected version and return updated revision metadata. A first-edit command carries the source revision/version; the server creates the working revision and applies the change atomically. If another working revision has appeared, return a conflict rather than silently applying a stale edit to it.

Use `project.read` for authorized revision reads, `project.edit` for proposal changes, and `project.approve` for review and baseline selection. Reuse existing roles and scopes. Users with both roles may approve their own work. Business administration alone does not grant approval. Derive ownership from stored planning/task/assignment records, never submitted project identifiers alone.

Route every mutation path through revision-aware application operations: task editors, Gantt date/progress changes, dependency/tag editors, task and project allocation dialogs, resource-pool allocation screens, bulk allocation actions, imports, and schedule replacement. Maintenance writers must use explicit deployment paths without rewriting reviewed snapshots.

Approval reserves the writer, rechecks the session and permission scopes, verifies the expected revision version and unchanged base active reference, validates the complete candidate, writes the audit event, and switches the active reference atomically. Reject stale review screens; do not approve changes made after the reviewer loaded the proposal. Concurrency versions increment for allocation edits as well as task edits.

Extend database transaction guards and constraints to enforce revision ownership, editable state, reference integrity, and reviewed-history immutability across direct repository/service calls. Protect history from project/task/resource-pool deletion paths; reject destructive operations that would erase or invalidate retained snapshots. Keep safe error handling and transactional audit rollback.

Record revision creation, edits, discards, approval/rejection, and baseline changes with the existing audit infrastructure. Treat planning events as business changes for cache invalidation; retain permission-revision invalidation for actual access-policy changes.

## 5. Readers, UI, and rollout

Update planning bundles, task selectors, dependency queries, portfolio summaries, exports, allocation maps, and capacity readers to select one revision per project. Official defaults select active revisions; explicit proposal/history reads carry a revision identifier. Avoid duplicate task identities and multiplied allocation totals across snapshots.

Extend cache keys/invalidation to include selected revision IDs and edit versions, current capacity-input revisions, and existing authorization context. Proposal calculations must not populate official cache entries. On approval refresh affected project bounds, dependent schedules, portfolio summaries, and resource pools. Retain current scoped-cache race protections.

Provide Approved, Proposed, and History views. The Proposed view shows a complete editable Gantt and both allocation levels, clearly labelled as pending. Review compares tasks, dependencies, assignments, FTE, and dates against the active revision; allow comparison with the selected baseline. Approve/Reject actions operate once at planning level. Show active, baseline, and superseded designations independently of approval status.

Introduce an additive, versioned migration and update all affected adapters before enabling the workflow. Backfill one Approved revision per existing project, copying tasks, dependencies, tags, and both allocation levels while preserving logical identities and official totals. Mark these as migration baselines without inventing human approvals. Leave the formal baseline reference unset until an approver explicitly selects it.

Retire mutable legacy write paths after conversion; there must not be two independent authoritative copies of planning data. Rebuild affected derived caches. Add an ADR and update the permission inventory and operator/deployment documentation, including the replacement of destructive schedule behavior. Implementation must preserve unrelated in-progress repository changes.

## 6. Acceptance and validation

1. Ten approved tasks become a proposal with nine: eight unchanged and one edited. Approval activates exactly those nine; rejection retains the original ten.
2. Revision 1 remains Approved after revision 2 becomes active. Exactly one revision drives official results. Baseline selection remains unchanged through later approvals, with auditable rebaselining.
3. New revisions inherit every task and project allocation exactly. Draft edits leave active and historical allocations unchanged; both allocation levels can be added, modified, reassigned, or removed in the proposal.
4. Task removal removes only its task allocations from the proposal. Project allocations persist unless explicitly edited. Reductions and releases affect official demand only after approval.
5. Capacity previews replace the project's active contribution exactly once and use current capacity data. Cover inherited/explicit dates, project-only allocations, empty schedules, and shared pools across projects.
6. Verify scopes, cross-project references, allowed self-approval, read-only roles, revoked/disabled users, forged revision ownership, and direct-call attempts to bypass the workflow.
7. Exercise concurrent editors, edit-versus-approval races including allocation changes, stale baselines, failed copying, failed audit, and mid-transaction failures. Assert complete rollback and immutable history.
8. Test imports, full replacement, dependent-task removal, approved/history exports, UI comparison counts, proposal labels, and whole-plan review controls.
9. Validate clean installation and populated upgrade using real SQLite, including IDs, foreign keys, migration reruns, unchanged initial totals, and cache rebuilding. Run focused Python/Streamlit/JavaScript tests, then the full regression suite and required quality checks.

Delivery is one coherent feature. Internal implementation order is schema/domain, transactional services and security, selected-revision readers and capacity calculations, UI, then migration/regression validation; do not ship a partially versioned allocation path.
