# Design

## Context

See proposal.md for motivation and scope. The repository already uses Python 3.14, a layered Streamlit/PostgreSQL application, pytest, browser deployments, and Node component tests. The existing `.github/workflows/tests.yml` provisions an isolated PostgreSQL service and application image but exposes only `workflow_dispatch`.

`tests/postgresql/conftest.py` skips real database tests when test URLs or PostgreSQL clients are absent. `tests/test_oidc_browser_e2e.py` skips its module unless `EPPM_RUN_OIDC_E2E=1`. These are useful local defaults but insufficient for a full verification claim. No root `tests/conftest.py` currently exists. OpenSpec has an initial configuration and generated local skills, with no durable specs.

## Goals / Non-Goals

**Goals:** Give future agents one authoritative delivery procedure; preserve task history; make the existing full-suite CI automatic and resistant to missing critical test execution.

**Non-Goals:** Redesign application architecture, upgrade dependencies, configure remote administrative policy without authorization, or turn every local partial test run into a full deployment.

## Decisions

### 1. Separate concise agent instructions from the contributor procedure

Update AGENTS.md with the standing branch/commit/PR authorization and a mandatory pointer to `docs/development-workflow.md` for OpenSpec work. The guide owns the detailed lifecycle and verification commands; README links to it and corrects its manual-only CI statement. Use existing `docs/decisions/` if a future architectural decision warrants an ADR; this contributor convention does not need one.

In `openspec/config.yaml`, use supported artifact rules for task granularity, explicit validation, and scope; use operation guidance for applying and archiving. Branch selection precedes any planning writes and is governed by AGENTS.md because per-artifact rules alone cannot enforce that prerequisite. Keep generated skills unmodified so OpenSpec regeneration remains safe. Instructions guide agents; they are not a claim of GitHub enforcement.

Alternative: duplicate the procedure across all skills. Rejected because generated files drift and regeneration can remove edits.

### 2. One branch per change, one commit per numbered task

Use `codex/<change-name>` based on current main after checking for unrelated work. This setup starts on `codex/project-workflow-setup`; preserve the user's untracked initialization files until their dedicated bootstrap task. Commit the proposal as the planning task, then each implementation task with its tests and completion checkbox. Put the change name and task ID in each commit subject so history is auditable without embedding a commit's own hash in its contents.

Do not amend completed task commits to incorporate subsequent tasks or squash the PR. Follow-up corrections receive their own explicit task and commit. Planning and archive/evidence work are named tasks too. Group enough implementation and tests into each task that a task commit is coherent.

### 3. Automatic full CI, using the existing isolated infrastructure

Add an unfiltered `pull_request` trigger to the existing workflow and retain manual dispatch. Do not add path filters or draft exclusions: every PR must run the full suite. Keep read-only workflow permissions and use the PR event rather than `pull_request_target`; tests execute proposed code without production secrets. Keep the existing Python 3.14 setup, separate test roles, isolated PostgreSQL provisioning, Docker build, browser opt-in, 95% coverage command, and Node checks.

### 4. Opt-in strict pytest verification

Add `--require-full-suite` via focused pytest hooks in `tests/conftest.py`. Strict mode requires both test URLs, the OIDC opt-in, and actual collection of PostgreSQL and authenticated browser tests; missing prerequisites or missing groups fail clearly without displaying credential values. Any skipped test in these required groups, including setup skips, causes a failing session. Preserve ordinary local skip behavior when the option is absent. Do not fail unrelated intentional skips by default.

Use the option in CI and the documented full verification command. Cover strict-mode acceptance, missing prerequisites, missing groups, collection/setup/runtime skips, ordinary failure propagation, and unchanged local partial-run behavior with isolated pytester tests. Pytester's built-in plugin avoids a new testing dependency. These tests must not connect to real services; the full application suite continues using real isolated PostgreSQL and OIDC deployments.

Alternative: environment preflight alone. Rejected because nonempty variables cannot prove a critical suite ran. Alternative: ban every skip globally. Rejected because unrelated conditional tests need not invalidate the defined critical-suite gate.

### 5. Verify and archive before PR creation; require approval to merge

After implementation, run OpenSpec validation and the verify-change workflow against the artifacts, the full pytest command with coverage and strict mode, and Node checks. Record commands, outcomes, skipped tests, and task-to-commit evidence in `verification.md` inside the change. Any unavailable required gate leaves the change incomplete; partial validation is labeled accurately.

Only after successful verification, sync applicable product spec deltas and archive the change on the same branch. The approved tag-filter and helper-hardening repairs now have focused deltas to sync. Archive and PR operations belong in the plain workflow follow-up section, outside the tracked implementation checklist, so archive does not depend on its own completion. Give the archive and its evidence a separate lifecycle commit. Then publish the branch and create a PR targeting main, with validation evidence and task history in its description. New commits after verification require relevant revalidation; full PR CI must pass on the final PR revision, including archive changes.

