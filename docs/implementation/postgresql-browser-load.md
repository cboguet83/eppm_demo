# Authenticated browser load acceptance

The explicit runner `python -m tests.performance.browser_load` creates a unique
`eppm-load-<random>` Compose deployment. It uses the built native candidate or the
preserved SQLite baseline image, an isolated Keycloak provider, generated
credentials, and separate application data. Normal exit and handled failures
remove only that deployment's containers and volumes. Private environment files,
archives and raw diagnostic files stay in ignored `.local/browser-load/` storage.
The ordinary application database, old SQLite files and existing volumes are not
modified.

The native operator seeds 10,001 projects with seed 42 and zero-to-fifteen tasks.
The SQLite run copies the preserved deterministic baseline fixture, verifies its
counts, and compares the source file's SHA-256 before and after the run. Both
fixtures have 73,929 tasks, 66,173 dependencies, 103 pools, 31 pool groups and
10,201 assignments. They start with no accounts; real Keycloak login creates the
benchmark identities. SQLite helpers live under `docs/archive/sqlite/benchmarks/`
and execute only inside that image. Active runtime, tools and tests still cannot
import SQLite storage.

Each browser context gets its own provider login and opaque application session.
The two fictional provider identities supply readers and editors; their distinct
application sessions are checked before measurement. Bootstrap is explicit, and
normal application services grant the intended permissions. No benchmark cookie
or identity bypass is installed in the application.

## Current pilot command

Build the candidate from the intended commit; the source-revision label and
actual image ID are recorded with the deployment's CPU/memory limits:

```powershell
$loadSourceCommit = git rev-parse HEAD
docker build --label "org.opencontainers.image.revision=$loadSourceCommit" -t eppm-demo:postgresql-load-candidate .
.venv/Scripts/python.exe -m tests.performance.browser_load --backend postgresql --readers 2 --editors 1 --rounds 1 --warmup-seconds 4 --measurement-seconds 12
.venv/Scripts/python.exe -m tests.performance.browser_load --backend sqlite --readers 2 --editors 1 --rounds 1 --warmup-seconds 4 --measurement-seconds 12
```

The SQLite image is `eppm-demo:sqlite-migration-baseline`, built from the preserved
revision documented in [comparison preparation](benchmarks/comparison-preparation.json).
An explicit `--image` can select another built candidate. The runner defaults to
40 readers, 10 editors, three measurements of 600 seconds, and 120-second warmups.
Those defaults do not establish acceptance: the prescribed workload, browser
rendering breakdown and complete results still need to be run and reviewed.

## Actions and observation

Half of the readers scroll the actual portfolio master list to uncached pages;
the others expand projects in the real planning component and wait for loaded
task rows. Editors change a project title and save through the actual form. Each
editor owns a different selected project. Edits must produce the updated details
and save confirmation. The load generator offers actions approximately every two
seconds; recorded workflow durations expose when processing prevents that cadence.

Browser timestamps start at scrollbar movement or the actual pointer event and
finish after the usable-result condition and a rendering frame. Results keep each
scenario and measurement period separate. Failed actions remain failures and
cannot acquire a fabricated low latency. A failed worker continues offering its
next actions and every configured round still runs. The runner does not reset the
page or erase failures to recover a successful result. Slow actions can reduce
the achieved cadence; actual attempts and workflow durations remain visible.
Failure while collecting a viewport diagnostic cannot erase the original failed
action. Historical pilots stopped failed workers and are identified separately.
Cold preparation, warmup actions and badge HTTP responses are separate evidence.

Benchmark-only mounted observers retain actual method arguments, results and
exceptions while accumulating client database-call times, pool acquisition and
native pool counters, Streamlit execution, HTTP reader execution, process CPU and
maximum RSS. They record no SQL, parameters, cookies, credentials or exception
messages. On database failure, only its category and application code locations
are retained. A failed native planning preparation also requests a read-only,
signed-reader `EXPLAIN`; expressions and literal values are excluded from the
saved plan.

The native test cluster enables `pg_stat_statements` and I/O timing. Its separate
operator monitor records cumulative top-level runtime statement execution and
block counts, plus active wait categories sampled approximately every 250 ms.
Sampling estimates waits; it cannot prove that shorter waits never occurred.
SQLite client SQL durations include its native locking waits, for which the
driver provides no separate counter. There is no SQLite connection pool.

`container-timings.jsonl` samples only the deployment's explicit full container
IDs with `docker stats`, approximately every two seconds. CPU percentages use
Docker's per-core scale and can exceed 100%; memory bytes are approximate because
Docker formats quantities with limited precision. The observer retains only
numeric utilization fields and safe failure categories. It does not retain
container environments or command/error text, and does not alter the containers.

`diagnostic_phases` records warmup and measurement windows independently. Runtime
and database counter differences use only complete samples inside each phase,
with first/last timestamps and the actual observed duration. Missing observations
are insufficient evidence rather than zero work; decreasing/disappearing counters
are flagged as resets. Runtime maxima are not subtracted as though cumulative
maxima were additive counters. Database wait occupancy is a sampled estimate,
not a count of every wait. Container summaries retain failed-sample counts.
`scheduled_seconds` describes the offered phase; its final timestamp includes
completion of an action started before that phase's deadline. Nested server,
cache and database timings overlap and must not be summed into total latency.

For diagnostic pilots only, `--profile` samples application thread stacks every
20 ms into `data/thread-profiles.json`. It retains code locations and counts,
never frame locals, arguments or source lines. Storage is bounded to 10,000
distinct stacks, with dropped observations reported explicitly. These samples
locate waiting/processing paths; they are not exact function durations or
acceptance timings. The usual service/cache boundary timers remain available.
Concurrent worker preservation, value exclusion, the storage bound and sampler
shutdown passed three targeted tests (14 checks including reporting/import guards).

