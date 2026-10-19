# Verification evidence

## Planning only — 2026-10-19

Status: task 1.1 complete; all six implementation/acceptance tasks remain open.
The proposal, baseline, design, and tasks are ready for review. No runner, test,
workflow, Compose, application, database, or GitHub setting was modified.

| Check | Observed result |
| --- | --- |
| `openspec list --json` and `openspec context --json` | Resolved this repository's existing OpenSpec root; no active change to duplicate |
| `git fetch origin main` and `git rev-list --left-right --count main...origin/main` | Fetched main `d4a769f12d92fc01d6fc49a1c4d16ca0be41ecee`; divergence `0 0` |
| Dedicated branch | Created `codex/fast-local-selective-pr-ci` from that main before authoring artifacts |
| GrillMe decisions | User chose automatic full CI on readiness/later ready revisions and inclusion of main protection setup |
| `openspec validate fast-local-selective-pr-ci --strict` | Passed; zero product deltas intentionally accepted via `skip_specs: true` |
| `openspec status --change fast-local-selective-pr-ci --json` | Planning complete: proposal/design/tasks done, specs skipped |
| Artifact/task audit | All internal artifact links resolve; seven unique task IDs; no product delta directory; implementation tasks unstarted |
| `git diff --cached --check` and staged diff review | Clean planning-only changes scoped to this change directory |

Read-only configuration probes confirmed the startup defects without starting
or changing services: missing pgAdmin variables fail PostgreSQL-only Compose
interpolation, the active tools profile with dummy values fails for an undefined
volume, and the resolved test overlay retains the development port alongside
15432. No secret-bearing rendered configuration was printed.

Read-only GitHub inspection returned no legacy main protection (404), no
effective branch rules (`[]`), and merge/squash/rebase all enabled. Automatic
merging is disabled and the repository is public. These are observations,
not newly applied settings. The exact future settings update/read-back belongs
to task 4.2 after apply authorization and local gate verification.

The large generated diagnostic reports remain untracked under
`docs/diagnostics/`; they are preserved and excluded from the planning commit.
The self-contained baseline records the relevant measured findings and their
revision limitations. Prior diagnostic test results are not acceptance for
the proposed implementation. Full integration/coverage/hosted checks will run
under the remaining tasks; no new hosted workflow was triggered for planning.

## Task-to-commit evidence

Task 1.1 has its dedicated planning commit with subject
`docs(fast-local-selective-pr-ci): complete task 1.1 planning`.
Resolve its hash with `git log main..HEAD --oneline`; do not embed the commit's
own hash inside its contents. Later apply work must record every subsequent
task's commit and actual validation evidence here.

## Task 2.1 — optional tools startup

- `python -m pytest -q tests/test_compose_configuration.py`: five passed in
  1.47s. Covers database/test/application combinations, required opt-in
  credentials, volume/port identities and project-scoped tool names.
- Isolated `eppm-fast-ci-tests` PostgreSQL startup passed with only the generated
  `.local/fast-ci-tests.env`, no pgAdmin values, and port 15432. The existing
  application services/database on 8501/5434 were not recreated or modified.
- pgAdmin image pinned to 9.18, verified against its official container docs;
  only config resolution was tested, without starting the optional tool.

## Task 3.1 — explicit partial feedback

- `python -m pytest -q tests/test_local_test_runner.py`: 19 passed in 0.83s.
  Tests cover complete inventory accounting, new module/case behavior, unsafe
  selections, propagation of child failure, and actual guarded subprocess
  attempts at database/network/container work in isolated pytest sessions.
- `python -m scripts.run_tests fast`: 717 passed in 2.43s with guarded resource
  creation, cleaned inherited credentials, no service prerequisites, no browser
  or container calls, and no coverage claim. 66 candidate modules remain fast;
  four modules with actual CLI/Node subprocesses are explicitly extended rather
  than exempted from resource guards. All their cases remain in full discovery.
- `python -m scripts.run_tests targeted tests/test_finance.py`: 27 passed in
  0.05s; dry-run labels partial scope and never executes commands.
- No test/assertion was removed. The fast inventory is maintained in
  `tests/suites.json`; full tests retain their existing discovery.

## Task 3.2 — canonical full command

- Full/local runner, existing strict serial/parallel gate, and actual repository
  scheduling regressions: 91 passed in 18.94s. Covers canonical/worker identity,
  a new discovered test, stale references, partial collections retaining both
  required groups, implicit/explicit selection, missing prerequisites, skips,
  crashes/completion failures, and narrowed discovery/coverage configuration.
- `python -m scripts.run_tests full --dry-run` confirms separate unfiltered
  canonical collection, strict two-worker/template execution with the unchanged
  application/subprocess coverage config and 95% threshold, both JS suites,
  and generated assets. A fresh exclusive temporary manifest is used in real
  runs; a stale prior file cannot become the canonical proof.
- README and the development workflow now document the shared full entry point.
  Real complete integration acceptance remains task 5.1, not this focused check.

## Task 4.1 — selective feedback and strict merge gate

- Policy/state/result/transport regressions: 44 passed in 0.14s. Includes real
  Git merge-parent and JSON job-transport checks, rename/deletion origins and
  350 added files, same-SHA readiness, draft conversion, changed base, missing
  results, all unsuccessful required results, and stale execution receipts.
- Combined Compose/local/full/policy regression pass before the final added
  real-Git transport case: 84 passed in 3.06s. The final policy module was rerun
  after its additions and passed all 44 cases.
- Workflow YAML parsed with the existing system PyYAML validator; checked
  events, exact dependency graph, read-only permissions and cancellation. No
  validator/project dependency was added. GitHub's context reference confirms
  needs outputs are available for job display names; manual/metadata contexts
  do not replace `tests`, and metadata has a separate concurrency key.
- README and delivery policy describe partial draft deferral, full ready-code
  acceptance, allowlisted prose, automatic later revision checks, manual
  diagnostics, cancellation, and source-bound gate evidence. SonarCloud
  integration and full-suite/coverage scope remain unchanged.

## Implementation acceptance

Pending a subsequent user request to apply. This change has not been archived,
published as a PR, or approved for merging. The planned final acceptance retains
full tests and at least 95% unchanged application coverage, effective remote
protection, one commit per task, and explicit approval of the concrete PR before
a merge commit into main.
