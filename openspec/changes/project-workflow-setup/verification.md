# Verification: project-workflow-setup

Branch: `codex/project-workflow-setup`. Baseline main:
`69fccbcd1574f6f0ab8904fc520a0f27a6f7bfed`.

## Acceptance status

The original required pre-archive checks passed, and the focused CI portability repairs are verified locally. Final updated PR CI is pending. The clean run completed **3,219 tests
and five subtests**, with **zero failures, errors or skips**, in **2,436.50s
(40m36s)**. Application statement coverage is **97.69%** (16,926 statements,
391 missing), above the unchanged 95% gate. All **10 JavaScript checks** pass.

| Dimension | Result |
| --- | --- |
| Completeness | 52/52 tasks; 12/12 requirements mapped |
| Correctness | All 19 scenarios mapped and covered by passing verification |
| Coherence | Design and repository patterns reviewed; one optional-import finding corrected; no open implementation findings |

The original five main specs remain synchronized. PR #1 full CI subsequently
reported two runner-specific fixture failures (3,217 passed, two failed, five
subtests passed; 97.68% coverage; 41m24s). The change was reopened for focused
repairs, verified and rearchived before the PR update. No merge is approved.

## Completeness

All 52 tracked tasks are complete in dedicated commits, including the runner portability and allocation-form follow-ups. The initial tooling-only exemption was superseded by
approved application repairs. Five readable capability deltas contain 12
requirements and 19 scenarios. None is intentionally skipped.

## Correctness: requirement and scenario mapping

| Capability and requirements | Implementation | Scenario evidence |
| --- | --- | --- |
| Shared tags include dictionary/free-text values; filters preserve authorization | `app/infrastructure/postgresql/dashboard_catalog.py` scoped left join; shared filter service | `test_shared_filter_tags.py::test_shared_filter_tags_include_both_sources_without_hidden_labels` exercises mixed sources, Any/All and hidden labels; `test_business_transaction_security.py` retains hidden payload/reset checks |
| Clearing shared filters resets planning | `project_filter_panel.py::clear_filters` advances the chart reset signal | `test_project_template_workflows.py::test_clear_all_filters_resets_selection_and_resource_filter_state`; shared-filter and organization browser regressions |
| Trusted privileged helper resolution; append-only hardening upgrades | Migration 0065 changes only three helper search paths | `test_wbs_helper_hardening.py` verifies clean setup and upgrade, temporary-object shadowing, unchanged bodies, records/ledger and rejected over-allocation; existing WBS and integrity tests |
| Bounded selected planning cache reads; storage/security preserved on upgrade | Migration 0066 retains bulk path and scope/token envelope while bounding selected sources | `test_cache_key_plans.py` retains +64 shared-buffer bound after 5,000 unrelated tasks; `test_selected_cache_upgrade.py` checks bulk/scoped equivalence, revised/deleted/hidden endpoints, clean/upgrade records, ledger, grants and security |
| Bounded task-source assignment membership | Migration 0068 uses indexed correlated task membership, preserving invoker security and check option | Existing task-source query-plan/oracle regressions; `test_bounded_assignment_membership.py` compares old/new membership, NULL/deleted/inactive rows, grants/options, records and ledger |
| Bounded authorized dependency metadata; append-only stable reference index | `planning.py::_dependencies` resolves minimal active owner tasks and direct/copied endpoint cases under native RLS; migration 0067 adds a partial index | Existing dependency query-plan regression retains +64 buffer growth and two-row scan limits for direct/copied endpoints; `test_planning_dependency_index.py` verifies upgrade history/records; planning authorization, scoped UI and HTTP tests retain hidden endpoint denial/redaction |
| Independent title saves without unchanged WBS contention; allocation integrity preserved | `wbs.py::replace_wbs` skips unchanged writes/global reads and clears empty replacements; existing service authorization/reactivation validation retained | Five ten-editor workloads in `test_project_save_concurrency.py`, including 10,001 projects, preserve properties and exact WBS rows; `test_wbs.py` verifies unchanged/empty reads, unauthorized rejection, caps, rollback, reactivation and competing claims |

These rows map every requirement and all 19 scenarios; the passing clean full
run below supplies execution evidence in addition to source inspection.

## Coherence and final diff review

The dedicated branch precedes planning. Each numbered task has one focused
commit and its completion marker; no completed commits were amended or squashed.
The workflow remains layered Streamlit/PostgreSQL on Python 3.14. New migrations
0065–0068 are append-only: all existing migration files and companions are
unchanged from main. Generated OpenSpec skill bodies are byte-identical to
bootstrap commit `eb2bc67`. No new runtime dependency or business rule is added.

