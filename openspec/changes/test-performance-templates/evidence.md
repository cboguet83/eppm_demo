# Implementation evidence

## Task 2.1 — owned migrated template lifecycle

The real PostgreSQL lifecycle module verifies lazy one-time migration, a closed
template, distinct empty/fresh/clone paths, exact ledger checksums, migration and
metadata initialization failures, clone creation/initialization failures,
database ACL/grant-option/connection-limit/role-setting parity, exact-name
cleanup, closed-factory rejection and secret-safe driver/migration errors.
Generated-name and query-override validation run before database I/O.

```bash
POSTGRES_TEST_CLIENT_CONTAINER=eppm-workflow-tests-postgres-1 \
.venv/bin/python -m dotenv -f .local/workflow-tests.env run -- \
  .venv/bin/python -m pytest -q -x tests/postgresql/test_template_database.py
```

Final result: **17 passed in 11.33s**, no failures or skips. New support/test
modules also pass syntax, explicit signature-annotation and 79-column checks. Application and
applied migrations are unchanged. Fixture integration follows in task 2.2.

## Task 2.2 — selectable fixture preparation

`pg_database` uses the worker-local owner in explicit fresh/template modes;
the default remains fresh. `empty_database` remains unmigrated and independent.
The legacy fixture value and URL helper imports are preserved. New regressions
verify combined fixture requests and absence of business/security seeds.

All 30 modules containing actual empty-database migration/fixture paths pass in
both modes: **273 passed in fresh mode (194.80s)** and **273 passed in template
mode (125.93s)**, with no failures/skips. This includes clean install, historical
upgrades, rollback, competing migration runners and schema compatibility. These
focused timings are not the final controlled whole-suite speedup comparison.
The unchanged strict-suite gate checks also pass: **24 passed in 3.14s**.

Fresh/template collection manifests are identical: **3,241 canonical test IDs**.

## Task 2.3 — native clone and process isolation

Reconciled setup prerequisite commit `bc18f05` through a merge commit, preserving
its 58 dedicated task commits and the unrelated local environment/Compose edits.
The setup PR remains unmerged; full CI and explicit merge approval remain gates.

`authorized_database()` now supplies the same per-database key/account/session/
grant seeding and restricted-pool teardown to ordinary fixtures and direct clone
regressions. No application, migration or security contract changed. Native
regressions prove sibling writes/sequences/revision generations, lifecycle/OID
cache identities, signing-key rejection, local session revocation, pristine
subsequent clones and two simultaneous independent factory invocations.
Initialization faults and checksum changes fail closed. The process probe proves
normal `-x` cleanup and controlled hard-exit leftovers, then recovers only exact
recorded database names with matching OID/owner; a foreign database survives.
Uncontrolled forced worker termination still cannot guarantee finalizers.

Commands use the ignored explicit test-server environment with
`python -m dotenv -f .local/workflow-tests.env run -- python -m pytest -q -x`:

- Six modules: `test_template_database`, `test_template_isolation`,
  `test_revisions`, `test_business_security`, `test_business_transaction_security`,
  `test_authorization`: **270 passed in 149.87s**, template mode.
- Eight cache modules: `test_authorized_cache`, `test_derived_cache`,
  `test_bounded_cache_keys`, `test_cache_key_plans`, `test_revision_plans`,
  `test_portfolio_revision`, `test_plan_import_revision`, `test_display_revision`:
  **92 passed in 102.08s**, template mode.
- New six isolation/process cases independently pass with fresh rollout setting:
  **6 passed in 7.56s**. The tests explicitly request clones where appropriate.

No failures/skips in these checks. Copied-epoch/OID recreation and transactional
invalidation regressions remain unchanged and passed. These focused runs are
correctness evidence, not controlled performance comparisons.

## Task 3.1 — controller/worker full-suite proof