Stop for the user's explicit approval of that PR before merging. Use a merge commit to preserve all task commits. A request to apply or create a PR is not merge approval. Document recommended GitHub settings: PR-required changes to main, required full-suite status check, merge commits enabled, and squash/rebase merge methods disabled. Inspect remote settings during delivery if accessible; report unverified or missing protection separately rather than claiming local documentation enforces it. Changing those settings is outside this implementation scope.

## Risks / Trade-offs

- The measured full local run took 47 minutes 47 seconds, exceeding the former 30-minute CI limit. Give the job 90 minutes for dependency installation, image build and all PostgreSQL/OIDC/browser checks, and verify the actual PR run without removing required gates.
- First PR introduces its own CI definition. Review the workflow diff and require a successful run on its final revision before merge approval.
- Local instructions cannot stop a privileged direct push or squash merge. Document remote protection requirements and accurately report enforcement status.
- Strict pytest hooks can accidentally mask failures or affect local runs. Regression-test exit status and opt-in isolation, and preserve existing failing exit codes.
- Full verification needs Docker, Chromium, database services, and installed dependencies. If unavailable, record the precise blocker and leave verification/archive tasks pending.

## Migration Plan

Verification exposed stale resource-tooltip assertions in two JavaScript test
files: the current application already displays one-decimal FTE, while tests
still expect whole values or two decimals. The user approved task 3.3 to align
those assertions and retain fractional values; integer kEUR display stays as-is.
This is a test-only correction with its own commit, not a UI behavior change.

The user also approved focused baseline Python repairs after independent
reproduction: dashboard selectors must find the intended expander rather than
assume it is first; the bounded-key migration regression must isolate migration
0024 from later feature migrations that deliberately invalidate cache tokens;
planning harnesses must enter the existing edit mode before allowed mutation
events; employee-function fixtures and shared-filter selectors must follow
current contracts. Preserve all non-disclosure, revocation, ledger, and source
isolation assertions. CSV import tests follow the current named, inactive revision
contract rather than expecting destructive replacement of the active schedule.

The user approved two application repairs: include free-text tags through a
scoped left join alongside dictionary labels, and add migration 0065 setting the
explicit trusted-before-temporary search path on the WBS and two hierarchy-cycle
helpers identified by the unchanged security assertion. Preserve helper bodies,
prior migration bytes/checksums, allocation constraints, and hierarchy rules.
Nested EXPLAIN plans also confirmed that selected planning-cache reads scan the
whole portfolio through current-plan views. Migration 0066 keeps the original bulk
query and all authorization/token logic, using correlated lookups
only for explicitly selected planning entities. The private helper selects active,
non-deleted owner tasks before resolving their logical dependency endpoints,
matching the existing views without expanding unrelated rows. Preserve the existing 64-buffer
growth limit, use symmetric warm-up, and verify scoped/full token equivalence,
clean initialization and append-only upgrade safety.
The same view expansion affected dependency metadata reads under runtime RLS.
Select minimal owner-task fields from active non-deleted rows under their existing
policies, precompute the predecessor logical identity, and resolve the disjoint
plain/copy cases through indexed lateral lookups. Migration 0067 adds a partial
index on non-null stable references. Keep RLS, current-plan remapping and hidden
endpoint privacy; retain exact 64-buffer growth and two-row scan limits, including
copied predecessors. Verify index initialization/upgrade preserves records/ledger.
Task-source fingerprints also expanded all live task IDs through assignment-view
membership. Migration 0068 replaces the equivalent membership subquery with a
correlated indexed EXISTS lookup while preserving security_invoker, view grants,
local check option and NULL/deleted/inactive task semantics. Compare upgraded
membership and metadata, and retain the independent revision oracle and exact
64-buffer growth limit. No record rewrite or prior migration changes are needed.
Concurrent title saves also read global WBS facts unnecessarily, and the old
concurrency fixture cleared seeded WBS shares instead of submitting a title-only
form. Preserve the loaded shares in the workload and assert exact before/after
allocation equality. The native WBS store skips global reads and rewrites for
unchanged shares; an explicit empty replacement still clears existing shares
without consuming capacity. Master authorization, serializable isolation, changed
nonempty cap checks and cancelled-project reactivation checks remain unchanged.
Shared Clear filters must also advance the planning chart reset signal, in
addition to restoring In Progress and unrestricted scoped project/resource reads.
Capture these real behavior contracts in focused delta specs; the initial
tooling-only `skip_specs` exemption is superseded by the approved scope expansion.

Land bootstrap inputs, policy/configuration, strict verification with tests, and PR triggering in distinct task commits on this branch. Complete gates and archive in a final task commit, then create the PR. Existing local test commands remain available; the documented completion command gains strict mode. Roll back through a reviewed revert PR if needed, preserving task history and avoiding runtime/database changes.
