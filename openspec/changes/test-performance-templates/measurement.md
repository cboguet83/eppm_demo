> Historical comparison before main PR #3 integration. Task 4.4 must remeasure the integrated sources. Migration 0069 below names the unpublished preview now renumbered, without SQL changes, to 0071.

# Controlled test performance measurements

Status: task 4.1 acceptance PASSED. All nine cohorts and four full runs pass; CI promotion is the next separate task.
The original 50% preparation and 25% full-wall improvement targets apply.
There is no absolute seven-minute execution limit.

## Fixed inputs and method

Revision: `09b57a6fffa0ce21d4fc70352b9fbe0fac47d53c` plus three fixed task-4.1 inputs:
`tests/conftest.py` (measurement-harness scheduling),
`tests/performance/template_metrics.py`, and `tests/test_template_measurements.py`.
App/tests/config source fingerprint: `c7696b72aed956ca5bad730ad4d64bb9b4103e2ecd28656b93388b10e686f961`.
Installed versions, source bytes and the application image are checked before
and after each run. Application bytes include the approved task 3.9 navigation restoration;
migration 0069 adds the separately approved task 3.10 project-page headroom.
All 68 historical migration files retain their original bytes.
Unrelated user environment/Compose edits are excluded by the isolated checkout.

A is serial/fresh; B serial/template; C two-worker/template with loadgroup.
Three cohort repetitions interleave A/B/C, B/C/A and C/A/B.
The dedicated PostgreSQL 18.6 service uses loopback port 25432 and a private
Compose override; credentials are generated into its ignored environment file.
The older shared service and unrelated development workloads remain untouched.
Complete A/B/C runs
and a repeated C run require matching canonical collection/outcomes, no skips,
95% application coverage, all JavaScript cases and zero remaining test databases
or other clients. No test retries, worker restarts, stale coverage or persistent
cross-invocation templates count toward acceptance.

Preparation measures the real `pg_database` fixture setup, including each
worker's first cold template. Seeding, test calls, startup and teardown remain
in wall time. The external resource sampler adds small overhead to monitored
wall time. Focused cohort coverage is not the full application gate.

## Preparation cohorts

All nine cohorts pass the same 54 canonical cases, identical outcomes and
6.762743% focused coverage, with zero test-database/client leaks. They contain
`test_database_fixture_modes.py`, `test_revisions.py` and `test_business_security.py`.

| Run | Mode | Wall seconds | Migrated preparation seconds |
| --- | --- | ---: | ---: |
| cohort-1-A | A | 35.696265 | 21.880806 |
| cohort-1-B | B | 18.311584 | 5.788727 |
| cohort-1-C | C | 13.303446 | 6.977939 |
| cohort-2-B | B | 18.363230 | 5.745349 |
| cohort-2-C | C | 14.301208 | 6.758936 |
| cohort-2-A | A | 35.631081 | 21.619483 |
| cohort-3-C | C | 14.290459 | 7.095205 |
| cohort-3-A | A | 33.581754 | 21.341893 |
| cohort-3-B | B | 21.392786 | 6.626180 |

Median preparation: A=21.619483s, B=5.788727s, C=6.977939s.
C reduces preparation by **67.72%**; the 50% preparation target passes.

## Full comparison

| Run | Cases / subtests | Coverage | Wall seconds | Preparation seconds |
| --- | ---: | ---: | ---: | ---: |
| full-A | 3304 / 5 | 97.684720% | 2537.813874 | 841.415367 |
| full-B | 3304 / 5 | 97.684720% | 2123.056248 | 247.129503 |
| full-C-1 | 3304 / 5 | 97.684720% | 1277.208545 | 330.752346 |
| full-C-2 | 3304 / 5 | 97.684720% | 1243.467171 | 330.390460 |

## Resource observations