Added development-only `pytest-xdist>=3.8,<4` and installed 3.8.0 with
execnet 2.1.2 on Python 3.14.7. Published Python metadata permits this runtime;
actual worker regressions establish compatibility rather than relying on a
classifier. Runtime dependencies, application scope and coverage settings remain
unchanged. CI remains serial pending scheduling and measured acceptance.

The strict gate gathers complete ordered collections, rejects mismatches and
duplicated IDs, requires both integration groups, forwards collection/runtime
skips, and reconciles exactly-once call/final reports. Normal worker exits must
include their skip proof. Missing reports, duplicate completions, missing worker
proof or crashes fail; strict mode disables replacements even when requested.
Existing serial skip/prerequisite behavior and nonzero exit codes are preserved.

`python -m pytest tests/test_full_suite.py tests/test_full_suite_parallel.py -q -x`
passes **48 cases in 11.07s**: 24 existing serial cases and 24 actual two-worker
subprocess regressions. Cases include complete success, missing prerequisites or
groups, deselection, required import/setup/call/teardown skips, divergence,
missing reports, duplicate collection/completions, missing worker proof, crash,
fail-fast, collection errors and successful subtests/optional skips. An initial
duplicate-report probe accidentally shadowed gate registration; the corrected
probe uses a distinct hook implementation and fails as intended. No failed
diagnostic was counted as acceptance.

## Task 3.2 — audited two-worker/loadgroup scheduling

Parallel execution requires exactly two workers with `--dist=loadgroup`; serial
`-n 0` remains available. Native browser/benchmark filenames, audited native
callers without those names, recovery and subprocess harnesses share one heavy
group. The controller rejects conflicting combined marks before dispatch.
Direct-creator source audits and actual full-repository worker collection parity
regressions preserve every canonical ID; a real scheduler execution probe proves
heavy members share a worker and selected IDs execute exactly once.

All benchmark creators/cluster-wide observers (including indirect operator CLI
callers) live in `test_benchmark_tools.py`. Grouping does not coordinate another
invocation, so its autouse fixture also holds a maintenance-database advisory
lock with a bounded 180-second acquisition timeout. Real independent workers
prove distinct process IDs, simultaneously live isolated clones/templates, local
business rows, non-overlapping shared lock intervals and exact cleanup. Timeout
regression verifies bounded sanitized failure and subsequent lock release.

Actual commands/results:

- `pytest tests/test_test_scheduling.py tests/test_full_suite.py
  tests/test_full_suite_parallel.py -q -x`: **55 passed in 16.34s**. Updated
  collection fault probes compose with the policy hook instead of replacing it.
  The final scheduling-only repeat passes **7 cases in 5.22s**.
- `pytest tests/postgresql/test_parallel_resources.py
  tests/postgresql/test_benchmark_tools.py -q -x -n 2 --dist=loadgroup
  --postgres-test-db-mode=template`, with the explicit test-client container and
  browser path: **16 passed in 20.26s**, no skips. An initial diagnostic omitted
  the required client-container variable; its missing-client failure/skips were
  corrected in the invocation and are not acceptance.
- Complete audited heavy group in the isolated verification checkout:
  `pytest -q -x -p no:cacheprovider -n 2 --dist=loadgroup
  --postgres-test-db-mode=template -m xdist_group`, with real OIDC enabled and
  the explicit client/browser prerequisites: **224 passed in 679.37s**, no
  failures/skips. This included all native browser, benchmark, real OIDC/recovery
  and then-present subprocess harness cases. Subsequent policy error-path and
  formatting changes preserve the tested workload grouping; their regressions
  pass separately. The future coverage probe is verified in task 3.3.

The one-second sampler included fixture/worker startup and observed peaks of
**7 client connections**, **76,805,066 bytes** of test/benchmark databases and
**2,229,428 KiB** host test-process aggregate RSS (shared pages counted per
process). Wall time including monitoring was 680.07s, 670 samples. Docker
container memory is separate and was not captured as a peak in this focused
run. Dedicated server capacity is 100 connections; provisional full-run budget
is 40 test clients on the existing Docker 8-CPU/about-7.48-GiB allocation.
Full cross-group connection, memory/disk and repeated-runtime evidence remains
mandatory in task 4.1 before any CI promotion.

