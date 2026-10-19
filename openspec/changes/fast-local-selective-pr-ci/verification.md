# Verification evidence

## Reopened rollout correction — 2026-10-19

The user approved the focused metadata-proof correction after the first hosted
rollout. PR #6 at `22d3965` passed full CI: 3,581 cases plus five subtests in
1,623.33s, 97.71% coverage, both JavaScript suites and assets; full job 29m15s.
SonarCloud passed. Main remains `d4a769f` and the approved protection is active.
Later metadata-only runs leave the native merge box listing required `tests`
as Expected even though the API retains the older passing check. The screenshot
and sanitized logs are in the original checkout's ignored `.local/fast-ci-pr6-*`.

Fast actual-symptom reproduction, executed before correction:

```bash
gh api repos/cboguet83/eppm_demo/pulls/6 --jq \
  'if .mergeable_state == "clean" then "PASS: native merge gate" else error("FAIL: native merge gate remains " + .mergeable_state) end'
```

Exit 1: `FAIL: native merge gate remains blocked`. Repeated API/UI observations
confirm the same symptom. The leading hypothesis is omission of `tests` by the
later metadata workflow; source-app/base mismatch is ruled out by read-back,
and the state persists beyond a transient mergeability cache refresh.

Reused this chat's clean attached worktree at
`/home/cb2/.codex/worktrees/performance-verification/eppm_demo`, switched only
that checkout to `codex/fast-local-selective-pr-ci`, and reopened the archive
without changing its prior evidence. The shared checkout's Gantt work is
untouched. Tasks 1.2, 4.4 and 5.2 track this approved extension separately;
prior completed tasks retain their commits and historical evidence below.

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

## Task 4.3 — authoritative prose validation

Verification identified that path suffixes alone did not enforce the design's
nonexecutable/prose boundary. Added a separate correction task/commit rather
than rewriting task 4.1. Both sides of the complete raw Git diff now validate
regular nonexecutable modes and plain UTF-8 blobs; executable/link/binary/shebang
or unavailable content evidence selects full acceptance.

`python -m pytest -q tests/test_pr_test_policy.py`: 51 passed in 0.39s, including
actual Git/CLI cases for ordinary prose, executable Markdown, shebang text,
NUL/non-UTF-8 blobs, symlinks, and deleted executable Markdown. This adds
document checks without adding a parser/library dependency or weakening any
existing full gate.

At this point task 4.2 was incomplete: automatic approval review rejected the
persistent main-protection write pending explicit approval of its exact payload,
specifically administrator enforcement and disabling force pushes/deletion. The
prepared JSON was reviewable and no remote settings had changed. Local acceptance
continued while approval was pending; the next section records its resolution.

## Task 4.2 — effective main protection

The user explicitly approved the exact protection payload after reviewing its
administrator enforcement and force-push/deletion restrictions. The first API
submission returned HTTP 422 because `contexts` and `checks` are alternative
input shapes; removing the redundant empty `contexts` field preserved every
approved rule. The corrected protection PUT and merge-method PATCH succeeded.

Read-back at 2026-10-19 12:26 UTC confirms required PRs, strict/up-to-date
GitHub Actions `tests` (app 15368), administrator enforcement, blocked force
pushes/deletion, and no linear-history requirement. Merge commits alone are
enabled; squash, rebase, and automatic merging are disabled. Required GitHub
reviews remain zero; explicit user approval of the concrete PR is still needed.

The legacy protection endpoint returns these enforced rules; the separate
ruleset endpoint remains `[]`. Existing successful `tests` history at
`1761338f5818a4e7c0a8842d4e83bed658e25e5d` confirms the required app/context
identity. See `main-protection-request.json`, `merge-methods-request.json`, and
`github-settings-evidence.json` for sanitized requests and before/after evidence.
Operator inspection and conservative rollback are documented in
`docs/implementation/pr-ci-operations.md`. No administrative token enters CI.

## Task 5.1 — integrated local acceptance

Environment: Python 3.14.7, the existing development/browser dependencies,
PostgreSQL 18.6 in isolated Compose project `eppm-fast-ci-tests`, two xdist
workers, migrated templates, and Playwright Chromium. The dedicated credentials
are ignored under `.local/`; the existing application database was not used.
The disposable application image was `eppm-demo:fast-ci-tests`, config digest
`sha256:9c93dda7538111a96a55367feb020d345e44546a15b61d25a7b6a9490dc160b8`.
The application's `eppm-demo:local` image tag was not changed.

Three sequential `python -m scripts.run_tests fast` runs, with service variables
absent and automatic pytest plugin loading disabled by the runner:

| Run | Passed | Pytest seconds | Wrapper wall seconds |
| --- | ---: | ---: | ---: |
| 1 | 717 | 2.46 | 3.058 |
| 2 | 717 | 2.29 | 2.801 |
| 3 | 717 | 2.28 | 2.799 |

Median: 2.29s pytest, 2.801s wall. This is partial feedback from 66 modules,
not full coverage. The initial 783-case candidate included four modules with
real CLI/Node subprocesses; their cases remain in the extended/full suite.
The documented targeted example passed 27 finance cases in 0.05s. Policy and
Compose matrices passed as recorded above and also ran in full acceptance.