Automatic unfiltered PR CI retains manual dispatch, read-only permissions,
Python 3.14, separate PostgreSQL roles, Docker image build, authenticated browser
opt-in, strict no-required-skips execution, 95% app coverage and all Node checks.
The measured earlier local full run took 47m47s, so task 3.37 budgets 90 minutes
for the complete CI job, including installation/build. No gate was removed.

`git diff --check main` passes. Only safe `.env.example` is tracked; generated
credentials stay in ignored `.local/workflow-tests.env` and are never displayed.
Existing unrelated user data/volumes are not cleanup targets.

## Independent branch review

### Standards

No open Standards findings in `git diff main...HEAD`. Follow-up review found
one optional Playwright import-order issue; task 3.42 corrected it and verified
both missing-dependency collection and installed-browser execution. The application
changes preserve documented layer boundaries, caller-owned transactions,
PostgreSQL RLS, explicit helper search paths, applied migration checksums, and
cancellation/reactivation WBS validation. Baseline repairs retain authorization,
hidden-payload, rollback and integrity assertions. No baseline smell warrants
additional abstraction in these focused changes.

### Spec

No actionable Spec findings. Planning SQL retains active-plan selection,
logical endpoint remapping, native RLS, hidden-endpoint filtering and source-token
semantics. Migration 0068 preserves assignment membership, invoker security and
the local check option. WBS no-op saves retain authoritative edit checks and
serializable transactions; reactivation validates capacity before the shortcut,
and changed allocations retain validation and native constraints. Strict CI
matches the documented prerequisite, collection and required-skip gates.

Review summary: **Standards: one corrected finding, zero open; Spec: zero
findings**. Follow-up reviews covered the browser and subprocess coverage work.
Review is supported by the clean full run; it does not substitute for final PR CI.

## Execution evidence

- Strict gate: 24 isolated pytester regressions passed without services.
- Final JavaScript command: `node --test tests/test_*.cjs`: **10 passed, 0 failed,
  0 skipped** (191.31 ms).
- Independent title saves/WBS/authorization: **78 passed** (68.80s), including
  all five ten-editor workloads, with real PostgreSQL and unchanged isolation.
- Scoped UI and project dialog checks: **147 passed, 1 deselected** (139.72s);
  the independently verified reset case was excluded from that focused run.
- Shared reset, tags and organization browser group: **48 passed** (52.55s).
- Historical upgrade/source inventory and staffing revocation group:
  **45 passed** (45.66s).
- Final remaining baseline group: **49 passed, 1 failed** (44.21s). The failure
  identified an obsolete test service signature; after matching the existing
  `include_deleted` keyword the affected browser module **passed** (2.50s).
  This focused evidence does not substitute for the final consolidated run.
- Previously focused clean/upgrade, bounded cache/dependency and authorization
  checks passed. Measured dependency buffer growth: direct 239 to 247; copied
  269 to 277. After migration 0068, selected planning 615 to 622, capacity
  2,668 to 2,062, task-source 3,355 to 3,352 after 5,000 unrelated tasks. These
  local measurements retain original bounds; they are not general load claims.
- Real authenticated OIDC and deployed restart/restore previously passed
  alongside isolated PostgreSQL. They also passed in clean full acceptance.
- `openspec validate project-workflow-setup --strict`: passed.
- Workflow parsed with system PyYAML; both triggers, all seven steps, read-only
  permissions and strict 95% coverage command verified.

Additional focused evidence:

- Task 3.38: **8 passed** (9.38s), preserving real resource dialogs and database snapshots.
- Task 3.39: **4 passed** (0.44s), including exact dashboard/shared planning reset state.
- Task 3.40: CSV, hierarchy Settings and real Keycloak: **3 passed** (50.53s);
  other shared CSV browsers: **3 passed** (15.87s). Wait for native rerun
  acknowledgment before blurring the project selector and dialog readiness
  before Escape; retain all access grant/revocation and upload reset checks.
- Task 3.41: native CSV browsers and strict pytester cases: **28 passed** (27.89s).
  Function CSV child-process coverage increased from 17/44 to 44/44 executed
  statements. The diagnostic combined preview reached **95.52%**, retaining
  source selection/exclusions/95% threshold. This is supporting measurement,
  **not** clean full-suite acceptance. Official configuration reference:
  <https://pytest-cov.readthedocs.io/en/latest/subprocess-support.html>.
