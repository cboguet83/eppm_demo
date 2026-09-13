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
Those defaults do not establish acceptance: the prescribed workload and complete
diagnostic aggregation still need to be run and reviewed.

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
cannot acquire a fabricated low latency. A failed worker currently stops that
period; its missing offered load is another reason such a run cannot be accepted.
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

Next work is to investigate task-loading/save latency during edits, add container
utilization and browser-rendering breakdowns, aggregate diagnostics for each
period, and run the complete prescribed workload. The runner deliberately leaves
`acceptance_complete` false. The final application regression/coverage gate also
needs refreshing after performance fixes. Pilot-report and active-import guards
passed **11 tests in 2.29 seconds**; native recovery remains recorded separately.