Role changes are UUID-owned or database-specific, backend termination is
owned-pool-specific, temporary scripts/logs use per-test directories and
deployments use UUID project/volume names with candidate dynamic ports. Diagnostic
screenshots are outputs only; concurrent full invocations need separate
checkouts/coverage paths. No shared password/security assertion changed.

After the complete heavy run: zero test/benchmark databases and zero other
client connections remain on the isolated test server. User-staged Compose and
environment-example edits were preserved through an explicit-path task commit.

## Task 3.3 — combined worker/native subprocess coverage

New probes execute distinct existing `app.domain.tags.rules` branches in an
ordinary worker, a second worker hosting the native browser test, and its actual
Streamlit child. Fresh per-test coverage files combine all three branches under
one application source path. Worker identity files prove the parallel branches
came from two different processes; the same proof also passes serially. Native
shutdown uses the existing graceful termination and coverage subprocess patch.

Negative two-worker coverage runs reject missing final reports and worker loss;
a passing partial fake suite with the existing 95% threshold fails specifically
for insufficient coverage. No threshold, source, exclusion or security setting
was changed. Focused probes omit the whole-application threshold except for its
explicit negative regression; they are not full acceptance. Containerized OIDC
remains a separate behavior gate, not host coverage evidence.

`pytest tests/postgresql/test_parallel_coverage.py -q -x`: **5 passed in 11.14s**.
The same five cases under outer `--cov=app` with a fresh data file and JSON report:
**5 passed in 12.36s**. Full collection/scheduling parity with the new probes
present also passes under outer coverage: **7 passed in 7.37s**. These checks
exercise both the supported coverage configuration and nested instrumentation
used by full verification. Complete 95% application runs remain required in
task 4.1; coverage-related fixture success does not substitute for them.

## Task 3.4 — bounded observation of pool backend shutdown

The first serial/template full attempt was interrupted by an external sampler
race (`pg_database_size()` observed an OID concurrently dropped by a test).
The corrected sampler counts that missed observation instead of stopping tests;
a controlled fault-injection probe verifies child completion and the counter.
The restarted full run then failed the existing immediate shutdown assertion:
**1 failed, 1,000 passed in 673.72s**. Neither attempt is acceptance evidence.