- Completed diagnostic full run before tasks 3.38–3.41: **3,209 passed,
  10 failed, 5 subtests passed**, 40m41s, 94.77% host app coverage. Six failures
  were stale resource UI controls, one reset expectation and three browser
  synchronization failures; all are subsequently fixed and focused-verified.

- Task 3.42: missing-Playwright collection correctly skips; installed-browser
  hierarchy module **1 passed** (5.12s).

## Test duration investigation requested during apply

The collected suite contains 3,219 tests, 2,447 under PostgreSQL. Existing
function-scoped `pg_database` provisions a database and applies all 68 migrations
for each test. A 30-test integrity sample passed in 14.40s, with the slowest setup
phases at 0.42–0.46s each. Serial execution, native server/browser startup and
Docker deployment/restore tests add cost; failing browser waits and repeated
full diagnostic runs also extended this setup effort.

A disposable benchmark retained separate runtime checks and compared three fresh
create+migrate operations with three clones of one closed, freshly migrated
template. Medians: **0.466s fresh versus 0.055s clone (8.46× for preparation)**.
Only newly created random test databases were dropped. No fixture optimization
was applied in this setup branch. This is a small local experiment, not a
whole-suite speedup claim. A dedicated future performance change should verify
isolated template clones for ordinary tests while preserving true migration
execution, then measure controlled process parallelism and browser startup reuse.
The 90-minute CI budget prevents cancellation; it is not a speed optimization.

The successful full run attributes **2,321.68 cumulative seconds** to the 2,447
PostgreSQL-directory cases and **109.85 seconds** to the other 772 cases. The
slowest individual check is deployed recovery (134.44s call plus 19.25s setup),
followed by the 10,001-project concurrency workload (26.37s call). Setup reuse
is therefore the first measured candidate, while retaining recovery, migration,
authorization and workload coverage. A future optimization must prove independent
cache generations, credentials, sequences and database lifecycles as well as speed.

Clean full-suite acceptance command (after image rebuild at task 3.41):

```bash
POSTGRES_TEST_CLIENT_CONTAINER=eppm-workflow-tests-postgres-1 \
EPPM_RUN_OIDC_E2E=1 COVERAGE_FILE=.local/workflow-acceptance.coverage \
.venv/bin/python -m dotenv -f .local/workflow-tests.env run -- \
  .venv/bin/python -m pytest -q -x -p no:cacheprovider --require-full-suite \
  --cov=app --cov-report=term --cov-fail-under=95 --durations=25 \
  --junitxml=.local/workflow-acceptance.xml -o junit_family=xunit1
```

Result: **3,219 passed, five subtests passed, zero failures/errors/skips;
97.69% statement coverage; 40m36s**. JUnit independently reports zero failures,
errors and skips. Earlier diagnostic, interrupted and failing runs are not
acceptance.

The clean run started at `d9dd152`. Application files and coverage configuration
are unchanged through the acceptance commit. Task 3.42 subsequently reordered
two test imports solely to preserve the existing optional-browser skip: a blocked
Playwright import correctly skips, and the installed-browser module passed in
5.12s. That correction does not change execution with installed browser tools;
final PR CI must also pass on the archived revision.

A concurrent, unrelated working-tree edit changes the local PostgreSQL host port
to 5434. It is preserved uncommitted and excluded from this change/PR.
Environment: Python 3.14.7, declared dev/browser tools, Chromium, Docker and
isolated PostgreSQL operator/runtime roles with disposable browser deployments.

## GitHub delivery limits

Main still points to the baseline SHA at final preparation. GitHub reports
`main.protected=false`. Merge commits are enabled, and squash/rebase methods
remain enabled too. The protection endpoint returned HTTP 403 requiring GitHub
Pro or a public repository. Remote administrative changes are outside this
plan. Local policy requires explicit human approval of the concrete PR and a
merge commit preserving task commits; it does not claim server enforcement.

The full CI on the eventual final PR revision remains an additional delivery
gate. PR #1 exists as a draft; its first CI run exposed the two portability
failures documented below. Merging has not occurred and is not approved.

## Task-to-commit evidence

