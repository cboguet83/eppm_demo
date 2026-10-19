# Tasks

Each numbered checkbox is one focused commit, including its tests, relevant
documentation, and completion marker. Include `fast-local-selective-pr-ci` and
the task ID in every task commit subject. Add follow-up corrections as new
tasks/commits rather than rewriting completed task history. Only planning is
authorized at creation; the remaining boxes require a subsequent apply request.

## 1. Planning

- [x] 1.1 Create the proposal, baseline, design, and task plan on
  `codex/fast-local-selective-pr-ci` from fetched current main, recording the
  user's readiness/full-coverage and remote-protection decisions. Verify with
  strict OpenSpec validation, complete planning status with specs explicitly
  skipped, internal-link checks, and a reviewed planning-only diff; record the
  planning check results in `verification.md` and commit this task separately.

## 2. Repair optional database tools startup

- [x] 2.1 Extract pgAdmin into an opt-in development Compose overlay, declare
  `pgadmin_data`, preserve PostgreSQL volume/ports and required private tools
  credentials, avoid global container-name collisions, and make the test overlay
  replace the development port with isolated 15432. Include config-only
  regressions for PostgreSQL/test/application combinations without pgAdmin
  variables, tools opt-in with/without dummy credentials, volume identity, and
  independent project names; verify those tests and isolated PostgreSQL startup.
  Update optional-tools startup/placeholder documentation in the same commit.
  Leave the running application database and existing credentials untouched.

## 3. Local feedback and full acceptance entry points

- [x] 3.1 Add the maintained, audited fast-suite inventory and
  `python -m scripts.run_tests fast` / `targeted <paths-or-nodeids...>` commands,
  with explicit partial-result summaries and a command-listing/dry-run mode.
  Include meaningful runner/inventory regressions for path validation, command
  failures, new/unclassified modules, service-requiring fast members, and new
  tests in existing modules. Verify fast execution with service variables
  absent and without invoking Docker/browser services, plus one explicit
  targeted invocation; document prerequisites, scope, and examples in this
  commit. Do not apply the 95% full-coverage gate to these partial modes.
- [x] 3.2 Add canonical `full` mode using complete repository discovery,
  existing strict two-worker/template pytest, unchanged application/subprocess
  coverage of at least 95%, both JavaScript suites, and asset consistency.
  Include subprocess/collection regressions that reject explicit/implicit
  selection, missing prerequisites, skips, worker failures, and incomplete proof,
  including a partial selection containing both required groups. Verify command
  parity, discovery of a newly added test, canonical/worker collection equality,
  and failure propagation; update full preparation/execution instructions in
  this commit. Preserve all existing integrity/security and scheduling checks.

## 4. Selective PR feedback with enforceable merge acceptance

- [x] 4.1 Implement the complete-diff policy helper and selective PR workflow
  from design decisions 3–4: audited prose exemption, fast draft feedback,
  automatic full checks for ready code revisions, forced full checks for policy
  changes/uncertain diffs, manual diagnostic isolation, obsolete-run cancellation,
  and stable `tests` aggregation. Add deterministic policy/subprocess/workflow
  regressions for mixed/unknown/renamed/deleted files and large diffs; readiness
  without a new SHA; draft conversion; base retargeting versus metadata-only
  edits; all expected job results including failure, skip, cancellation, and
  missing/stale proof; and separate manual/metadata check contexts. Verify that
  partial drafts cannot produce green merge acceptance and that policy failure
  cannot turn all-skipped jobs green. Preserve read-only test permissions,
  SonarCloud integration, all full gates and cleanup. Update README and
  `docs/development-workflow.md` to the agreed policy in this same commit.
- [x] 4.2 After local gate regressions pass, preview and apply the explicitly
  requested main protections: PR-based changes, required GitHub Actions `tests`
  context, up-to-date branches, and effective administrator enforcement; keep
  merge commits and disable squash/rebase/automatic merging without altering
  unrelated protections or creating an unusable owner review-count requirement.
  Read back effective rules/protection and merge settings, verify the required
  context against the existing workflow history, and commit sanitized settings
  evidence plus operator/rollback documentation. If permissions prevent the
  requested protection, leave this task incomplete and report the actual gap;
  do not claim that local instructions enforce GitHub merging.

- [x] 4.3 Close the verification finding in prose-only classification: validate
  authoritative Git modes and UTF-8/plain document content on both sides of
  the diff so executable/symlink/binary/shebang files cannot use a prose suffix
  to omit full acceptance. Include real-Git/CLI regressions and document the
  conservative fallback; verify those cases and commit this correction
  separately before task 5.1. This restores the existing design boundary,
  without changing the readiness policy or coverage gate.

## 5. Integrated acceptance

- [x] 5.1 On the final implementation revision, verify all plan outcomes and
  record actual commands/results in `verification.md`: repeat fast timings with
  environment/test counts, demonstrate the documented targeted command, run the
  policy/state/result regression matrix, validate all Compose combinations and
  effective remote settings, and run the complete strict PostgreSQL/OIDC/browser
  pytest suite with at least 95% unchanged application coverage plus both
  JavaScript suites and generated-asset check. Run strict OpenSpec validation
  and the verify-change skill, inspect the final diff and task-to-commit mapping,
  and document skips/limitations and revised developer examples. Keep acceptance
  incomplete if any required check fails; no seven-minute deadline or weakened
  gates. This task integrates already-tested/documented work from tasks 2–4.

## Workflow follow-up

- After every tracked task and required local acceptance check passes, archive
  this tooling-only change on the same feature branch; no product deltas need
  syncing. Inspect and commit the archive separately.
- Publish the branch and create/attach the PR to `main` after archive. Confirm
  real hosted full CI on the final PR revision, effective protection, and the
  existing SonarCloud result. Archive changes do not exempt a mixed code PR.
- Present the concrete PR and wait for the user's explicit approval before
  merging. Use a merge commit, preserving all task commits. Readiness, passing
  checks, planning approval, and apply authorization are not merge approval.