The discarded initial diagnostic wrapper attempted concurrent `cProfile`
instances; Python 3.14 rejects a second active profiler. This was reproduced with
two local threads. The stack sampler uses no profiling hook and the replacement
three-session pilot completed all preparations and actions successfully.

That diagnostic run is retained at `.local/browser-load/52f3d5e8c50a/`, using the
unchanged `89b5b0e` application image. Seven project updates spent 3.61 seconds
inside the service; property parent writes were the deepest application frame in
132 samples. Revision reads and derived-cache reads/publication accounted for
most other observed database waits. The run had zero workflow failures; measured
p95 values were 941.1 ms paging, 5,424 ms task loading and 1,938.3 ms saves.
Its tiny, instrumented sample is diagnostic evidence only.

## Recorded results and remaining work

The [pilot summary](benchmarks/browser-pilot-results.json) records three sessions
per backend. Initial native planning reached its 10-second statement timeout
without current planner statistics. `80abb88` makes bulk seeding refresh those
statistics before first use. Both original images also lost a pending scroll
after a concurrent project edit; `89b5b0e` preserves the requested page while
reauthorizing its data.

The rebuilt native candidate completed **18 workflow attempts including warmup
with zero failures**. Its short measured period contains only six paging, two
task-loading and five save samples. Their nearest-rank p95 values are 966.7 ms,
10,257.7 ms and 1,844.4 ms respectively. These few samples diagnose work still
needed; they are not a statistical backend comparison or the 50-user acceptance
run. The historical SQLite pilot had three failures across ten attempts including
warmup, so its reduced workload must not be compared as equivalent throughput.

Next work is to investigate task-loading/save latency during edits, add the
browser-rendering breakdown, and run the complete prescribed workload with its
per-period diagnostics. The runner deliberately leaves
`acceptance_complete` false. The final application regression/coverage gate also
needs refreshing after performance fixes. Pilot-report and active-import guards
passed **11 tests in 2.29 seconds**; native recovery remains recorded separately.

The later [property-save pilot](benchmarks/property-save-pilot-results.json) uses
the separate `eppm-demo:postgresql-property-candidate` image at `aedc105`. It
completed 18 attempts including warmup without workflow failures. Service update
time was 0.599 seconds across eight updates; six measured browser saves had p95
1,323.3 ms. The single measured task load still took 13,137.4 ms, with repeated
HTTP revision conflicts in the run. This confirms remaining refresh work and
does not meet the required workload or one-second acceptance target.

The [revision-query pilot](benchmarks/revision-browser-pilot-results.json) uses
`eppm-demo:postgresql-revision-candidate` at `e53d924`, including migration 0023.
It completed 19 attempts including warmup with zero workflow failures. Measured
p95 values were 651.8 ms paging, 1,104.1 ms saves and 7,605.9 ms task loading, from
six, six and two samples respectively. Task and badge revision conflicts remain
visible in the report. These results keep the complete load gate open.

The [bounded-cache pilot](benchmarks/bounded-cache-browser-pilot-results.json)
used migration 0024 at `ad7a456` and completed 20 attempts including warmup, with
zero workflow/database failures. Its measured p95 values were 736.5 ms paging,
1,291.7 ms saves and 6,284.3 ms task loading (six, six and three samples). Five
task responses and six badge responses still reported changed revisions.

A second pilot validated the new resource and phase observers against the same
application image. All 18 container samples succeeded. Its measured window had
seven resource samples, averaging 64.43% app CPU and 120.36% PostgreSQL CPU, with
no recorded native pool waits. The separate runtime/database windows report
their precise coverage rather than claiming complete observation. These tiny
diagnostic samples do not satisfy acceptance or establish statistical improvement.
See [the instrumentation evidence](benchmarks/resource-observer-pilot-results.json).
The final reporting/sampling/import run passed 33 checks in 1.68 seconds, including
continued attempts after a failed workflow and a failed viewport diagnostic.
That failure-continuation refinement was made after the second pilot started and
is covered by the focused regression, not claimed as part of that pilot's run.

The [migration 0026 pilots](benchmarks/task-pool-browser-pilot-results.json)
had no task HTTP revision conflicts, but each still failed one save confirmation.
The longer run retained three badge HTTP 409 responses. It found the expected new
title in the visible details panel after the editor closed, with no alert and
no success confirmation text. The root cause remains under investigation.
The failed editor reduced the offered write load, so the subsecond reader
samples do not satisfy acceptance. Save failures now include their workflow
stage and safe boolean/count/timing observations; no form values are retained.

## Browser processing observations

Every authenticated browser target enables Chromium's CDP `Performance` counters.
Before and after each workflow, the runner reads only numeric layout/style/script/
task durations and layout/style recalculation counts. It retains the differences
and the browser clock's observed interval in each sample's `browser_processing`.
The workflow includes editor opening or task-collapse preparation; these diagnostic
windows are deliberately separate from the existing browser-action-to-result
latency. Missing observations and counter/clock resets cannot become zero cost.

Each warmup/measurement phase reports processing per scenario, including failed
workflows and the number of missing observations. Nested script/layout/style/task
durations can overlap and must not be summed into total latency. These counters
measure renderer processing, not GPU execution or separate paint duration; the
usable-result timer still waits for a browser animation frame. No CDP trace,
page content, arbitrary metric fields, request URLs or credentials are retained.

The observer and reporting checks passed **42 tests in 2.32 seconds**, including
real Chromium layout/style work and safe handling of invalid/missing counters.
Log: `.local/postgresql-browser-metrics-final.log`. An actual application pilot
and the full prescribed comparison still need to verify these streams under load.
