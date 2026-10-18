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

## Task 3.8 — acknowledge project-form event publication

The v5 fresh and template references passed all 3,299 cases and five subtests,
but the first parallel run stopped after 1,786 passes at the WBS form's final
saved-event assertion (741.20s pytest; 742.098730s monitored). The earlier
validation event contained WBS 2 at 35%; the expected final event contained WBS 1
at 100%. This incomplete run is not acceptance, and CI remains serial.

The private scenario renders `project_form(...)` and then its `st.code(events)`
log as separate Streamlit updates. A closed dialog is therefore not an
acknowledgement that the event log has been published. Ranked possibilities
were premature event-log observation, lost form edits, and a missing save event.
The first prediction was that delaying only event-log publication would reproduce
the exact stale-event mismatch while leaving the actual form action unchanged.

The committed regression's private server delays one second immediately before
publishing the final event log, after rendering the closed form. It preserves
the original component, callbacks, values and validation behavior. With the
original test sequence it reproduces the exact WBS 2/35% versus WBS 1/100%
mismatch in **4.25s**. Waiting for the second published server event makes the
same regression pass with the expected final WBS value. This establishes a
test observation race rather than a WBS application defect.

`_wait_for_event_count()` waits at most five seconds for the exact expected
event count in the private page's JSON code block, then the existing assertions
read that log. It does not retry an action, accept an unexpected event count
or increase existing business-assertion deadlines. Both first
validation and final-save reads use the corresponding count. The source audit
found the direct `json.loads(page.locator('pre')...)` browser reads in this module
only; choice ordering, exact decimal money and links had the same publication
gap and now use that acknowledgement as well. Cancel/delete cases already wait
for the expected count and are unchanged.

Every original direct and Playwright assertion is retained exactly, checked
against the committed AST. This includes draft/tabs, untouched versus edited
selection order, precise decimal strings, dirty flags, links, validation,
allocation defaults and remaining capacity, removed WBS rows, and shell-run
checks. Modified test functions now have explicit types and useful docstrings.

All **nine module cases pass (24.55s)**, including ordinary and delayed WBS
publication. The module, adjacent native dialog cases and real PostgreSQL
authorization/revision tests pass **65 cases with two workers/loadgroup and
application coverage collection (36.82s)**. Focused coverage is not full
application acceptance. Application and migration files remain unchanged.

The complete WBS scenario then passes **ten ordinary and ten delayed-publication
repetitions** with fresh browser sessions, without retries or omitted failures.

The complete comparison restarts after this corrective test-source change;
all earlier v5 timings remain diagnostic history. Task 4.1 still requires
identical final-source cohorts, complete A/B/C and successful repeated C,
the original performance targets, full coverage/JavaScript gates and cleanup.

## Task 3.9 — navigation diagnosis and approved application restoration

The v6 fresh reference passes 3,300 cases and five subtests, 97.684036% coverage
and 108 JavaScript cases in 2,437.556362s monitored wall time. Serial/template
then fails after 3,235 passes and five subtests in 1,832.07s pytest /
1,833.948504s monitored. Settings navigation times out in `completed_rerun()`;
this incomplete comparison does not satisfy task 4.1. CI remains serial.

Ranked probes distinguished a missing DOM running transition, replacement of
the observed app node, and a click during initial hydration. The isolated
original navigation reproduces the observer timeout on its fourth page. Actual
Streamlit protocol messages show successful completion; the Settings submenu
is rendered and the original app node remains connected, but the helper has
not observed the required `notRunning -> running -> notRunning` sequence.

A separate, tighter probe asserts main-content visibility after actual protocol
completion rather than waiting thirty seconds for that DOM observer. It fails
on its fifth ordinary navigation. More importantly, explicitly waiting for the
initial successful script completion and actual idle state does not resolve
the problem: the second navigation fails with completion count 1 -> 2, idle
true, the destination's hierarchy tabs present, `body.eppm-page-loading` still
set and the main content's computed visibility `hidden`.