| Task | Commit | Subject |
| --- | --- | --- |
| 1.1 | `47548ba` | docs(project-workflow-setup): complete task 1.1 setup plan |
| 1.2 | `eb2bc67` | chore(project-workflow-setup): complete task 1.2 OpenSpec bootstrap |
| 2.1 | `c63502c` | docs(project-workflow-setup): complete task 2.1 delivery policy |
| 3.1 | `9a8b2b1` | test(project-workflow-setup): complete task 3.1 strict suite gate |
| 3.2 | `78e3fd9` | ci(project-workflow-setup): complete task 3.2 automatic full PR checks |
| 3.3 | `a3383d6` | test(project-workflow-setup): complete task 3.3 align FTE assertions |
| 3.4 | `70df620` | test(project-workflow-setup): complete task 3.4 baseline assertion repairs |
| 3.5 | `24a2fae` | test(project-workflow-setup): complete task 3.5 planning harness repairs |
| 3.7 | `d4b6501` | fix(project-workflow-setup): complete task 3.7 protected helper hardening |
| 3.8 | `c7f748e` | fix(project-workflow-setup): complete task 3.8 scoped free tag filters |
| 3.6 | `2c898d1` | test(project-workflow-setup): complete task 3.6 current UI and data contracts |
| 3.9 | `c1742af` | test(project-workflow-setup): complete task 3.9 historical migration fixtures |
| 3.10 | `24db328` | test(project-workflow-setup): complete task 3.10 staffing projection fixtures |
| 3.11 | `92a5d44` | test(project-workflow-setup): align browser contracts for task 3.11 |
| 3.12 | `df9f694` | test(project-workflow-setup): complete task 3.12 isolated recovery deployments |
| 3.13 | `3335ad2` | fix(project-workflow-setup): complete task 3.13 bounded selected cache sources |
| 3.14 | `a67c2b8` | test(project-workflow-setup): complete task 3.14 current sidebar rerun contracts |
| 3.16 | `8f19864` | test(project-workflow-setup): complete task 3.16 current hierarchy and shell routes |
| 3.17 | `06f35df` | test(project-workflow-setup): complete task 3.17 scoped WBS reader allowlist |
| 3.18 | `87cd3c1` | test(project-workflow-setup): complete task 3.18 current planning transaction contracts |
| 3.19 | `610110a` | test(project-workflow-setup): complete task 3.19 preserve operator pool catalog |
| 3.15 | `123a9ad` | test(project-workflow-setup): complete task 3.15 current Gantt interaction contracts |
| 3.20 | `7675f23` | test(project-workflow-setup): complete task 3.20 synchronized browser project selection |
| 3.21 | `3eda57c` | fix(project-workflow-setup): complete task 3.21 bounded authorized dependency reads |
| 3.22 | `64596bc` | test(project-workflow-setup): complete task 3.22 current lazy planning fixtures |
| 3.23 | `ae191d8` | test(project-workflow-setup): complete task 3.23 accepted capacity exception contracts |
| 3.24 | `04d4cfd` | test(project-workflow-setup): complete task 3.24 historical revision isolation |
| 3.25 | `defb4a0` | test(project-workflow-setup): complete task 3.25 current portfolio browser contracts |
| 3.26 | `d5705bf` | fix(project-workflow-setup): complete task 3.26 bounded active assignment membership |
| 3.27 | `8abc1c1` | fix(project-workflow-setup): preserve independent saves (task 3.27) |
| 3.28 | `25245bf` | test(project-workflow-setup): align scoped collaboration harnesses (task 3.28) |
| 3.29 | `a4ac624` | test(project-workflow-setup): isolate historical upgrade assertions (task 3.29) |
| 3.30 | `a122d8a` | test(project-workflow-setup): refresh staffing in revocation fixture (task 3.30) |
| 3.31 | `64be430` | test(project-workflow-setup): align project dialog and menu contracts (task 3.31) |
| 3.32 | `3c6e48a` | test(project-workflow-setup): restore shared filter reset signal (task 3.32) |
| 3.33 | `b6193ea` | test(project-workflow-setup): align shared status browser fixtures (task 3.33) |
| 3.34 | `108cf51` | test(project-workflow-setup): refresh audited presentation contracts (task 3.34) |
| 3.35 | `5122bc5` | test(project-workflow-setup): retain active tag snapshot contracts (task 3.35) |
| 3.36 | `c99b287` | test(project-workflow-setup): refresh task pool and tag fixtures (task 3.36) |
| 3.37 | `32479f3` | test(project-workflow-setup): budget full CI runtime from measurements (task 3.37) |
| 3.38 | `3a131bd` | test(project-workflow-setup): align resource tree and mapping controls (task 3.38) |
| 3.39 | `ef312b9` | test(project-workflow-setup): assert restored planning reset state (task 3.39) |
| 3.40 | `b0c3e44` | test(project-workflow-setup): synchronize native browser reruns (task 3.40) |
| 3.41 | `d9dd152` | test(project-workflow-setup): collect native browser subprocess coverage (task 3.41) |
| 3.42 | `969dae8` | test(project-workflow-setup): preserve optional browser collection skip (task 3.42) |
| 4.1 | `20fd0a0` | test(project-workflow-setup): verify full acceptance (task 4.1) |
| 3.43 | `137bc7d` | test(project-workflow-setup): select a sandbox-compatible CI benchmark browser (task 3.43) |
| 3.44 | `0e4d883` | test(project-workflow-setup): isolate recovery archives from host user ownership (task 3.44) |
| 3.45 | `4499d2d` | test(project-workflow-setup): fail CI promptly without reducing green-run checks (task 3.45) |
| 4.2 | `1c90f97` | test(project-workflow-setup): verify runner portability repairs and retain full baseline evidence (task 4.2) |

