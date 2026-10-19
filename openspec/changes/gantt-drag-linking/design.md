# Design

## Context

See proposal.md for motivation. This is a cross-module interaction and host-contract change, so a design is required.

Observed integration points:

- `packages/planning-view/src/timeline/render.js` builds virtualized task/project bars. Task bars already own start/end/progress handles; project bars expand rows. Milestones have distinct geometry.
- `workspace/interactions.js` delegates pointer/keyboard handling, captures pointers on date drags, and cancels stale drags. `workspace/actions.js` resolves fresh identities and correlates requests, but dependency editing currently resolves an existing dependency ID.
- `timeline/dependencies.js` and `dependency-render.js` already position FS/SS/FF/SF links and inspect individually bundled records. EPPM's `dependencyEditor:'successor'` routes editing to the successor task form or project panel.
- EPPM's `eppm-contract.js` converts existing dependency data but its event mapper has no direct dependency-creation route. `eppm-transport.js` owns host correlation; `planning_events.py` validates Python boundary events and `pages/planning.py` dispatches them.
- `PlanningService.add_dependency` appends a task dependency; `save_task_dependencies` replaces incoming links. `save_project_dependencies` already accepts explicit deltas with a source revision. Direct creation must avoid replacing a partially visible incoming-link set.
- ADRs 0025, 0028, and 0029 establish warning-only dependencies, live schedule edits, immutable saved content, and revision-checked alternative drafts. Existing tests include package contracts/actions/dependencies, `test_eppm_planning_adapter.cjs`, component/browser suites, and PostgreSQL dependency/scenario tests.

## Goals / Non-Goals

**Goals:** Reuse bar geometry, dependency rendering, instance lifetime, host request reconciliation, and existing Python authorization/persistence. Keep the independent package free of EPPM IDs and business policy.

**Non-Goals:** Introduce a scheduling engine, change date arithmetic or cycle policy, edit saved snapshots, or introduce new persistence. Direct arrow rewiring and new undo history are excluded. Off-screen endpoints remain reachable by ordinary scrolling; automatic edge scrolling is deferred.

## Decisions

### 1. Separate connectors and an explicit connection state

Add small start/finish controls outside bar resize targets, with a larger transparent hit area and localized accessible names. Reveal on hover/focus; keep eligible destinations discoverable throughout a connection. Milestones expose separately selectable sides despite equal dates. Use the existing calendar anchors, including inclusive finish geometry, for project/task endpoints.

Keep one instance-owned state: idle, armed, dragging, or awaiting-host. Store endpoint identities/kinds, edge, lane/overlay context, scope/revision, pointer identity, and preview coordinates rather than long-lived DOM references. A click without crossing the existing movement threshold arms click–move–click; releasing that first click does not cancel it. A held pointer moving beyond the threshold uses drag mode. Destination completion consumes the synthetic click, preventing duplicate submission, expansion, selection, or a date drag. The bar body and existing resize/progress handles keep their current behavior.

Pointer capture means the captured event target cannot identify the destination: hit-test current rendered connector controls using pointer coordinates within this instance, then resolve fresh endpoint data. Recompute preview anchors on scroll/scale/layout changes. Cancel if the source is virtualized out; ordinary scrolling can reveal destinations while the source remains rendered. Hidden, filtered, collapsed child rows, and unloaded endpoints are not fabricated as targets. Collapsed project summaries link to the project itself.

Alternatives considered: reusing resize handles makes intent ambiguous; HTML drag-and-drop adds a separate event model and weaker control over existing pointer capture. Use delegated pointer handling and existing lifetime cleanup instead.

### 2. Direction and eligibility are explicit

The first connector defines the predecessor. Concatenate predecessor and successor edges (S/F) to obtain SS, SF, FS, or FF. Screen position and date order do not change direction. Initial lag is always zero; pointer distance never implies lag.

Eligibility must be distinct from date-edit eligibility: a visible read-only predecessor can be valid for a project successor, while live task links retain their stricter predecessor authorization. Extend host-supplied endpoint hints as needed and recheck at completion; the server remains authoritative. Disallow self-links and existing prohibited project/own-task pairs. Preserve existing cycle and uniqueness rules. An exact already-delivered endpoint/type/zero-lag match opens inspection rather than emitting a second create; this is a UI duplicate-gesture guard, not a new graph uniqueness constraint.

In comparison, only an editable alternative can own the successor. The user confirmed the existing comparison resolution rules during implementation: within the successor's project, only that alternative's task connectors are eligible sources; for other projects, only current/live connectors are eligible. Another project's alternative connector must not create a link that would subsequently resolve to its current bar. Baseline connectors remain unavailable. A read-only predecessor reference is not edited. Capture the successor alternative's project, plan ID, and revision independently of the external current source. Links to specific external alternative versions require a different dependency model and remain outside this change.