This is a real application loading-overlay defect, not merely a false test
observer timeout. `page_transition.py` requires witnessing the transient DOM
running state before removing the overlay; a fast completed navigation need not
commit that intermediate presentation state. Replacing the test observer alone
would conceal the stuck main page and is not accepted as a repair.

The user explicitly approved the task 3.9 application extension on 2026-10-18.
The correction adds an opaque page-render marker after the shell's destination
renderer returns (also for a rejected route), letting the transition observe
completed rendering without requiring a transient running DOM state. Idle,
no-skeleton and two-animation-frame checks remain; a navigation generation
prevents a stale reveal from releasing a later request. No business rules,
authorization checks, migration bytes or CI/coverage gates change. The approved
UI restoration now has an actual `completed-page-navigation` capability delta
and supersedes the original tooling-only `skip_specs` exemption.

The Settings test attaches the existing bounded protocol observer before initial
navigation and waits for real successful completion around its click. Every
original navigation, layout and hierarchy CRUD assertion remains. CSV and OIDC
helper callers are retained; they are not silently replaced without a reproduced
observer fault.

A controlled real-browser regression suppresses only the component's observed
transient running state while retaining actual Streamlit rendering/completion.
On the original implementation it fails with the loading overlay still visible
after successful destination completion (**1 failed, 1 passed in 10.56s**).
The correction passes both ordinary/coalesced slow navigation cases, including
frame-by-frame proof that unfinished content is hidden, plus both existing
chart full-rerun/fragment response cases (**4 passed in 11.52s**). The wider
focused set including Settings CRUD and protocol observer negative cases passes
**9 cases in 16.36s** before the added frame sampler.

The exact causal Settings probe that previously failed on its second
completion-aware navigation now passes **30 consecutive fresh-page navigations**
without retries. Native shell/fragment tests, real PostgreSQL retained-page
authorization/fragment tests and all four CSV helper callers pass **35 cases in
25.73s** with two workers/loadgroup/template mode. Four JavaScript regression
cases pass for old-content rejection, coalesced completion with idle/skeleton
checks, unchanged fragment completion and superseded reveal callbacks.

Task 4.1 remains open. All cohorts and full comparisons restart on this corrected
application/test revision; earlier timings are diagnostic only. CI remains
serial/fresh until acceptance passes, and archive/PR/merge gates remain intact.

Final layout-free marker verification passes **5 native navigation/Settings cases
in 16.61s**. The marker uses style-only HTML outside Streamlit's visible main
layout. The unchanged authenticated login/pending/bootstrap/access-administration
browser workflow passes **1 case in 37.06s** against the rebuilt correction image
from the established managed checkout. Initial disposable deployment attempts
from the dirty primary workspace and `/tmp` stopped before browser execution;
the temporary checkout's Docker bind mount was explicitly denied by Desktop.
No failed attempt is counted as a pass, no test was retried within a suite, and
the user's local Compose/environment edits remain untouched. The final image
is rebuilt for the layout-free marker before the new comparison. All **112 Node
cases pass**, with zero failures/skips. AST comparison confirms every original
assertion in both modified browser modules remains. Strict OpenSpec validation
passes; focused checks do not substitute for the pending full comparisons.

## Task 4.1 — v7 reference blocked by independent-save contention

Task 3.9 is committed as `f8d7c0eac1b3f1739cba96aee1ca5d29ccdd08c3`.
The final image was rebuilt and the managed verification checkout advanced
without changing the three fixed measurement inputs. V7 source fingerprint is
`bba2b312f058d51a9be1316f1a67f59039089cd6d0a970893b80920f02007dc3`.
All nine preparation cohorts pass their 54 canonical cases. Median migrated
preparation is A 19.166846s / B 5.421497s / C 6.442131s: **66.389194% lower**
for C. This is preparation evidence only.

The fresh/serial full reference then fails at the large ten-editor title-save
case after **1,833 passes**, with five safe `ProjectStorageError` results caused
by exhausted `TransactionRetryError`. Pytest wall time is **1,949.09s** and
monitored wall time **1,950.755298s**. It fails before full B/C, Node execution
or performance acceptance. The failure is in the unchanged persistence code;
`git diff origin/main...HEAD -- app/application app/infrastructure` is empty.
No measured source was edited while the matrix ran.

