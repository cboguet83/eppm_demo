# Tasks

Each numbered checkbox is one focused commit containing its implementation, tests, documentation, and completion marker. Include `gantt-drag-linking` and the task ID in each commit subject. Complete dependent tasks in order; do not check a box until its checks pass. Implementation begins only after an explicit apply request.

## 1. Planning

- [x] 1.1 Capture the agreed interaction in proposal, design, and deltas for planning-visualization/planning-embedding on `codex/gantt-drag-linking` from current main; verify all required artifact paths exist, `openspec validate gantt-drag-linking --strict` passes, and the planning diff contains no implementation or unrelated changes. Commit as `docs(gantt-drag-linking): complete task 1.1 planning`.

Planning evidence (2026-10-19): fetched `origin/main`; local main and origin/main had zero divergence at `d4a769f`. OpenSpec reports proposal, specs, design, and tasks done; strict change validation passes. This planning contribution contains only the scaffold metadata and five Markdown artifacts. Runtime acceptance remains pending implementation.

## 2. Reusable creation contract

- [x] 2.1 Extend `packages/planning-view/src/contracts/` and `workspace/actions.js` with opt-in `createDependencies` and validated `dependency`/`operation:create` intentions targeting successor task/project identities; capture endpoint/overlay/revision context, reject malformed or mismatched endpoints, and reconcile pending acceptance/rejection. Add contract/action/store tests for opaque IDs, omitted capability, all types, fresh permission checks, one request, and stale responses; document the additive version-1 host extension. Verify the planning-view Node suite and affected pytest contract/model tests pass.

- [x] 2.2 Correct pending-draft preservation after a synchronous/asynchronous creation delivery failure so a subsequent ordinary editor save closes normally; add an action-controller regression and verify the complete package Node suite.

## 3. Direct chart interaction

- [x] 3.1 Add distinct start/finish connector controls to virtualized task/project/milestone bars, scoped styles, preview/highlighting, and delegated armed/dragging/completion state in `workspace/interactions.js`; preserve existing resize/move/progress/expand gestures. Add browser regressions for both pointer gestures across all four endpoint combinations and task/project pairings, empty-space cancellation, synthetic-click suppression, duplicate-delivered-link inspection, and date invariance. Include interaction guidance with this change; verify package tests and affected component/browser tests pass.
- [x] 3.2 Complete keyboard/focus behavior, localized endpoint/status labels, layout/scroll/scale handling, revocation/stale-source cancellation, tooltip suppression, and lifetime disposal. Add regressions for Enter/Space completion, Escape, pointer cancellation, source virtualization, narrow bars, milestones, collapsed projects, two instances, and disposal/remount; document visible-target behavior and update relevant label catalogs. Verify package and affected browser suites pass with bounded DOM/target discovery and unchanged hydration limits.

- [x] 3.3 Add a scoped arrowhead to the connection preview and restrict dependency status announcements to dependency requests; verify the keyboard preview regression and package suite, then regenerate/check assets.

- [x] 3.4 Use indexed endpoint resolution for pair checks and hide connectors when no authorized rendered pair exists; preserve read-only predecessors for editable project successors. Verify the new permissions browser regression, all direct gesture cases, the package suite, and regenerated assets.

## 4. EPPM authoritative append flow

- [x] 4.1 Add the validated Python creation boundary action and focused transactional live append service flow using existing task/project persistence, endpoint restrictions, and source/revision checks. Preserve inaccessible/unrelated links and date fields; keep cycles and uniqueness behavior unchanged. Add pytest boundary/service tests and real PostgreSQL regressions for all task/project pairings/types, stale sources, hidden/self/own-project endpoints, revoked permissions, read-only predecessor policy, rollback, and retained links. Document the service behavior and verify affected pytest/PostgreSQL suites pass.
- [x] 4.2 Map the creation event through EPPM contract/transport/dispatch and alternative draft routing; explicitly enable the capability only with the supported bridge. Preserve successor plan revision and cross-project predecessor identity, deduplicate reruns, return accepted dependency identity or safe errors, and retain the existing task/project dependency editor route for later type/lag edits. Add adapter tests and authenticated browser/PostgreSQL workflows for immediate live creation, alternative-only creation, bundled inspection, signed-lag/type edits, host rejection, and one mutation per request/rerun. Update EPPM interaction documentation and verify both JavaScript suites and affected pytest/integration/browser tests pass.

## 5. Distribution and acceptance

- [x] 5.1 Synchronize package versions/manifests and generated planning assets using `python -m scripts.build_planning_assets`; update independent host/Streamlit examples for explicit opt-in. Extend packaging/embedding regression coverage to prove omitted support remains compatible and installed artifacts create/acknowledge/edit dependencies using only packaged assets. Verify both JavaScript suites, generated-asset consistency, and affected packaging/plain-web/Streamlit tests pass.
- [ ] 5.2 Run final acceptance per `docs/development-workflow.md`: strict OpenSpec validation, the verify-change workflow against every scenario, and the canonical complete strict pytest command documented on this branch (the `scripts.run_tests` wrapper is absent) with isolated PostgreSQL and authenticated browser deployments, both JavaScript suites, asset consistency, and at least 95% application statement coverage. Record actual commands/results/coverage/skips, scenario evidence, final diff review, and task-to-commit mapping in `verification.md` using `git log main..HEAD --oneline`. Keep this task incomplete if a required check fails or cannot run.

## Workflow follow-up

- After every tracked task and required check passes, archive on the same branch through the archive skill, sync both capability deltas, and commit archive changes separately.
- Publish the feature branch and create/attach the PR to main with verification and task-commit evidence; require successful applicable CI on the final revision.
- Present the concrete PR and wait for explicit user approval before merging with a merge commit.