### 3. Add an opt-in creation intention to the existing contract

Use the existing `dependency` event family with `operation:'create'`, `targetKind` and `targetId` naming the successor task/project, and `values` containing predecessor, successor, type, and `lagDays:0`. Capture successor context, overlay/lane, scope, revision, and unique request ID. No persisted dependency ID is invented. Extend contract validation and action-controller creation checks rather than overloading the existing edit-by-dependency-ID path.

Add `capabilities.createDependencies`, disabled when omitted, and document this as an additive version-1 extension with synchronized package versions/manifests. EPPM explicitly enables it only when its bridge supports the operation. Existing hosts continue rendering/editing dependencies without receiving a new operation. Validate malformed endpoints, invalid types, successor/target disagreement, and inconsistent overlay context before request delivery.

Alternative considered: submitting the successor's whole task form would resend unrelated fields and could erase links that were not delivered. A focused append intention makes the change explicit.

### 4. Append through authoritative application operations

The EPPM mapper translates the create intention into a dedicated validated boundary action. Extend `planning_events.py`, planning dispatch, transport acknowledgment, and scenario routing coherently. For live task successors, wrap/reuse `PlanningService.add_dependency` in a focused transactional operation that rechecks the applicable planning source/revision and endpoint permissions before appending. Do not infer concurrency protection merely from a client scope token. For project successors, obtain/recheck the existing panel source revision and submit one explicit upsert with no deletions; a background read is allowed without opening a form. If a required source is stale, reject and refresh rather than retry against a new source silently.

For alternative successors, append to the authoritative server draft's incoming-link collection using its existing plan revision checks and preserve all other task/project dependencies, including protected references. Return the updated alternative through the established draft response flow. Immediate creation updates the draft; saving/publishing a plan remains the existing explicit workflow.

Use existing serializable transactions, owner guards, and endpoint authorization. Request IDs pass through the established nonce/rerun deduplication. Tests must prove one mutation per accepted request through both bridge delivery and reruns. No automatic retries of an uncertain write. Reuse existing uniqueness behavior rather than adding a database constraint.

### 5. Immediate submission with pending feedback and later editing

Completion emits one request immediately. Keep a visually distinct pending arrow and short accessible status until an authoritative patch/response supplies persisted identity. Prevent another conflicting submission while the existing request is pending. Rejection removes pending visuals, reports a safe error, and leaves the last valid schedule and unrelated draft intact. A revision/scope change clears obsolete previews and late responses follow the existing stale-result rules.

Accepted dependencies use the existing renderer/inspector and successor editor route. Verify the newly created record remains individually selectable even when its path is bundled. Type and signed lag editing continues through the current task or project dependency editor, not a second creation dialog. Dates never change from linking; warnings refresh through existing evaluation.

### 6. Accessibility and bounded ownership

Connector controls support focus and Enter/Space to arm/complete, Escape to cancel, and status announcements. Keep focus on usable controls after completion or rejection. Localize new labels through host labels/EPPM catalogs. Suppress delayed tooltips during a connection so they do not obscure targets. Dispose listeners, capture, preview SVG, and state through the existing instance lifetime.

Render connector DOM only with virtualized bars and one preview layer. Target discovery must not scan every task, hydrate unrelated projects, or change the 25-project batch/100-project retained limits. Tests cover two instances, scrolling, scale changes, narrow bars, milestones, and disposal.

## Risks / Trade-offs

- Edge controls compete for space on short bars → Separate visible dots and hit areas; verify zoomed-out and milestone geometry in a browser.
- Task/project authorization differs → Pair-aware UI hints plus existing server checks; test visible read-only predecessors explicitly.
- Pointer capture, reruns, and synthetic clicks can duplicate writes → One interaction owner, correlated request IDs, click suppression, and browser/adapter regression tests.
- Partial dependency data could erase protected links → Append/delta operations only; assert preservation in real PostgreSQL tests.
- Alternative predecessor resolution can be confusing → Preserve stable endpoint and successor revision context; test cross-project/current/alternative references using the existing resolver.

## Migration Plan

No database migration is planned. Implement and test the opt-in browser contract before enabling it in EPPM; regenerate distributed assets with `python -m scripts.build_planning_assets` and validate package consistency. Document the event extension and interaction in the embedding guide. Rollback disables EPPM's creation capability and reverts UI/bridge code together; existing persisted dependencies remain compatible and editable.

Final acceptance follows `docs/development-workflow.md`: strict OpenSpec validation, verify-change review, complete strict pytest acceptance with at least 95% application coverage, both JavaScript suites, real isolated PostgreSQL/authenticated browser execution, and asset consistency. A successful planning validation is not implementation acceptance.