A fresh isolated reproduction passes without coverage (36.10s), but reproduces
the failure with coverage (35.58s), excluding prior-test state as a necessary
cause. Exception-only instrumentation records SQLSTATE 40001 dependency-pivot
failures while reading owner-specific WBS/property rows. It logs SQL templates
and diagnostic types, never bound values or connection coordinates. A ten-project
control passes with zero exceptions and ten project updates; it performs no
property writes, so unexpected dynamic-property rewrites are not the cause.

Paired disposable-database probes keep all original ten-success, title, WBS and
property assertions and the unchanged three-attempt replay limit:

| Project-table treatment | Result | Time | Save attempts |
| --- | --- | ---: | --- |
| Default fillfactor 100, VACUUM FULL | Failed | 35.17s | Several reach three; some exhaust |
| Fillfactor 50, VACUUM FULL | Passed | 34.29s | All ten succeed on first attempt |
| Fillfactor 70, VACUUM FULL | Passed | 30.32s | All ten succeed on first attempt |
| Fillfactor 70, CLUSTER by existing primary key | Passed | 34.65s | All ten succeed on first attempt |

These results establish a physical-layout dependence. Avoiding non-HOT index
updates is the mechanism supported by the probes and PostgreSQL's
[HOT documentation](https://www.postgresql.org/docs/18/storage-hot.html) and
[SSI implementation notes](https://raw.githubusercontent.com/postgres/postgres/REL_18_STABLE/src/backend/storage/lmgr/README-SSI);
no direct HOT-counter measurement has yet been captured. The candidate is not
claimed as a completed migration or a universal no-retry guarantee.

Only disposable test databases received these diagnostic treatments. No new
application migration, retry policy or business/security change has been made.
A proposed forward migration would reserve 30% project-table page space and
repack existing rows, preserving serializable isolation and the three-attempt
bound. Its costs are more table space, temporary rebuild space and an exclusive
read/write-blocking lock during the repack, per PostgreSQL's
[CLUSTER documentation](https://www.postgresql.org/docs/18/sql-cluster.html).
A separate user approval request for focused task 3.10 is pending because the
application-storage scope exceeds the task 3.9 navigation approval.

Task 4.1 remains unchecked, CI stays fresh/serial, and archive/PR creation waits
for actual successful full comparisons. No failed full run or diagnostic
partial run is counted as acceptance, and no assertion or gate is weakened.

Post-diagnostic audit: no current-invocation `eppm_test_serial_*` database remains. One differently named `eppm_test_<uuid>` database with idle runtime clients was observed on the shared test server; ownership is not established and it is left untouched. Future controlled comparisons must wait for an uncontended server and the driver's zero-other-resource check. Do not infer or perform prefix-based cleanup.

## Task 3.10 — approved forward-only project update headroom

On 2026-10-18 the user explicitly approved the fillfactor-70 forward migration,
existing-row repack, regression tests and dedicated commit, including the
exclusive-lock and disk-space tradeoffs. Migration 0069 changes only project
table storage: ALTER TABLE fillfactor, CLUSTER through its existing primary key,
then ANALYZE. All **68 historical migration files remain byte-for-byte equal
to HEAD**. The transaction engine, three-attempt limit/backoff, authorization,
business services and original concurrent-save test module have no diff.

The new clean-install regression failed before the migration with **zero HOT
updates instead of ten** (0.96s), independently of checking a configuration value.
It now requires ten on-page updates from the real transaction-local PostgreSQL
statistics view, avoiding asynchronous cumulative-counter polling.

Three migration cases pass (2.53s before formatting-only cleanup): clean page
headroom, populated upgrade/reentry and a controlled failure after repacking.
The populated cases compare all project rows, WBS shares, project cache revisions,
owner/ACL/RLS flags, row policies, constraints and index definitions. They retain
the complete historical ledger including timestamps; the deliberate failure
restores the old storage file/options and ledger before a successful reapply.
No row/security object is rewritten to make the tests pass.

The final formatted tests and all existing concurrent editor, foundation
transaction/retry, allocation integrity, WBS hardening and business-authorization
cases pass **124 tests in 108.54s** under coverage with fresh/serial preparation.
The identical set passes **124 tests in 52.66s** with coverage, template mode and
two workers/loadgroup, with worker restarts disabled. The original ten-editor
workload passes in both, including its 10,001-project/browser-form case. Focused
coverage collection is not full application acceptance; the full 95% gate and
all Node cases remain required in the new controlled comparisons.

The capability delta retains every existing independent-save requirement and
scenario, adding populated-upgrade preservation coverage. Documentation records
page-space/HOT rationale, maintenance-window locking, temporary rebuild space
and increased table storage; this is not a universal no-retry guarantee.
Strict OpenSpec validation passes.

Another invocation was observed creating differently owned databases on the old
shared test service. Its resources were left untouched. A new isolated
`eppm-performance-tests-postgres-1` service, PostgreSQL 18.6 / max_connections 100,
is created on loopback port 25432 with distinct newly generated ignored test
credentials for the restarted comparison. No application database is modified.
Task 4.1 remains open and CI stays fresh/serial pending complete final-source
cohorts, full A/B/C/repeated-C, unchanged full gates and performance acceptance.

## Task 4.1 — complete corrected-source acceptance

V8 completes all nine 54-case preparation cohorts and all four full runs on
`09b57a6` plus the three fixed measurement inputs, source fingerprint
`c7696b72aed956ca5bad730ad4d64bb9b4103e2ecd28656b93388b10e686f961`.
A/B/C1/C2 monitored wall times are 2,537.813874 / 2,123.056248 / 1,277.208545 /
1,243.467171 seconds. The slower C improves full wall time **49.672884%**;
C median preparation improves **67.723838%**. Both targets pass.

The independent raw audit verifies all 3,304 canonical setup/call/teardown
outcomes exactly once, five passing subtests, no skipped/failed reports,
matching full worker collections and nonzero work on each original worker.
All four coverage reports have exactly the same 283 files, excluded/missing
lines and 16,539/16,931 statements (**97.684720%**). All 112 Node cases pass
in each run. Each full cleanup check has zero test databases/other clients.
Unrounded inputs/results/resources, connection-budget observations and method
limits are preserved in `measurements.json` and `measurement.md`; earlier
failed comparisons remain explicit diagnostic history, never acceptance.

The opt-in metrics helper is tested by the complete suites: it records real
preparation timing/outcomes without fixture values, rejects stale/missing
output directories, and retains failed preparation results/nonzero exits.
Its subprocess tests join the audited heavy scheduling group. The C3 test
infrastructure map documents the existing components. CI is still unchanged
in this task; template default and two-worker promotion are task 4.2.

## Task 4.2 — promote the measured configuration

Template preparation is now the pytest fixture default; parallelism remains
explicit. Full PR CI appends only `-n 2 --dist=loadgroup
--postgres-test-db-mode=template --max-worker-restart=0` to its existing command.
Parsed YAML deep comparison with origin/main confirms every other workflow
field is unchanged: unfiltered pull_request/manual triggers, Python 3.14,
prerequisites, real PostgreSQL/OIDC, fail-fast, strict completion, 95% coverage
and all JavaScript checks. The opt-in metrics plugin is not added to CI.

The strict gate/controller/scheduler and real fixture-contract set passes
**57 cases in 17.31s** under two workers. A separate real default invocation
passes both fixture-contract cases (**1.37s**) and its measurement record
confirms template mode with no explicit mode argument. Post-promotion
collection-only comparison retains all **3,304 canonical IDs in exact order**;
this is manifest evidence, not another claimed full execution. The existing
explicit fresh reference remains available and was already fully verified.

Developer documentation now gives the accepted complete command, serial/fresh
fallback, local focused feedback guidance and measured scope/limitations.
Only the option default and explicit workflow flags change execution selection;
CI uses exactly the previously measured C configuration. No application, test
assertion, coverage scope, source, dependency or schema change occurs here.
The sandbox initially denied Node's nested Git process; the native parsed
workflow check succeeds with the authorized execution permission.
