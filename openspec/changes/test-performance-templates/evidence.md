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