PostgreSQL has a 100-connection limit; the conservative test client budget is 40.
Docker has 8 CPUs and 8,026,890,240 bytes allocated memory.
Client/logical-database/descendant-RSS sampling is approximately once per second;
Docker memory approximately every ten seconds; filesystem headroom every thirty.
The Docker scope includes the isolated test server, `eppm-e2e-*` and `eppm-load-*`
deployments. Host RSS counts shared pages per process and is separate from Docker
memory. Peaks are sampled observations, not hard maxima. Expected database-drop
races are counted as missed observations without interrupting child tests.

| Run | Peak clients | DB MiB | Host RSS MiB | Docker MiB |
| --- | ---: | ---: | ---: | ---: |
| full-A | 12 | 151.73 | 2003.79 | 1671.20 |
| full-B | 12 | 164.90 | 1922.01 | 1800.20 |
| full-C-1 | 23 | 191.34 | 2253.59 | 1847.10 |
| full-C-2 | 24 | 191.56 | 2280.78 | 2128.70 |

## Reproduction

Use an activated Python 3.14 environment with the project dev/browser tools,
its installed Chromium and the isolated PostgreSQL service. Keep credentials
in ignored `.local/performance-tests.env`; never select an application database.
Create a new output directory for each invocation:

```bash
mkdir -p .local
result_dir="$(mktemp -d "$PWD/.local/template-measurement.XXXXXX")"
mkdir "$result_dir/metrics"
EPPM_TEST_MEASUREMENT_DIRECTORY="$result_dir/metrics" \
COVERAGE_FILE="$result_dir/.coverage" \
POSTGRES_TEST_CLIENT_CONTAINER=eppm-performance-tests-postgres-1 \
EPPM_RUN_OIDC_E2E=1 \
python -m dotenv -f .local/performance-tests.env run -- \
  python -m pytest -q -x -p no:cacheprovider \
  -p tests.performance.template_metrics --max-worker-restart=0 \
  FLAGS --require-full-suite --cov=app --cov-fail-under=95 \
  --cov-report="json:$result_dir/coverage.json"
node --test tests/test_*.cjs
```

Replace `FLAGS` with A: `-n 0 --postgres-test-db-mode=fresh`, B:
`-n 0 --postgres-test-db-mode=template`, C:
`-n 2 --dist=loadgroup --postgres-test-db-mode=template`. Set
`EPPM_BENCHMARK_BROWSER` to the installed Chromium executable if needed. Run
modes sequentially on otherwise uncontended measurement resources. Repeat C
with another fresh output directory. For cohorts replace strict/95% options
with all three cohort paths; retain coverage without claiming full acceptance.
The opt-in measurement plugin is not loaded by ordinary PR CI.

## Prerequisite delivery and superseded diagnostics

Setup PR #1 passed full CI and SonarCloud at `bc18f05`: 3,223 tests and five
subtests, 97.68% coverage and 108 JavaScript cases. Pytest took 2,882.72s and
its whole hosted job 3,031.937s. Hosted provisioning/timing is separate from
cached local measurements. The user approved merge commit `0b6ebb0`, followed
by the metadata-only feature reconciliation `fd80a5b`. Performance PR merging
requires separate approval. Public-repository visibility does not change tests.

Previous local series are diagnostic history, not acceptance for these sources:
- A completed earlier A/B pair at `c052f7c` ran 3,293 cases plus five subtests
  with 97.684036% coverage and 108 JavaScript cases. Fresh wall time was
  2,610.096823s; template wall time 1,892.740186s (27.48% lower). Its parallel
  run failed on dashboard selection readiness; task 3.5 adds the verified repair.
- The next series at `779f0b2` passed nine cohorts (65.68% preparation reduction)
  but serial/fresh failed after 694 passes on organization filtering:
  491.60s pytest / 493.605384s monitored. Task 3.6 records diagnosis, its exact
  causal limits and verified completion/render-readiness regression.