## Clean-runner portability follow-up

The first PR run ([38904081512](https://github.com/cboguet83/eppm_demo/actions/runs/38904081512))
completed with 3,217 passed, two failed, five subtests passed and 97.68%
coverage in 41m24s. SonarCloud Code Analysis passed. This failed run is not
acceptance. The failures were the raw browser benchmark startup and an operator
backup archive write in the deployed recovery fixture.

- Task 3.43: validate an optional absolute executable browser path and use the
  Ubuntu runner's installed Google Chrome for the raw benchmark. Keep the local
  Playwright fallback and every source/cleanup/native payload assertion. No
  sandbox flags changed. The complete benchmark module using the explicit local
  Chromium executable passed: **14 passed in 21.22s**. Workflow parsing confirms
  the runner override and unfiltered automatic PR trigger. The exact runner
  Chromium namespace cause is inferred from its security profile; startup failure
  itself was directly observed.
- Task 3.44: replace the fixture's host data bind with a Compose project-scoped
  named volume. Image ownership initializes its data directory independently of
  the host UID. Verify non-root execution and create/remove a runtime-owned probe
  before yielding the deployment, retaining secret-isolation checks. Real backup,
  restart, restored application and OIDC verification: **2 passed in 192.11s**,
  including real operator archives, restored business/access parity, login,
  bootstrap and access administration. Both isolated deployments cleaned up.
- Task 3.45: add pytest `-x` to the same full CI command. First failures terminate
  promptly; green runs still execute every test, required database/OIDC groups,
  no-skip enforcement, 95% coverage and JavaScript checks. All **24 strict gate
  tests passed in 3.04s**; parsed command verification confirms all gates, no
  selection filter and the unchanged Node command.

Application, migration and coverage configuration bytes are unchanged from the
successful full baseline (`d9dd152`); focused portability checks complement that
baseline and do not claim a second full run. Both independent follow-up standards
and spec reviews found no actionable findings. All five synchronized main specs
remain unchanged. Final updated PR CI is still required before merge.

Task 4.2: benchmark (14), deployed recovery/OIDC (2), strict-suite gates (24),
and JavaScript (10) checks pass with no failures or skips. OpenSpec strict
validation passes for the change and all five main specs. `git diff d9dd152 --
app pyproject.toml` is empty. No new application defect or business rule change
was needed for the CI repairs. Final CI must execute on the archived published
revision; its result must not be inferred from these focused checks.


## Allocation form prerequisite repair

The second full PR run ([38911540632](https://github.com/cboguet83/eppm_demo/actions/runs/38911540632))
stopped after one failure and 1,487 passes in 21m15s. The project allocation form
option became unstable/detached during `options.nth(1).click()`. This failed run
is not full acceptance. The user explicitly approved a focused setup-branch
repair before resuming the separate test-performance plan.

The exact original module passed locally (two tests, 9.06s), so the CI-only
failure cannot be claimed deterministic. A controlled moving-option case on the
actual native form then reproduced the same actionability timeout: one failure,
three deselected, 33.20s. It isolates layout motion as a sufficient cause, not
proof of the precise source of CI layout changes.

Task 3.46 changes test interaction to native combobox ArrowDown/Enter and adds
stationary/moving option cases to both project and task dialogs. No forced click,
retry or longer timeout is introduced. The selected pool must change, WebSocket
reruns must stay empty before submit, and the submitted 2.50 FTE allocation must
render. Application, migrations and coverage configuration are unchanged.

The first corrected complete module run passed all four cases in 16.81s.
Repeat verification and task 4.3 evidence are recorded before rearchive. Final
full PR CI is still required; the earlier full local acceptance remains historical
baseline evidence and is not described as a run of this correction.