The final local full command exited zero:

```bash
POSTGRES_TEST_CLIENT_CONTAINER=eppm-fast-ci-tests-postgres-1 \
EPPM_RUN_OIDC_E2E=1 \
EPPM_E2E_APP_IMAGE=eppm-demo:fast-ci-tests \
.venv/bin/python -m dotenv -f .local/fast-ci-tests.env run -- \
  .venv/bin/python -m scripts.run_tests full
```

| Required gate | Result |
| --- | --- |
| Canonical discovery and strict real PostgreSQL/OIDC/browser execution | 3,581 passed, five subtests passed; 1,078.54s (17m58s) |
| Application/subprocess statement coverage, threshold 95% | 97.7072%; 16,705 of 17,097 statements, 392 missing |
| Root JavaScript suite | 221 passed, zero failed/cancelled/skipped |
| Planning-view JavaScript suite | 117 passed, zero failed/cancelled/skipped |
| Generated browser assets | Verified |
| Required/conditional skips, worker crashes or restarts | None |
| Strict OpenSpec validation | Passed; intentional `skip_specs: true` accepted |
| Main protection and merge settings | Applied and read back; see task 4.2 |
| Current main | Fetched again; local/remote divergence 0/0 at `d4a769f` |

Full execution uses all existing tests plus 92 new cases, not the fast inventory.
No existing assertion/test was deleted or weakened. No application, package,
migration, dependency or application coverage configuration source changed from
main. Full collection, security/integrity, scheduling and recovery checks remain.

The accepted runtime/test/CI/build sources are those of `1f77db1`. A SHA-256
manifest of 852 tracked files was captured before execution and rechecked after
it, with zero mismatches. Combined source digest:
`ceb9a72a60a4d00a2302649dfd3d6cc6dad70d42c37368b282f75596f0c45ec9`.
Subsequent task 4.2, this acceptance task and archive only change evidence/docs
or remote settings. The full log, coverage export, source manifest and timing
JSON remain in ignored `.local/fast-ci-*` files; no credentials are committed.

Revised PostgreSQL developer examples now use a dedicated test project, separate
credentials/client container, and explicit partial `targeted` mode. Fixtures
migrate disposable databases, so the examples do not migrate the root test
database or touch an existing application volume. Final Docker inspection shows
the existing app/database healthy and the disposable browser deployment removed.

### Verification report: fast-local-selective-pr-ci

| Dimension | Status |
| --- | --- |
| Completeness | All eight tasks implemented and evidenced; task completion confirmed by OpenSpec after recording this acceptance. Spec coverage: not applicable (`skip_specs: true`). |
| Correctness | Spec requirement mapping/scenario coverage: not applicable to this tooling-only change. Plan outcomes verified through the runner/policy/Compose regressions, complete local execution and remote read-back above. |
| Coherence | All five design decisions followed. CLI argument-list execution, focused script boundaries, strict typing, existing pytest/Compose conventions and unchanged application behavior reviewed. |

Design-to-implementation evidence:

- Decision 1: `scripts/run_tests.py`, `scripts/test_inventory.py`,
  `scripts/fast_test_guard.py`, `tests/suites.json` and the 19 runner regressions
  enforce explicit partial selection, complete inventory and resource guards.
- Decision 2: `scripts/full_test_proof.py`, full-mode/config validation and the
  actual accepted command reconcile independent discovery with both workers;
  existing strict completion checks and the complete JS/asset gates remain.
- Decisions 3–4: `scripts/pr_test_policy.py`, the four-job workflow and 51 policy
  cases cover complete diffs, blob/mode checks, draft/readiness on the same SHA,
  later/base revisions, metadata/manual isolation, failure/cancellation/missing
  receipts and strict result aggregation. Actual GitHub protection matches it.
- Decision 5: optional pgAdmin overlay, scoped volume/service identity and
  isolated test port replacement are covered by five config cases and actual
  isolated PostgreSQL startup. Existing application services were preserved.

No critical issues, warnings or suggestions remain in this pre-archive review;
no applicable verification check was skipped. All applicable checks passed.
Ready for archive. Product specs are intentionally not applicable, not missing.

### Task-to-commit audit

| Task | Dedicated commit |
| --- | --- |
| 1.1 | `0efc23d` |
| 2.1 | `2af1b6c` |
| 3.1 | `dc861f9` |
| 3.2 | `053ab17` |
| 4.1 | `5151315` |
| 4.3 | `1f77db1` |
| 4.2 | `9374039` |
| 5.1 | Resolve the dedicated `complete task 5.1` subject with `git log main..HEAD --oneline`; a commit cannot contain its own hash. |

The staged/final diffs were inspected and whitespace checks passed. Unrelated
generated diagnostics under `docs/diagnostics/` remain untracked and preserved.
The archive has a separate lifecycle commit. No merge is authorized.

### Delivery checks after archive

Hosted full CI and the existing SonarCloud integration must still confirm the
final PR revision after publication; local success does not replace them. No
SonarCloud MCP was available for a separate local server analysis, and none is
claimed. A new failure requires resolution and fresh affected acceptance before
merge. Present the concrete PR and obtain explicit user approval before using
a merge commit into main. Automatic merging remains disabled.