- The series at `55a517f` passed full A/B/C once (3,295 cases, five subtests,
  108 JavaScript cases and at least 97.678128% coverage). A/B/C wall times were
  2,684.217428s / 1,917.747534s / 1,043.677697s. Repeated C failed on the first
  finance-selection clear after 197 passes (48.23s pytest). Task 3.7 records
  the observed delivery/readiness gap and its limits. All v4 times are
  superseded diagnostics; the v5 series uses final completion-aware tests.
- The series at `bc1f4ba` passed fresh/template full references (3,299 cases,
  five subtests and 108 JavaScript cases) in 2,429.604527s / 1,811.475152s.
  Its first parallel run failed after 1,786 passes on stale project-form event
  observation (741.20s pytest / 742.098730s monitored). Task 3.8 proves that
  race with delayed event publication and retains all original assertions.
  These v5 results are superseded; the following series restart after the approved corrections.
- V6 at `ba24367` passes fresh reference (3,300 cases, five subtests,
  97.684036% and 108 JavaScript cases) in 2,437.556362s; template fails on
  Settings navigation after 3,235 passes. Task 3.9 restores completed-page
  reveal when transient browser running state is coalesced.
- V7 at `f8d7c0e` passes nine cohorts (66.389194% preparation reduction),
  but fresh reference fails after 1,833 passes on the 10,001-project
  concurrent-save case, 1,949.09s pytest / 1,950.755298s monitored.
  Task 3.10 adds approved project-table headroom with real HOT/upgrade/rollback
  regressions and unchanged concurrency/security/retry assertions.
- Earlier shutdown observation and external sampler/drop races are documented
  in task 3.4 evidence. The sampler counts only the expected missing-OID race;
  it does not ignore test failures. An interrupted old run's sealed template
  was recovered only after matching its exact name/OID/owner/closed state.

All comparisons restarted after each test-source correction. No partial or
failed run satisfies task 4.1, and no cross-source timing is used for promotion.

## Final acceptance audit

The slower optimized full run takes **1,277.208545s (21m17s)** versus
**2,537.813874s (42m18s)** fresh/serial, a **49.672884% reduction**. The repeated
optimized run takes **1,243.467171s (20m43s)**. Median preparation improves
**67.723838%**, meeting both original relative targets; there is no seven-minute
limit. Serial/template alone takes 2,123.056248s (35m23s), so preparation savings
are not presented as whole-suite savings.

All four full runs pass 3,304 canonical cases and five subtests, with exactly
one successful setup/call/teardown per case, no skips, worker restarts or
retries. All four execute all 112 Node cases with zero failures, cancellations,
skips or TODOs. Each full run prepares 2,261 migrated fixtures. Both workers do
real work: C1 schedules 958/2,346 calls and C2 984/2,320.

Canonical ordered collection SHA-256:
`49076554992fc6fedd32475eeda4bfe646d0839ceb8b6aa04b3186945fabbfd6`.
Coverage is identical in every full mode: 16,539/16,931 statements,
**97.684720%**, the same 283 source files and 499 excluded lines, with no
per-file missing-line differences. The 95% gate/source/exclusions remain intact.
All four cleanup checks report zero test databases and zero other server clients.
Resource peaks remain below the 40-client budget. Expected dropped-database
OID sampling races and missed Docker observations are counted in the raw
summary; they do not suppress test failures or establish hard resource maxima.

[measurements.json](measurements.json) preserves unrounded timings, package/image
versions, per-run coverage/resource/cleanup data and the independent outcome audit,
without credentials, fixture values or host checkout paths. Full per-fixture
records remain in ignored local measurement directories for inspection.

These are local pytest timings with cached tools/image plus monitoring overhead,
not hosted CI job timings. Unrelated development services were left running;
Docker memory sampling conservatively includes matching test deployment
prefixes and can include another invocation. The dedicated PostgreSQL service
has no other clients at comparison boundaries. Provisioning, image build and
browser installation are excluded from measured pytest wall time and remain
part of full PR CI. Hosted final-revision results will be recorded separately.