A tight loop calling the actual shutdown test reproduced three failures in
107 template-mode iterations and three in 83 fresh-mode iterations. In every
case, a new observer found zero remaining sessions about 8–11 ms later. Thus
this is an existing server-observation race, not template-only session leakage.
The application simply delegates closure to the pool; its implementation and
security configuration remain unchanged. The [pool API contract](https://www.psycopg.org/psycopg3/docs/api/pool.html#psycopg_pool.ConnectionPool.close)
closes the pool and waits for worker threads; it does not promise an immediately
updated remote `pg_stat_activity` view.

The user explicitly approved adding this corrective task and rerunning the
comparison. The real test still requires both initial pool sessions and
immediate closed-pool state. It observes disappearance of those exact backend
PIDs, restricted to its database, with a two-second deadline and 10 ms polling.
There is no retry of application operations or failed tests. A `finally` closes
the resource even on assertion failure. A persistent session remains a failure.

The delayed-observation regression first failed against the immediate-assertion
implementation, then passed after bounded observation; a deterministic deadline
regression rejects a persistent backend. Both pass in **0.07s**. The complete
foundation module passes **51 cases in fresh mode (10.42s)** and **51 in template
mode (6.17s)**. The original real-shutdown loop then passes **300 iterations per
mode**, with no failures. Application and migration diffs remain empty.

All previously collected performance numbers are diagnostic history, including
the successful 3,291-case serial/fresh run. Task 4.1 requires a new interleaved
cohort and full A/B/C/repeated-C series on these revised final test sources.
CI remains serial until that series passes every correctness and speed gate.


## Task 3.5 — dashboard table selection acknowledgement

The first two-worker full comparison stopped after one failed dashboard case
and 200 passes. Python matching counts and the finance chart can update before
the table has rendered the new selection/token. Clicking that old row again
sends a stale event, which the existing application correctly rejects. The
adjacent dashboard scenario already waited for the row's selected state.

The user explicitly approved this focused corrective task. The finance case now
waits for `aria-selected=true` before clearing selection and requires `false`
afterward. Chart amounts (50/25 kEUR), 1/1,000 matching counts, both project
cycles and one shell run remain asserted. No application operations or failed
tests are retried, and no assertion deadline was increased.

The new fixture variant wraps the original table JavaScript only inside its
private generated test server. It delays selected-state rendering by two
seconds, preserves the original renderer/cleanup and cancels pending timers.
With the original test, this real-browser regression failed the deselection
assertion in **9.17s**. After the acknowledgement repair, the complete dashboard
module passes all **three cases in template mode (22.93s)** and **fresh mode
(23.11s)**. The module plus ordinary business-security and revision cases passes
**55 cases under two workers/loadgroup with application coverage (25.61s)**.
Focused coverage is not the full 95% acceptance gate. The measurement/scheduling
harness also passed 12 cases, strict OpenSpec validation passed, and all ten
JavaScript test files passed during resume checks.

Application/migration/security sources and coverage scope remain unchanged.
The only application-package metadata difference from main is the already
approved pytest-xdist development dependency. Every controlled mode will now
restart on identical revised sources; prior A/B results remain diagnostic.
The original 50% preparation/25% full-wall improvement criteria remain, without
an absolute seven-minute limit. CI stays serial pending task 4.1 acceptance.

## Task 3.6 — organization filter completion and component readiness

The restarted serial/fresh reference stopped after **694 passes and one
organization-browser failure in 491.60s** (493.61s monitored). The failing
Ctrl-click expected two matching projects but retained Service A alone. This
was before parallel execution; no failed or partial run counts as acceptance.
The user explicitly approved a focused test-only investigation and repair.

The exact isolated test passed in 6.26s and then passed 20 ordinary repetitions.
A 0.8-second fragment-tail delay did not reproduce it. With Chromium rendering
throttled sixfold, the original scenario failed on iteration 19 at its first
Space press after Reset: three projects remained instead of Service A's one.
This exposed a concrete readiness gap in the same scenario; it does not prove
that the initial Ctrl-click failure had an identical low-level cause.

A smaller real-browser probe controls the existing service-button renderer's
cleared-state delay. Immediately after Reset, Python's matching count is three
while the old button remains pressed. Focusing that old node, allowing the
queued redraw to complete, and pressing Space loses focus and fails selection.
Waiting for its actual cleared state before focusing retains focus and passes
the same keyboard operation. This changes only the private generated server,
not application functions, callback rules or authorization.

The committed regression runs the complete original scenario in immediate and
delayed-service modes. The delayed mode wraps the original JavaScript renderer
with a one-second cleared-state delay, including timer/renderer cleanup; its
1.2-second pause after focusing deliberately represents a user pausing while a
queued redraw finishes. With the original interaction sequence it failed in
**13.79s** at the first post-Reset keyboard selection. The normal case has no
fixed delay. The repair uses a hidden counter emitted after the original
Dashboard fragment completes, plus the expected actual pressed service buttons
before continuing. It reuses the existing bounded completion helper; business
assertion deadlines remain unchanged. It does not retry an event or a test.

Every original Playwright and direct assertion is retained, checked against the
previous committed AST. Both click and Ctrl-click selection/replacement,
keyboard toggling, cascading divisions/teams/managers, 25/100 kEUR budget values,
matching counts, reset defaults and layout checks remain. The controlled
regression is green with the repair. The whole module passes **three cases in
template mode (24.95s)** and **fresh mode (24.94s)**. Adjacent Dashboard/shared
filter browser modules plus ordinary security/revision tests pass **61 cases
under two workers/loadgroup with application coverage (73.92s)**. Focused
coverage is not the full 95% acceptance gate.

The corrected complete scenario then passes **20 fresh-database repetitions**
under the same sixfold Chromium throttling that exposed the original keyboard
failure. No failed repetition was retried or omitted.

Application and migration bytes remain unchanged. All nine pre-repair cohorts
passed (65.68% median preparation reduction), but are diagnostic history because
test sources changed. Task 4.1 requires a fresh complete comparison on the new
sources. CI stays serial until all original correctness/performance gates pass;
there is no absolute seven-minute limit.

## Task 3.7 — completion-aware finance-selection actions

The repeated optimized v4 run failed after 197 passes (48.23s pytest time) at
the first clear-selection assertion, despite the selected-row check added in
task 3.5. The first optimized run had passed all 3,295 tests; one successful run
therefore did not satisfy the repeatability gate. No CI promotion occurred.

The user approved this focused task and further test-only browser synchronization
follow-ups, each retaining assertions, diagnosis evidence and a dedicated commit.
Application, business-rule and security changes remain outside that approval.

A diagnostic runner preserved the full collection and two-worker/loadgroup
scheduling, stopping intentionally after the target case rather than running the
remaining suite. It reproduced the original failure on its fifth invocation:
one failure and 197 passes in 45.83s. A private callback observer logged only
synthetic project IDs, selected IDs and token-match booleans. The first selection
reached the callback with a matching token; the clear callback never arrived.
This rules out a rejected clear token in that observed failure, but does not
identify the exact frontend/transport step that lost the event.

Further private pointer/protocol observations confirmed a readiness gap:
the original sequence sent the next row click while Streamlit still reported
the previous dashboard run active. Selected-row and finance-chart visibility
were insufficient to establish script completion. Seven additional observed
original-sequence runs passed, demonstrating the failure's intermittent nature.
Private probes changed no application files and printed no payloads, tokens,
cookies or connection strings.

The test now attaches a completion observer before navigation. Each real row
click waits for the previous successful run to become idle and then for a new
successful completion plus actual idle status. Early-for-rerun notifications
and temporary idle notifications alone cannot release the wait. Missing initial
or new completion fails after a bounded ten seconds; browser-action failures
propagate without waiting or retrying. All original business assertion deadlines
remain unchanged. There is no test retry or repeated click.

Four focused protocol checks pass. A temporary in-process mutation bypassing
the waits makes three checks fail: an action runs before the queued successful
completion, and missing initial/requested completions incorrectly pass. The
unmodified observer passes those checks, including actual idle after completion,
ignored early reruns/text frames, and propagation of the original action error.
This is regression evidence for the observed synchronization gap, not a claim
of a deterministic reproduction of the underlying intermittent event loss.

Eight completion-aware full-scheduling diagnostic replays passed. Early replays
used a preliminary observer; the last three used the final helper, which
also requires the server's actual idle notification. Pointer traces show those
clicks following successful completion/idle instead of overlapping the prior
run. The original test still uses real Playwright row clicks, restricted native
servers and both ordinary/delayed-table scenarios. An AST comparison confirms
every existing direct and Playwright assertion is unchanged.

The dashboard module and protocol regressions pass **seven cases in template
mode (23.00s)** and **fresh mode (23.33s)**. Dashboard, organization and shared
filter browser scenarios, ordinary authorization/revision tests and the protocol
regressions pass **65 cases under two workers/loadgroup with application coverage
collection (70.84s)**. The focused protocol/measurement checks pass nine cases.
No application or migration files differ from merged setup PR #1.

Full acceptance remains task 4.1: restart all cohorts and complete A/B/C/repeated-C
on identical final sources. These focused and intentionally stopped diagnostic
runs do not satisfy full completion or the 95% application coverage gate.
